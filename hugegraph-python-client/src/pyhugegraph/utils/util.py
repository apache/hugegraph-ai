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
import traceback

import requests

from pyhugegraph.utils.exceptions import (
    NotAuthorizedError,
    NotFoundError,
    ServiceUnavailableError,
)
from pyhugegraph.utils.log import log


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
        req_body = req.body if req.body else "Empty body"
        response_body = response.text if response.text else "Empty body"
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
                else:
                    raise ValueError(f"Unknown content type: {self._content_type}")

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

                req_body = response.request.body if response.request.body else "Empty body"
                req_body = req_body.encode("utf-8").decode("unicode_escape")
                log.error(
                    "%s: %s\n[Body]: %s\n[Server Exception]: %s",
                    method,
                    str(e).encode("utf-8").decode("unicode_escape"),
                    req_body,
                    details,
                )

                if response.status_code == 404:
                    raise NotFoundError(response.content) from e
                raise Exception(f"Server Exception: {details}") from e

        except Exception:  # pylint: disable=broad-exception-caught
            log.error("Unhandled exception occurred: %s", traceback.format_exc())

        return result

    def __repr__(self) -> str:
        return f"ResponseValidation(content_type={self._content_type}, strict={self._strict})"
