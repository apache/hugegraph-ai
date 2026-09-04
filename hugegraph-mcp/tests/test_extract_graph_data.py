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

import json
from unittest.mock import Mock

from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.tools import extract_graph_data as extract_graph_data_module


def test_extract_graph_data_basic(monkeypatch):
    graph_data = {
        "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
        "edges": [
            {
                "label": "knows",
                "source_label": "person",
                "target_label": "person",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
            }
        ],
    }
    post = Mock(return_value=envelope_ok({"ok": True, "data": json.dumps(graph_data)}))
    monkeypatch.setattr(extract_graph_data_module, "post", post)

    result = extract_graph_data_module.extract_graph_data(
        "Alice knows Bob.",
        schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )

    assert result["ok"] is True
    gd = result["data"]["graph_data"]
    assert gd["vertices"] == graph_data["vertices"]
    assert gd["edges"] == graph_data["edges"]
    assert "schema_ref" in gd
    assert gd["schema_ref"]["graph"] is not None
    assert gd["warnings"] == []
    assert result["data"]["schema_warnings"] == []
    assert "raw_summary" in result["data"]
    post.assert_called_once_with(
        "/graph-extract",
        json={
            "text": "Alice knows Bob.",
            "schema": json.dumps({"vertexlabels": ["person"]}, sort_keys=True),
            "example_prompt": "extract people",
            "language": "zh",
        },
    )


def test_extract_graph_data_uses_graph_schema_by_default(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "DEFAULT/hugegraph")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "true")
    live_schema = {
        "schema": {
            "vertexlabels": [{"name": "person", "properties": ["name"]}],
            "edgelabels": [],
            "propertykeys": [{"name": "name", "data_type": "TEXT"}],
        }
    }
    monkeypatch.setattr(extract_graph_data_module, "fetch_live_schema_or_none", lambda: live_schema)
    graph_data = {"vertices": [], "edges": []}
    post = Mock(return_value=envelope_ok({"ok": True, "data": json.dumps(graph_data)}))
    monkeypatch.setattr(extract_graph_data_module, "post", post)

    result = extract_graph_data_module.extract_graph_data("Alice knows Bob.")

    assert result["ok"] is True
    gd = result["data"]["graph_data"]
    assert gd["schema_ref"]["schema_source"] == "live"
    assert len(gd["schema_ref"]["fingerprint"]) == 64
    post.assert_called_once_with(
        "/graph-extract",
        json={
            "text": "Alice knows Bob.",
            "schema": json.dumps(live_schema["schema"], sort_keys=True),
            "example_prompt": extract_graph_data_module.DEFAULT_GRAPH_EXTRACT_PROMPT_ZH,
            "language": "zh",
        },
    )


def test_extract_graph_data_default_schema_failure_is_structured(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "true")
    monkeypatch.setattr(extract_graph_data_module, "fetch_live_schema_or_none", lambda: None)

    result = extract_graph_data_module.extract_graph_data("Alice knows Bob.")

    assert result["ok"] is False
    assert result["error"]["type"] == ErrorType.CONNECTION_FAILED.value


def test_extract_graph_data_preserves_explicit_string_schema_and_prompt(monkeypatch):
    graph_data = {"vertices": [], "edges": []}
    post = Mock(return_value=envelope_ok({"ok": True, "data": json.dumps(graph_data)}))
    monkeypatch.setattr(extract_graph_data_module, "post", post)

    result = extract_graph_data_module.extract_graph_data(
        "Alice knows Bob.",
        schema="custom_graph",
        example_prompt="custom prompt",
    )

    assert result["ok"] is True
    post.assert_called_once_with(
        "/graph-extract",
        json={
            "text": "Alice knows Bob.",
            "schema": "custom_graph",
            "example_prompt": "custom prompt",
            "language": "zh",
        },
    )


def test_extract_graph_data_ai_unavailable(monkeypatch):
    fetch_schema = Mock(return_value=None)
    monkeypatch.setattr(extract_graph_data_module, "fetch_live_schema_or_none", fetch_schema)
    ai_error = envelope_err(
        ErrorType.HUGEGRAPH_AI_UNAVAILABLE,
        "HugeGraph-AI is unavailable",
        retryable=True,
    )
    post = Mock(return_value=ai_error)
    monkeypatch.setattr(extract_graph_data_module, "post", post)

    result = extract_graph_data_module.extract_graph_data("Alice knows Bob.")

    assert result == ai_error
    fetch_schema.assert_not_called()


def test_extract_graph_data_does_not_return_nonstandard_inner_error(monkeypatch):
    inner_error = {
        "ok": False,
        "error": {"type": "FLOW_EXECUTION_FAILED", "message": "flow failed"},
    }
    monkeypatch.setattr(
        extract_graph_data_module,
        "post",
        Mock(return_value=envelope_ok(inner_error)),
    )

    result = extract_graph_data_module.extract_graph_data(
        "Alice knows Bob.",
        schema={"vertexlabels": ["person"]},
    )

    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["type"] == ErrorType.INVALID_GRAPH_DATA.value
    assert set(result) == {
        "ok",
        "data",
        "error",
        "warnings",
        "next_actions",
        "meta",
    }
