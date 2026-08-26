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

"""Hard write-plan limits shared by schema and graph-data dry-run."""

from __future__ import annotations

import json
from typing import Any

from hugegraph_mcp.envelope import ErrorType, envelope_err

MAX_OPERATIONS = 200
MAX_PAYLOAD_BYTES = 1_048_576  # 1 MiB


def payload_byte_size(payload: Any) -> int:
    """Return a conservative UTF-8 JSON size for the write payload."""

    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    return len(encoded.encode("utf-8"))


def collect_write_limit_errors(
    operation_count: int,
    payload: Any,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if operation_count > MAX_OPERATIONS:
        errors.append(
            {
                "operation_index": -1,
                "operation": None,
                "reason": (
                    f"operation count {operation_count} exceeds "
                    f"MAX_OPERATIONS ({MAX_OPERATIONS})"
                ),
                "suggestion": (
                    f"Split the request so it contains at most {MAX_OPERATIONS} "
                    "operations, then retry dry-run."
                ),
                "error_type": ErrorType.VALIDATION_ERROR.value,
            }
        )
    size = payload_byte_size(payload)
    if size > MAX_PAYLOAD_BYTES:
        errors.append(
            {
                "operation_index": -1,
                "operation": None,
                "reason": (
                    f"payload size {size} exceeds MAX_PAYLOAD_BYTES "
                    f"({MAX_PAYLOAD_BYTES})"
                ),
                "suggestion": (
                    "Reduce the JSON payload to at most 1 MiB (1048576 bytes), "
                    "then retry dry-run."
                ),
                "error_type": ErrorType.VALIDATION_ERROR.value,
            }
        )
    return errors


def write_limit_envelope(
    operation_count: int,
    payload: Any,
) -> dict[str, Any] | None:
    """Return a VALIDATION_ERROR envelope when hard limits are exceeded."""

    errors = collect_write_limit_errors(operation_count, payload)
    if not errors:
        return None
    return envelope_err(
        ErrorType.VALIDATION_ERROR,
        "Write plan exceeds hard operation or payload limits.",
        suggestion=(
            f"Reduce the number of operations to {MAX_OPERATIONS} or fewer "
            "and the JSON payload to at most 1 MiB, then retry dry-run."
        ),
        details={
            "errors": errors,
            "max_operations": MAX_OPERATIONS,
            "max_payload_bytes": MAX_PAYLOAD_BYTES,
        },
    )


def operation_count_from_list(operations: Any) -> int:
    return len(operations) if isinstance(operations, list) else 0


def graph_data_operation_count(graph_data: Any) -> int:
    if not isinstance(graph_data, dict):
        return 0
    count = 0
    vertices = graph_data.get("vertices")
    edges = graph_data.get("edges")
    if isinstance(vertices, list):
        count += len(vertices)
    if isinstance(edges, list):
        count += len(edges)
    return count
