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

"""Connection configuration and a single server-profile probe."""

import re
from dataclasses import dataclass, field

import requests


@dataclass
class HGraphConfig:
    url: str
    username: str
    password: str = field(repr=False)
    graph_name: str
    graphspace: str | None = None
    timeout: tuple[float, float] = (0.5, 15.0)
    gs_supported: bool = field(default=False, init=False)
    version: list[int] = field(default_factory=list)

    def __post_init__(self):
        if not self.url.startswith(("http://", "https://")):
            self.url = f"http://{self.url}"
        self.url = self.url.rstrip("/")
        if self.graphspace and self.graphspace.strip():
            # An explicit graphspace selects the graphspace profile without probing.
            self.gs_supported = True
            return
        try:
            response = requests.get(f"{self.url}/versions", timeout=self.timeout)
            response.raise_for_status()
            core = response.json()["versions"]["core"]
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(
                "Unable to determine HugeGraph server version; check the connection or explicitly configure graphspace"
            ) from exc
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(core))
        if match is None:
            raise RuntimeError(f"Unable to parse HugeGraph server version: {core!r}")
        self.version = [int(value or 0) for value in match.groups()]
        if tuple(self.version) < (1, 5, 0):
            raise RuntimeError("HugeGraph >= 1.5.0 is required; use client v1.3.x for older servers")
        if tuple(self.version) >= (1, 7, 0):
            self.graphspace = "DEFAULT"
            self.gs_supported = True
