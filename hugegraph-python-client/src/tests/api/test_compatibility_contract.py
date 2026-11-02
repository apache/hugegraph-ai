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
from types import SimpleNamespace

import pytest
import requests
from pyhugegraph.api.rest import RestManager
from pyhugegraph.structure.rank_data import NeighborRankParameters, NeighborRankStep
from pyhugegraph.utils.huge_requests import HGraphSession

pytestmark = pytest.mark.contract


class RecordingHTTP(requests.Session):
    def __init__(self, responses=()):
        super().__init__()
        self.responses = list(responses)
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response._content = json.dumps(self.responses.pop(0) if self.responses else {}).encode()
        response.headers["Content-Type"] = "application/json"
        return response


def transport(responses=()):
    http = RecordingHTTP(responses)
    cfg = SimpleNamespace(
        url="https://example.test/proxy",
        graph_name="g",
        graphspace="DEFAULT",
        gs_supported=True,
        username="admin",
        password="private-password",
        timeout=(0.5, 15),
    )
    return HGraphSession(cfg, session=http), http


def test_optional_authorization_header_inherits_session_token():
    session, http = transport([{}, {}])
    session.use_token("session-token")
    login = RestManager(session).login

    login.verify_token()
    assert http.calls[0][0].headers["Authorization"] == "Bearer session-token"

    login.logout(authorization="Bearer explicit-token")
    assert http.calls[1][0].headers["Authorization"] == "Bearer explicit-token"


def test_neighbor_rank_requires_new_parameters_by_keyword():
    with pytest.raises(TypeError):
        NeighborRankParameters("source", "legacy-label")

    parameters = NeighborRankParameters(
        "source",
        alpha=0.8,
        capacity=1000,
        steps=[NeighborRankStep(labels=["knows"])],
    )
    assert json.loads(parameters.dumps()) == {
        "source": "source",
        "alpha": 0.8,
        "capacity": 1000,
        "steps": [
            {
                "direction": "BOTH",
                "labels": ["knows"],
                "max_degree": 10000,
                "top": 100,
                "skip_degree": 0,
            }
        ],
    }
