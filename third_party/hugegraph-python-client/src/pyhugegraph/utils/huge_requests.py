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
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pyhugegraph.utils.constants import Constants
from pyhugegraph.utils.huge_config import HGraphConfig
from pyhugegraph.utils.log import log
from pyhugegraph.utils.util import ResponseValidation, redact_sensitive_data


class HGraphSession:
    def __init__(
        self,
        cfg: HGraphConfig,
        retries: int = 3,
        backoff_factor: int = 0.1,
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
        self._retries = retries
        self._backoff_factor = backoff_factor
        self._status_forcelist = status_forcelist
        self._auth = (cfg.username, cfg.password)
        self._headers = {"Content-Type": Constants.HEADER_CONTENT_TYPE}
        self._timeout = cfg.timeout
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
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._session.keep_alive = False
        log.debug(
            "Session configured with retries=%s and backoff_factor=%s",
            self._retries,
            self._backoff_factor,
        )

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

        url = f"{self._cfg.url}/"
        if self._cfg.gs_supported:
            url = urljoin(
                url,
                f"graphspaces/{self._cfg.graphspace}/graphs/{self._cfg.graph_name}/",
            )
        else:
            url = urljoin(url, f"graphs/{self._cfg.graph_name}/")
        return urljoin(url, path).strip("/")

    def close(self):
        """
        closes the session.

        Args:
            None

        Returns:
            None

        """
        self._session.close()

    def request(
        self,
        path: str,
        method: str = "GET",
        validator=None,
        **kwargs: Any,
    ) -> dict:
        if validator is None:
            validator = ResponseValidation()
        url = self.resolve(path)
        response: requests.Response = getattr(self._session, method.lower())(
            url,
            auth=self._auth,
            headers=self._headers,
            timeout=self._timeout,
            **kwargs,
        )
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
