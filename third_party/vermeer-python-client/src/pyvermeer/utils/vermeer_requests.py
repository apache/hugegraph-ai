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
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pyvermeer.utils.exception import ConnectError, JsonDecodeError, TimeOutError, UnknownError
from pyvermeer.utils.log import log
from pyvermeer.utils.vermeer_config import VermeerConfig


class VermeerSession:
    """vermeer session"""

    def __init__(
        self,
        cfg: VermeerConfig,
        retries: int = 3,
        backoff_factor: int = 0.1,
        status_forcelist=(500, 502, 504),
        session: requests.Session | None = None,
    ):
        """
        Initialize the Session.
        """
        self._cfg = cfg
        self._retries = retries
        self._backoff_factor = backoff_factor
        self._status_forcelist = status_forcelist
        if self._cfg.token is not None:
            self._auth = self._cfg.token
        else:
            raise ValueError("Vermeer Token must be provided.")
        self._headers = {"Content-Type": "application/json", "Authorization": self._auth}
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

    def resolve(self, path: str):
        """
        Resolve the path to a full URL.
        """
        url = f"http://{self._cfg.ip}:{self._cfg.port}/"
        return urljoin(url, path).strip("/")

    def close(self):
        """
        closes the session.
        """
        self._session.close()

    def request(self, method: str, path: str, params: dict | None = None) -> dict:
        """request"""
        try:
            log.debug(f"Request made to {path} with params {json.dumps(params)}")
            response = self._session.request(
                method, self.resolve(path), headers=self._headers, data=json.dumps(params), timeout=self._timeout
            )
            log.debug(f"Response code:{response.status_code}, received: {response.text}")
            return response.json()
        except requests.ConnectionError as e:
            raise ConnectError(e) from e
        except requests.Timeout as e:
            raise TimeOutError(e) from e
        except json.JSONDecodeError as e:
            raise JsonDecodeError(e) from e
        except Exception as e:
            raise UnknownError(e) from e
