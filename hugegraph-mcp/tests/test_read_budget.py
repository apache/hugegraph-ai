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

from contextlib import contextmanager

import pytest

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.read_budget import ReadBudgetExceededError, read_budget_from_config
from hugegraph_mcp.tools import inspect_schema, query_graph_data


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    @contextmanager
    def request_guard(self, *, max_response_bytes: int, deadline_seconds: float, retries: bool = False):
        self.calls.append(
            {
                "max_response_bytes": max_response_bytes,
                "deadline_seconds": deadline_seconds,
                "retries": retries,
            }
        )
        yield


def test_read_budget_tracks_remaining_bytes_and_deadline():
    cfg = MCPConfig(read_timeout_seconds=10.0, max_result_bytes=1024, max_result_items=50)
    budget = read_budget_from_config(cfg, deadline_seconds=5.0, max_response_bytes=512)

    assert budget.deadline_seconds == 5.0
    assert budget.max_response_bytes == 512
    assert budget.max_items == 50

    budget.record_bytes(400)
    assert budget.remaining_bytes() == 112
    budget.record_bytes(112)
    assert budget.remaining_bytes() == 0

    with pytest.raises(ReadBudgetExceededError) as exc_info:
        budget.ensure_available()
    assert exc_info.value.reason_code == "READ_BYTE_BUDGET_EXCEEDED"


def test_read_budget_shares_guard_across_multiple_calls():
    session = _RecordingSession()
    target = type("_Manager", (), {"session": session})()
    budget = read_budget_from_config(MCPConfig(read_timeout_seconds=10.0, max_result_bytes=2048))

    with budget.request_guard(target):
        budget.record_bytes(500)
    with budget.request_guard(target):
        pass

    assert len(session.calls) == 2
    assert session.calls[0]["max_response_bytes"] == 2048
    assert session.calls[1]["max_response_bytes"] == 1548
    assert session.calls[1]["deadline_seconds"] <= session.calls[0]["deadline_seconds"]


def test_query_graph_data_attaches_request_guard(monkeypatch):
    session = _RecordingSession()

    class _FakeManager:
        def __init__(self) -> None:
            self.session = session

        def get_vertex_by_id(self, vertex_id):
            return {"id": vertex_id, "label": "person", "properties": {"name": "marko"}}

    monkeypatch.setattr(query_graph_data, "_graph_manager", lambda: _FakeManager())
    result = query_graph_data.query_graph_data(target="vertex", operation="get_by_id", id="1:marko")

    assert result["ok"] is True
    assert len(session.calls) == 1
    assert session.calls[0]["retries"] is False


def test_inspect_schema_shares_request_guard_between_schema_and_relations(monkeypatch):
    session = _RecordingSession()

    class _FakeSchemaManager:
        def __init__(self) -> None:
            self.session = session

        def get_schema(self):
            return {"propertykeys": [], "vertexlabels": [], "edgelabels": [], "indexlabels": []}

        def getRelations(self):
            return []

    monkeypatch.setattr(inspect_schema, "_schema_manager", lambda: _FakeSchemaManager())
    result = inspect_schema.inspect_schema(include_relations=True)

    assert result["ok"] is True
    assert len(session.calls) == 2
    assert session.calls[1]["deadline_seconds"] <= session.calls[0]["deadline_seconds"]
