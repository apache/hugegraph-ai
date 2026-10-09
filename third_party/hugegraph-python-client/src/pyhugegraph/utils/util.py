# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.


import json
import re
import traceback

import requests

from pyhugegraph.utils.exceptions import (
    NotAuthorizedError,
    NotFoundError,
    ResponseParseError,
    ServerError,
    ServiceUnavailableError,
)
from pyhugegraph.utils.log import log

REDACTED_VALUE = "***REDACTED***"
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
)
ESCAPE_MARKERS = ("\\u", "\\U", "\\x", "\\n", "\\r", "\\t")
RESPONSE_CONTENT_TYPES = {"raw", "json", "text"}


def _is_sensitive_key(key) -> bool:
    key_lower = str(key).lower()
    return any(part in key_lower for part in SENSITIVE_KEY_PARTS)


def _may_contain_sensitive_key(value: str) -> bool:
    value_lower = value.lower()
    return any(part in value_lower for part in SENSITIVE_KEY_PARTS)


def _decode_escaped_text(value):
    if not isinstance(value, str) or "\\" not in value:
        return value
    if not any(marker in value for marker in ESCAPE_MARKERS):
        return value
    return value.encode("utf-8", errors="replace").decode("unicode_escape", errors="replace")


def redact_sensitive_data(value):
    if isinstance(value, dict):
        return {
            key: REDACTED_VALUE if _is_sensitive_key(key) else redact_sensitive_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        if not _may_contain_sensitive_key(value):
            return value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            redacted = re.sub(
                r'(?i)("?[a-z0-9_-]*(?:api_key|authorization|password|passwd|pwd|secret|token)[a-z0-9_-]*"?\s*[:=]\s*)"[^"]*"',
                rf"\1\"{REDACTED_VALUE}\"",
                value,
            )
            return re.sub(
                r"(?i)(api_key|authorization|password|passwd|pwd|secret|token)=([^&\s]+)",
                rf"\1={REDACTED_VALUE}",
                redacted,
            )
        return json.dumps(redact_sensitive_data(parsed), ensure_ascii=False)
    return value


def create_exception(response_content):
    try:
        data = json.loads(response_content)
        if "ServiceUnavailableException" in data.get("exception", ""):
            raise ServiceUnavailableError(
                f'ServiceUnavailableException, "message": "{data["message"]}", "cause": "{data["cause"]}"'
            )
    except (json.JSONDecodeError, KeyError) as e:
        raise Exception(f"Error parsing response content: {response_content}") from e
    raise Exception(response_content)


def check_if_authorized(response):
    if response.status_code == 401:
        raise NotAuthorizedError(f"Please check your username and password. {response.content!s}")
    return True


def check_if_success(response, error=None):
    if (not str(response.status_code).startswith("20")) and check_if_authorized(response):
        if error is None:
            error = NotFoundError(response.content)

        req = response.request
        req_body = redact_sensitive_data(req.body) if req.body else "Empty body"
        response_body = redact_sensitive_data(response.text) if response.text else "Empty body"
        log.error(
            "Error-Client: Request URL: %s, Request Body: %s, Response Body: %s",
            req.url,
            req_body,
            response_body,
        )
        raise error
    return True


class ResponseValidation:
    def __init__(self, content_type: str = "json", strict: bool = True) -> None:
        super().__init__()
        self._content_type = content_type
        self._strict = strict

    def __call__(self, response: requests.Response, method: str, path: str):
        """
        Validate the HTTP response according to the provided content type and strictness.

        :param response: HTTP response object
        :param method: HTTP method used (e.g., 'GET', 'POST')
        :param path: URL path of the request
        :return: Parsed response content or empty dict if none applicable
        """
        if self._content_type not in RESPONSE_CONTENT_TYPES:
            raise ValueError(f"Unknown content type: {self._content_type}")

        result = {}

        try:
            response.raise_for_status()
            if response.status_code == 204:
                log.debug("No content returned (204) for %s: %s", method, path)
            else:
                if self._content_type == "raw":
                    result = response
                elif self._content_type == "json":
                    result = response.json()
                elif self._content_type == "text":
                    result = response.text

        except requests.exceptions.HTTPError as e:
            if not self._strict and response.status_code == 404:
                log.info("Resource %s not found (404)", path)
            else:
                if response.status_code == 401:
                    check_if_authorized(response)

                try:
                    body = response.json()
                    if isinstance(body, dict):
                        status = body.get("status")
                        status_message = status.get("message") if isinstance(status, dict) else None
                        details = (
                            body.get("message")
                            or body.get("exception")
                            or status_message
                            or response.text
                            or "unknown error"
                        )
                    else:
                        details = response.text or "unknown error"
                except (ValueError, KeyError, AttributeError, TypeError):
                    details = response.text or "unknown error"

                req_body = redact_sensitive_data(response.request.body) if response.request.body else "Empty body"
                req_body = _decode_escaped_text(req_body)
                log.error(
                    "%s: %s\n[Body]: %s\n[Server Exception]: %s",
                    method,
                    _decode_escaped_text(str(e)),
                    req_body,
                    details,
                )

                if response.status_code == 404:
                    raise NotFoundError(response.content) from e
                raise ServerError(f"Server Exception: {details}") from e

        except Exception as e:
            log.error("Unhandled exception occurred: %s", traceback.format_exc())
            raise ResponseParseError(f"Failed to parse {self._content_type} response for {method} {path}") from e

        return result

    def __repr__(self) -> str:
        return f"ResponseValidation(content_type={self._content_type}, strict={self._strict})"
