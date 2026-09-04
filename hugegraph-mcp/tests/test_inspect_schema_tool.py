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

from hugegraph_mcp.tools import inspect_schema as inspect_schema_module


def _raw_schema():
    return {
        "propertykeys": [{"name": "name", "data_type": "TEXT"}],
        "vertexlabels": [
            {
                "name": "person",
                "properties": ["name"],
                "primary_keys": ["name"],
                "nullable_keys": [],
            }
        ],
        "edgelabels": [
            {
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "properties": ["since"],
            }
        ],
        "indexlabels": [{"name": "personByName", "base_label": "person"}],
    }


class FakeSchemaManager:
    def getSchema(self):
        return _raw_schema()

    def getRelations(self):
        return ["person--knows-->person"]


def test_inspect_schema_summary(monkeypatch):
    monkeypatch.setattr(
        inspect_schema_module,
        "_schema_manager",
        lambda: FakeSchemaManager(),
    )

    result = inspect_schema_module.inspect_schema(include_raw_schema=True)

    assert result["ok"] is True
    assert result["data"]["summary"]["property_key_count"] == 1
    assert result["data"]["summary"]["vertex_label_count"] == 1
    assert result["data"]["relations"] == ["person--knows-->person"]
    assert result["data"]["raw_schema"] == _raw_schema()


def test_inspect_schema_filter_one_vertex_label(monkeypatch):
    monkeypatch.setattr(
        inspect_schema_module,
        "_schema_manager",
        lambda: FakeSchemaManager(),
    )

    result = inspect_schema_module.inspect_schema(
        filter_kind="vertex_label",
        filter_name="person",
    )

    assert result["ok"] is True
    assert result["data"]["filtered"]["name"] == "person"
    assert result["data"]["filtered"]["primary_keys"] == ["name"]


def test_inspect_schema_rejects_filter_name_without_kind():
    result = inspect_schema_module.inspect_schema(filter_name="person")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"


def test_inspect_schema_not_found(monkeypatch):
    monkeypatch.setattr(
        inspect_schema_module,
        "_schema_manager",
        lambda: FakeSchemaManager(),
    )

    result = inspect_schema_module.inspect_schema(
        filter_kind="edge_label",
        filter_name="missing",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "NOT_FOUND"


def test_inspect_schema_connection_error(monkeypatch):
    class BrokenManager:
        def getSchema(self):
            raise ConnectionError("down")

    monkeypatch.setattr(
        inspect_schema_module,
        "_schema_manager",
        lambda: BrokenManager(),
    )

    result = inspect_schema_module.inspect_schema()

    assert result["ok"] is False
    assert result["error"]["type"] == "CONNECTION_FAILED"
    assert result["error"]["retryable"] is True
