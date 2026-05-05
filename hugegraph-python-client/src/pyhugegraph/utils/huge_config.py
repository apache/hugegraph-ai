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

import re
import sys
import traceback
from dataclasses import dataclass, field

import requests

from pyhugegraph.utils.log import log


@dataclass
class HGraphConfig:
    url: str
    username: str
    password: str
    graph_name: str
    graphspace: str | None = None
    timeout: tuple[float, float] = (0.5, 15.0)
    gs_supported: bool = field(default=False, init=False)
    version: list[int] = field(default_factory=list)

    def __post_init__(self):
        # Add URL prefix compatibility check
        if self.url and not self.url.startswith("http"):
            self.url = f"http://{self.url}"

        if self.graphspace and self.graphspace.strip():
            self.gs_supported = True

        else:
            try:
                response = requests.get(f"{self.url}/versions", timeout=0.5)
                core = response.json()["versions"]["core"]
                log.info(  # pylint: disable=logging-fstring-interpolation
                    f"Retrieved API version information from the server: {core}."
                )

                match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.\d+)?", core)
                if match is None:
                    raise RuntimeError(
                        f"Unable to parse HugeGraph server version from response: {core!r}. "
                        "Please verify the server is compatible with this client."
                    )
                major = int(match.group(1))
                minor = int(match.group(2))
                patch = int(match.group(3)) if match.group(3) else 0
                self.version.extend([major, minor, patch])

                # Version guard: Reject servers older than 1.5.0
                if (major, minor, patch) < (1, 5, 0):
                    raise RuntimeError(
                        f"HugeGraph server version {major}.{minor}.{patch} is not supported. "
                        "Please upgrade to HugeGraph >= 1.5.0 or use an older version of this client (v1.3.x)."
                    )

                # Enable graphspace support for versions > 1.5.0
                # HugeGraph 1.7.0+ moved auth APIs to graphspaces/{graphspace}/auth/...
                if (major, minor, patch) > (1, 5, 0):
                    self.graphspace = "DEFAULT"
                    self.gs_supported = True
                    log.warning("graph space is not set, default value 'DEFAULT' will be used.")

            except Exception as e:  # pylint: disable=broad-exception-caught
                # Version mismatch errors must not be silently swallowed
                if isinstance(e, RuntimeError):
                    raise

                # Handle network/parsing failures gracefully
                try:
                    traceback.print_exception(e)
                    self.gs_supported = False
                except Exception:  # pylint: disable=broad-exception-caught
                    exc_type, exc_value, tb = sys.exc_info()
                    traceback.print_exception(exc_type, exc_value, tb)
                    log.warning("Failed to retrieve API version information from the server, reverting to default v1.")
