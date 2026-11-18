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


import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy
from typing import Any

import requests
import urllib3
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict
from urllib3.util.retry import Retry

from pyhugegraph.utils.authentication import request_auth
from pyhugegraph.utils.compat import ServerAdapter
from pyhugegraph.utils.constants import Constants
from pyhugegraph.utils.exceptions import ResponseTooLargeError
from pyhugegraph.utils.huge_config import HGraphConfig, normalize_timeout
from pyhugegraph.utils.log import log
from pyhugegraph.utils.util import ResponseValidation, redact_sensitive_data


def _tighten_response_socket_timeout(response: requests.Response, effective_deadline: float) -> None:
    remaining = effective_deadline - time.monotonic()
    if remaining <= 0:
        raise requests.exceptions.ReadTimeout("Response exceeded total deadline")
    try:
        sock = getattr(getattr(getattr(getattr(response, "raw", None), "_fp", None), "fp", None), "raw", None)
        sock = getattr(sock, "_sock", None)
        if sock is not None and hasattr(sock, "settimeout"):
            existing = sock.gettimeout() if hasattr(sock, "gettimeout") else None
            target = remaining if existing is None else min(existing, remaining)
            sock.settimeout(target)
    except Exception:
        pass


_REQUEST_RETRIES: ContextVar[bool] = ContextVar("hugegraph_request_retries", default=True)
_REQUEST_MAX_RESPONSE_BYTES: ContextVar[int | None] = ContextVar("hugegraph_request_max_response_bytes", default=None)
_REQUEST_DEADLINE: ContextVar[float | None] = ContextVar("hugegraph_request_deadline", default=None)


class _RetryAdapter(HTTPAdapter):
    def __copy__(self):
        # HTTPAdapter's pickle hooks recreate pools; bypass them for this
        # request-local policy copy and retain the original pool ownership.
        adapter = type(self).__new__(type(self))
        adapter.__dict__.update(self.__dict__)
        return adapter

    def send(self, request, *args, **kwargs):
        # Requests has no per-request retry option. A context-local policy and a
        # shallow adapter copy retain the same pools without mutating other calls.
        adapter = self
        if not _REQUEST_RETRIES.get():
            adapter = copy(self)
            adapter.max_retries = Retry(total=0)
        return HTTPAdapter.send(adapter, request, *args, **kwargs)


