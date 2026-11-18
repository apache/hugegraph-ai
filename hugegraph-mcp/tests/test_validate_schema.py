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

import importlib
import sys

import pytest

from hugegraph_mcp.tools.validate_schema import validate_schema_structure


def _hide_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "hugegraph_llm_sdk", None)
    monkeypatch.setitem(sys.modules, "hugegraph_llm_sdk.schema", None)


@pytest.mark.parametrize("use_fallback", [True, False])
def test_validate_schema_required_collections_and_optional_propertykeys(monkeypatch, use_fallback):
    if use_fallback:
        _hide_sdk(monkeypatch)
    else:
        try:
            importlib.import_module("hugegraph_llm_sdk.schema")
        except ImportError:
            pytest.skip("hugegraph-llm-sdk is not installed in this environment")

    # Missing required collections (vertexlabels, edgelabels) must be rejected.
    empty_res = validate_schema_structure(schema={})
    assert empty_res["ok"] is True
    assert empty_res["data"]["valid"] is False
    issue_paths = {issue["path"] for issue in empty_res["data"]["issues"]}
    assert {"vertexlabels", "edgelabels"}.issubset(issue_paths)

    # Omitting optional propertykeys is valid when labels declare properties.
    without_pks = validate_schema_structure(
        schema={
            "vertexlabels": [{"name": "person", "properties": ["name"]}],
            "edgelabels": [],
        }
    )
    assert without_pks["ok"] is True
    assert without_pks["data"]["valid"] is True
    assert without_pks["data"]["issues"] == []

    # When propertykeys IS provided, undeclared label properties must be rejected.
    with_pks_mismatch = validate_schema_structure(
        schema={
            "propertykeys": [{"name": "age"}],
            "vertexlabels": [{"name": "person", "properties": ["name"]}],
            "edgelabels": [],
        }
    )
    assert with_pks_mismatch["ok"] is True
    assert with_pks_mismatch["data"]["valid"] is False
    assert any("properties" in issue["path"] for issue in with_pks_mismatch["data"]["issues"])

    # Edge labels require non-empty valid source_label and target_label.
    bad_edge = validate_schema_structure(
        schema={
            "vertexlabels": [{"name": "person"}],
            "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "missing"}],
        }
    )
    assert bad_edge["ok"] is True
    assert bad_edge["data"]["valid"] is False
    assert any(issue["path"] == "edgelabels[0].target_label" for issue in bad_edge["data"]["issues"])


def test_validate_schema_fallback_is_clearly_labelled(monkeypatch):
    _hide_sdk(monkeypatch)
    res = validate_schema_structure(schema={"vertexlabels": [], "edgelabels": []})
    assert res["ok"] is True
    assert res["data"]["valid"] is True
    assert res["data"]["validation_scope"] == "limited_fallback"
    assert res["data"]["sdk_available"] is False
    assert res["warnings"]
    assert "hugegraph-llm-sdk" in res["warnings"][0]
