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

import os
import time
from dataclasses import dataclass

import pytest
import requests


@dataclass(frozen=True)
class HugeGraphService:
    url: str
    graph: str
    user: str
    password: str
    graphspace: str | None


def hugegraph_required() -> bool:
    return os.getenv("HUGEGRAPH_REQUIRED", "false").lower() == "true"


def hugegraph_service_from_env() -> HugeGraphService:
    graphspace = os.getenv("HUGEGRAPH_GRAPHSPACE") or None
    return HugeGraphService(
        url=os.getenv("HUGEGRAPH_URL", "http://127.0.0.1:8080"),
        graph=os.getenv("HUGEGRAPH_GRAPH", "hugegraph"),
        user=os.getenv("HUGEGRAPH_USER", "admin"),
        password=os.getenv("HUGEGRAPH_PASSWORD", "admin"),
        graphspace=graphspace,
    )


def wait_for_hugegraph(service: HugeGraphService, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{service.url}/versions", timeout=5)
            response.raise_for_status()
            return
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"HugeGraph is not ready at {service.url}/versions") from last_error


@pytest.fixture(scope="session")
def hugegraph_service() -> HugeGraphService:
    service = hugegraph_service_from_env()
    if hugegraph_required():
        wait_for_hugegraph(service)
        return service

    try:
        wait_for_hugegraph(service, timeout_seconds=5)
    except RuntimeError as exc:
        pytest.skip(f"HugeGraph integration tests not selected with required service: {exc}")
    return service
