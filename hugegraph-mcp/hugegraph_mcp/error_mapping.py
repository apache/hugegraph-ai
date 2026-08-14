# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared HugeGraph exception classification helpers."""

from dataclasses import dataclass

from pyhugegraph.utils.exceptions import (
    DataFormatError,
    InvalidParameterError,
    NotAuthorizedError,
    NotFoundError,
    ResponseParseError,
    ServerError,
    ServiceUnavailableError,
)

from hugegraph_mcp.envelope import ErrorType


@dataclass(frozen=True)
class ErrorClassification:
    error_type: ErrorType
    retryable: bool
    suggestion: str
    reason: str


NO_INDEX_MARKERS = (
    "noindexexception",
    "no index",
    "not indexed",
    "may not match secondary condition",
)
SCHEMA_MISSING_MARKERS = (
    "property key does not exist",
    "propertykey does not exist",
    "vertex label does not exist",
    "vertexlabel does not exist",
    "edge label does not exist",
    "edgelabel does not exist",
    "schema does not exist",
)
NOT_FOUND_MARKERS = (
    "404",
    "notfound",
    "not found",
    "not exist",
    "does not exist",
)


def classify_hugegraph_exception(exc: Exception) -> ErrorClassification:
    if isinstance(exc, NotAuthorizedError):
        return ErrorClassification(
            error_type=ErrorType.AUTHENTICATION_FAILED,
            retryable=False,
            suggestion="Check HUGEGRAPH_USER and HUGEGRAPH_PASSWORD.",
            reason="authentication_error",
        )
    if isinstance(exc, NotFoundError):
        return ErrorClassification(
            error_type=ErrorType.NOT_FOUND,
            retryable=False,
            suggestion="Verify the graph, graphspace, and endpoint before retrying.",
            reason="not_found_error",
        )
    if isinstance(exc, (InvalidParameterError, DataFormatError)):
        return ErrorClassification(
            error_type=ErrorType.VALIDATION_ERROR,
            retryable=False,
            suggestion="Check the request parameters and data format.",
            reason="validation_error",
        )
    if isinstance(exc, ServiceUnavailableError):
        return ErrorClassification(
            error_type=ErrorType.SERVER_ERROR,
            retryable=True,
            suggestion="Retry after checking HugeGraph Server availability.",
            reason="server_error",
        )
    if isinstance(exc, ResponseParseError):
        return ErrorClassification(
            error_type=ErrorType.SERVER_ERROR,
            retryable=False,
            suggestion="Check the HugeGraph response and client/server compatibility.",
            reason="server_error",
        )
    if isinstance(exc, ServerError):
        return classify_hugegraph_error_message(str(exc))
    return classify_hugegraph_error_message(str(exc))


def classify_hugegraph_error_message(message: str) -> ErrorClassification:
    lowered = message.lower()
    if any(marker in lowered for marker in NO_INDEX_MARKERS):
        return ErrorClassification(
            error_type=ErrorType.NO_INDEX,
            retryable=False,
            suggestion="Create an index for this condition query or retry with exact id lookup.",
            reason="no_index",
        )
    if any(marker in lowered for marker in SCHEMA_MISSING_MARKERS):
        return ErrorClassification(
            error_type=ErrorType.SCHEMA_MISMATCH,
            retryable=False,
            suggestion="Check the live schema, label, and property key before retrying.",
            reason="schema_missing",
        )
    if any(marker in lowered for marker in NOT_FOUND_MARKERS):
        return ErrorClassification(
            error_type=ErrorType.NOT_FOUND,
            retryable=False,
            suggestion="Verify the id, target type, graph, and graphspace before retrying.",
            reason="not_found",
        )
    return ErrorClassification(
        error_type=ErrorType.SERVER_ERROR,
        retryable=True,
        suggestion="Check query parameters and HugeGraph Server availability.",
        reason="server_error",
    )
