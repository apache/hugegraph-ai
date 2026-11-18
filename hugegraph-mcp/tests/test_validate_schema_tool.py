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

import copy
from importlib.util import find_spec

from hugegraph_mcp.artifacts import get_default_artifact_store
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.stores.base import default_stdio_actor
from hugegraph_mcp.tools.validate_schema import validate_schema_structure


def test_validate_schema_structure_preserves_input_and_reports_available_scope():
    schema = {
        "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
        "vertexlabels": [{"name": "person", "properties": ["name"], "primary_keys": ["name"]}],
        "edgelabels": [],
        "indexlabels": [],
    }
    snapshot = copy.deepcopy(schema)
    res = validate_schema_structure(schema=schema)

    assert res["ok"] is True
    assert res["data"]["valid"] is True
    assert res["data"]["issues"] == []
    expected_scope = "schema_structure" if find_spec("hugegraph_llm_sdk") is not None else "limited_fallback"
    assert res["data"]["validation_scope"] == expected_scope
    assert schema == snapshot


def test_validate_schema_structure_reports_issues_with_ok_true():
    bad_schema = {
        "propertykeys": [],
        "vertexlabels": [{"name": "person", "properties": ["missing_prop"]}],
    }
    res = validate_schema_structure(schema=bad_schema)

    assert res["ok"] is True
    assert res["data"]["valid"] is False
    assert len(res["data"]["issues"]) >= 1


def test_validate_schema_structure_from_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path))
    cfg = MCPConfig.from_env()
    actor = default_stdio_actor()
    manifest = get_default_artifact_store(cfg).put(
        '{"propertykeys":[],"vertexlabels":[{"name":"person"}],"edgelabels":[]}',
        owner_key=actor.principal_key,
        tenant=actor.tenant,
        target_graph={"graph": "hugegraph"},
        kind="schema",
    )
    res = validate_schema_structure(artifact_id=manifest.artifact_id)
    assert res["ok"] is True
    assert res["data"]["valid"] is True
