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

from hugegraph_mcp import server
from hugegraph_mcp.envelope import envelope_ok


def test_import_graph_data_tool_extract_routes_to_extract(monkeypatch):
    calls = []

    def fake_extract_graph_data(text, schema=None, example_prompt=None):
        calls.append((text, schema, example_prompt))
        return envelope_ok({"graph_data": {"vertices": [], "edges": []}})

    monkeypatch.setattr(server, "extract_graph_data", fake_extract_graph_data)

    result = server.import_graph_data_tool(
        mode="extract",
        text="Alice knows Bob.",
        graph_schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )

    assert result["ok"] is True
    assert "duration_ms" in result["meta"]
    assert calls == [("Alice knows Bob.", {"vertexlabels": ["person"]}, "extract people")]


def test_import_graph_data_tool_ingest_routes_to_mcp_import(monkeypatch):
    calls = []
    graph_data = {"vertices": [], "edges": []}

    def fake_manage_graph_data(
        mode,
        graph_data,
        dry_run=True,
        confirm=False,
        plan_hash=None,
        nonce=None,
        expires_at=None,
        plan_tool_name="manage_graph_data",
    ):
        calls.append(
            (
                mode,
                graph_data,
                dry_run,
                confirm,
                plan_hash,
                nonce,
                expires_at,
                plan_tool_name,
            )
        )
        return envelope_ok({"plan_hash": "0123456789abcdef"})

    monkeypatch.setattr(server, "manage_graph_data", fake_manage_graph_data)

    result = server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash="0123456789abcdef",
        nonce="test_nonce",
        expires_at=9999999999.0,
    )

    assert result["ok"] is True
    assert "duration_ms" in result["meta"]
    assert calls == [
        (
            "import",
            graph_data,
            False,
            True,
            "0123456789abcdef",
            "test_nonce",
            9999999999.0,
            "import_graph_data_tool",
        )
    ]


def test_import_graph_data_tool_wraps_extract_exception(monkeypatch):
    def fake_extract_graph_data(text, schema=None, example_prompt=None):
        raise RuntimeError("extract failed")

    monkeypatch.setattr(server, "extract_graph_data", fake_extract_graph_data)

    result = server.import_graph_data_tool(mode="extract", text="Alice knows Bob.")

    assert result["ok"] is False
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert result["error"]["source"] == "import_graph_data_tool"
    assert "extract failed" in result["error"]["message"]


def test_import_graph_data_tool_aligns_ingest_error_source(monkeypatch):
    def fake_manage_graph_data(**_kwargs):
        from hugegraph_mcp.envelope import ErrorType, envelope_err

        return envelope_err(ErrorType.INVALID_GRAPH_DATA, "bad graph data")

    monkeypatch.setattr(server, "manage_graph_data", fake_manage_graph_data)

    result = server.import_graph_data_tool(
        mode="ingest",
        graph_data={"vertices": [], "edges": []},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "INVALID_GRAPH_DATA"
    assert result["error"]["source"] == "import_graph_data_tool"


def test_import_graph_data_tool_validates_extract_text():
    result = server.import_graph_data_tool(mode="extract")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["source"] == "import_graph_data_tool"
    assert "duration_ms" in result["meta"]
    assert "text is required" in result["error"]["message"]


def test_import_graph_data_tool_validates_ingest_graph_data():
    result = server.import_graph_data_tool(mode="ingest")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["source"] == "import_graph_data_tool"
    assert "duration_ms" in result["meta"]
    assert "graph_data is required" in result["error"]["message"]


def test_import_graph_data_tool_rejects_non_object_graph_data():
    result = server.import_graph_data_tool(mode="ingest", graph_data=[])

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["source"] == "import_graph_data_tool"
    assert result["error"]["details"] == {"received_type": "list"}
    assert "graph_data must be an object" in result["error"]["message"]


def test_import_graph_data_tool_rejects_unknown_mode():
    result = server.import_graph_data_tool(mode="unknown")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["source"] == "import_graph_data_tool"
    assert "duration_ms" in result["meta"]
    assert result["error"]["details"] == {"mode": "unknown"}


def test_import_graph_data_tool_table_returns_feature_disabled():
    result = server.import_graph_data_tool(mode="table")

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert result["error"]["source"] == "import_graph_data_tool"
    assert result["error"]["message"] == "Table import is not supported by the current MCP contract."
    assert "import_graph_data_tool(mode='extract')" in result["error"]["suggestion"]
    assert "import_graph_data_tool(mode='ingest')" in result["error"]["suggestion"]
    assert "V1" not in result["error"]["message"]
    assert "duration_ms" in result["meta"]