class HGraphSession:
    def __init__(
        self,
        cfg: HGraphConfig,
        retries: int = 3,
        backoff_factor: float = 0.1,
        status_forcelist=(500, 502, 504),
        session: requests.Session | None = None,
    ):
        """
        Initialize the HGraphSession object.
        :param retries: The maximum number of retries.
        :param backoff_factor: The backoff factor, used to calculate the interval between retries.
        :param status_forcelist: A list of status codes that trigger a retry.
        :param session: An optional requests.Session instance, for testing or advanced use cases.
        """
        self._cfg = cfg
        self.adapter = ServerAdapter(cfg)
        self._closed = False
        self._retries = retries
        self._backoff_factor = backoff_factor
        self._status_forcelist = status_forcelist
        self._auth = (cfg.username, cfg.password)
        self._headers = {"Content-Type": Constants.HEADER_CONTENT_TYPE}
        self._timeout = normalize_timeout(cfg.timeout)
        self._session = session if session else requests.Session()
        self.__configure_session()

    def __configure_session(self):
        """
        Configure the retry strategy and connection adapter for the session.
        """
        retry_strategy = Retry(
            total=self._retries,
            read=self._retries,
            connect=self._retries,
            backoff_factor=self._backoff_factor,
            status_forcelist=self._status_forcelist,
        )
        adapter = _RetryAdapter(max_retries=retry_strategy)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        log.debug(
            "Session configured with retries=%s and backoff_factor=%s",
            self._retries,
            self._backoff_factor,
        )

    @property
    def timeout(self) -> tuple[float, float]:
        return self._timeout

    @property
    def cfg(self):
        """
        Get the configuration information of the current instance.

        Args:
            None.

        Returns:
        -------
            HGraphConfig: The configuration information of the current instance.
        """
        return self._cfg

    def resolve(self, path: str):
        """
        Constructs the full URL for the given pathinfo based on the session context and API version.

        :param path: The pathinfo to be appended to the base URL.
        :return: The fully resolved URL as a string.

        When path is "/some/things":
        - Since path starts with "/", it is considered an absolute path,
          and urljoin will replace the path part of the base URL.
        - Assuming the base URL is "http://127.0.0.1:8000/graphspaces/default/graphs/test_graph/"
        - The result will be "http://127.0.0.1:8000/some/things"

        When path is "some/things":
        - Since path is a relative path, urljoin will append it to the path part of the base URL.
        - Assuming the base URL is "http://127.0.0.1:8000/graphspaces/default/graphs/test_graph/"
        - The result will be "http://127.0.0.1:8000/graphspaces/default/graphs/test_graph/some/things"
        """

        return self.adapter.resolve(path)

    def use_token(self, token: str | None) -> None:
        if token is None:
            self._headers.pop("Authorization", None)
        else:
            if not token.strip():
                raise ValueError("token must not be empty")
            self._headers["Authorization"] = f"Bearer {token}"

    def close(self):
        """
        closes the session.

        Args:
            None

        Returns:
            None

        """
        if not self._closed:
            self._session.close()
            self._closed = True

    @contextmanager
    def request_guard(
        self,
        *,
        max_response_bytes: int | None = None,
        deadline_seconds: float | None = None,
        retries: bool | None = None,
    ):
        """Apply bounded response size, total deadline, and retry policy to nested requests."""
        if max_response_bytes is not None and max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if deadline_seconds is not None and deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        tokens: list[tuple[ContextVar[Any], Any]] = []
        if max_response_bytes is not None:
            tokens.append((_REQUEST_MAX_RESPONSE_BYTES, _REQUEST_MAX_RESPONSE_BYTES.set(max_response_bytes)))
        if deadline_seconds is not None:
            tokens.append((_REQUEST_DEADLINE, _REQUEST_DEADLINE.set(time.monotonic() + deadline_seconds)))
        if retries is not None:
            tokens.append((_REQUEST_RETRIES, _REQUEST_RETRIES.set(retries)))
        try:
            yield
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    def request(
        self,
        path: str,
        method: str = "GET",
        validator=None,
        retries: bool | None = None,
        max_response_bytes: int | None = None,
        deadline_seconds: float | None = None,
        **kwargs: Any,
    ) -> Any:
        if validator is None:
            validator = ResponseValidation()
        if self._closed:
            raise RuntimeError("The HugeGraph client is closed")
        url = self.resolve(path)
        headers = CaseInsensitiveDict(self._headers)
        request_headers = kwargs.pop("headers", None) or {}
        headers.update({key: value for key, value in request_headers.items() if value is not None})
        auth = request_auth(headers, self._auth)
        timeout = kwargs.pop("timeout", self._timeout)

        effective_max_bytes = (
            max_response_bytes if max_response_bytes is not None else _REQUEST_MAX_RESPONSE_BYTES.get()
        )
        effective_retries = _REQUEST_RETRIES.get() if retries is None else retries
        effective_deadline = _REQUEST_DEADLINE.get()
        if deadline_seconds is not None:
            if deadline_seconds <= 0:
                raise ValueError("deadline_seconds must be positive")
            candidate_deadline = time.monotonic() + deadline_seconds
            effective_deadline = (
                candidate_deadline if effective_deadline is None else min(effective_deadline, candidate_deadline)
            )

        if effective_deadline is not None:
            remaining = effective_deadline - time.monotonic()
            if remaining <= 0:
                raise requests.exceptions.ReadTimeout("Request deadline exceeded before dispatch")
            if isinstance(timeout, tuple) and len(timeout) == 2:
                timeout = (min(float(timeout[0]), remaining), min(float(timeout[1]), remaining))
            elif isinstance(timeout, int | float):
                timeout = min(float(timeout), remaining)
            elif timeout is None:
                timeout = remaining

        if effective_max_bytes is not None:
            if effective_max_bytes <= 0:
                raise ValueError("max_response_bytes must be positive")
            kwargs["stream"] = True
            kwargs["allow_redirects"] = False
        elif effective_deadline is not None:
            kwargs["stream"] = True
            kwargs["allow_redirects"] = False

        policy = _REQUEST_RETRIES.set(effective_retries)
        try:
            response: requests.Response = getattr(self._session, method.lower())(
                url,
                auth=auth,
                headers=headers,
                timeout=timeout,
                **kwargs,
            )
            if effective_max_bytes is not None or effective_deadline is not None:
                try:
                    if effective_max_bytes is not None:
                        raw_cl = response.headers.get("Content-Length") if hasattr(response, "headers") else None
                        if raw_cl is not None:
                            try:
                                cl_val = int(raw_cl)
                            except (TypeError, ValueError):
                                cl_val = None
                            if cl_val is not None and cl_val > effective_max_bytes:
                                raise ResponseTooLargeError(effective_max_bytes, actual_bytes=cl_val)
                    buf = bytearray()
                    if effective_deadline is not None:
                        _tighten_response_socket_timeout(response, effective_deadline)
                    chunk_limit = min(16384, effective_max_bytes) if effective_max_bytes is not None else 16384
                    raw_stream = getattr(response, "raw", None)
                    read1_fn = getattr(raw_stream, "read1", None) if raw_stream is not None else None
                    if callable(read1_fn) and hasattr(raw_stream, "decode_content"):
                        while True:
                            if effective_deadline is not None:
                                _tighten_response_socket_timeout(response, effective_deadline)
                            try:
                                chunk = read1_fn(chunk_limit, decode_content=True)
                            except urllib3.exceptions.ReadTimeoutError as exc:
                                raise requests.exceptions.ReadTimeout(exc, response=response) from exc
                            if effective_deadline is not None and time.monotonic() > effective_deadline:
                                raise requests.exceptions.ReadTimeout("Response exceeded total deadline")
                            if not chunk:
                                break
                            buf.extend(chunk)
                            if effective_max_bytes is not None and len(buf) > effective_max_bytes:
                                raise ResponseTooLargeError(effective_max_bytes, actual_bytes=len(buf))
                    else:
                        for chunk in response.iter_content(chunk_size=chunk_limit):
                            if effective_deadline is not None and time.monotonic() > effective_deadline:
                                raise requests.exceptions.ReadTimeout("Response exceeded total deadline")
                            if not chunk:
                                continue
                            buf.extend(chunk)
                            if effective_max_bytes is not None and len(buf) > effective_max_bytes:
                                raise ResponseTooLargeError(effective_max_bytes, actual_bytes=len(buf))
                            if effective_deadline is not None:
                                _tighten_response_socket_timeout(response, effective_deadline)
                    if effective_deadline is not None and time.monotonic() > effective_deadline:
                        raise requests.exceptions.ReadTimeout("Response exceeded total deadline")
                    response._content = bytes(buf)
                    response._content_consumed = True
                finally:
                    response.close()
        finally:
            _REQUEST_RETRIES.reset(policy)
        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "Request: %s %s validator=%s kwargs=%s %s",
                method,
                url,
                validator,
                redact_sensitive_data(kwargs),
                response,
            )
        return validator(response, method=method, path=path)
