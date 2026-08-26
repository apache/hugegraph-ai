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

import re
from unittest.mock import Mock

from hugegraph_mcp.tools import manage_schema as manage_schema_module
from hugegraph_mcp.tools.manage_schema import manage_schema


def _empty_schema():
    return {
        "schema": {
            "propertykeys": [],
            "vertexlabels": [],
            "edgelabels": [],
            "indexlabels": [],
        },
        "simple_schema": {},
        "readonly": False,
    }


def _schema(
    *,
    propertykeys=None,
    vertexlabels=None,
    edgelabels=None,
    indexlabels=None,
):
    return {
        "schema": {
            "propertykeys": propertykeys or [],
            "vertexlabels": vertexlabels or [],
            "edgelabels": edgelabels or [],
            "indexlabels": indexlabels or [],
        },
        "simple_schema": {},
        "readonly": False,
    }


def _property_key(name="age", data_type="INT"):
    return {"type": "create_property_key", "name": name, "data_type": data_type}


class RecordingPropertyBuilder:
    def __init__(self, name, state=None):
        self.name = name
        self.state = state
        self.data_type = None
        self.cardinality = None
        self.aggregate_type = None

    def add_parameter(self, key, value):
        setattr(self, key, value)

    def asInt(self):
        self.data_type = "INT"
        return self

    def asBool(self):
        self.data_type = "BOOLEAN"
        return self

    def valueSingle(self):
        self.cardinality = "SINGLE"
        return self

    def valueSet(self):
        self.cardinality = "SET"
        return self

    def valueList(self):
        self.cardinality = "LIST"
        return self

    def calcSum(self):
        self.aggregate_type = "SUM"
        return self

    def create(self):
        if self.state is not None:
            property_key = {
                "name": self.name,
                "data_type": self.data_type,
                "cardinality": self.cardinality,
            }
            if self.aggregate_type is not None:
                property_key["aggregate_type"] = self.aggregate_type
            self.state["schema"]["propertykeys"].append(property_key)
        return "ok"


class RecordingPropertyManager:
    def __init__(self, state=None):
        self.state = state
        self.builders = []

    def propertyKey(self, name):
        builder = RecordingPropertyBuilder(name, self.state)
        self.builders.append(builder)
        return builder


def _vertex_label(
    name="person",
    properties=None,
    primary_keys=None,
    id_strategy=None,
    nullable_keys=None,
):
    operation = {"type": "create_vertex_label", "name": name}
    if properties is not None:
        operation["properties"] = properties
    if primary_keys is not None:
        operation["primary_keys"] = primary_keys
    if id_strategy is not None:
        operation["id_strategy"] = id_strategy
    if nullable_keys is not None:
        operation["nullable_keys"] = nullable_keys
    return operation


def _edge_label(
    name="knows",
    source_label="person",
    target_label="person",
    properties=None,
    nullable_keys=None,
    sort_keys=None,
    frequency=None,
):
    operation = {
        "type": "create_edge_label",
        "name": name,
        "source_label": source_label,
        "target_label": target_label,
    }
    if properties is not None:
        operation["properties"] = properties
    if nullable_keys is not None:
        operation["nullable_keys"] = nullable_keys
    if sort_keys is not None:
        operation["sort_keys"] = sort_keys
    if frequency is not None:
        operation["frequency"] = frequency
    return operation


def _index_label(
    name="personByAge", base_type="VERTEX", base_label="person", fields=None
):
    operation = {
        "type": "create_index_label",
        "name": name,
        "base_type": base_type,
        "base_label": base_label,
    }
    if fields is not None:
        operation["fields"] = fields
    return operation


def _live_pk(name):
    return {"name": name, "data_type": "TEXT"}


def _live_vertex(name, properties=None):
    return {"name": name, "properties": properties or []}


def _live_edge(name, source_label="person", target_label="software"):
    return {
        "name": name,
        "source_label": source_label,
        "target_label": target_label,
    }


def _assert_dry_run_invalid(result):
    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "plan_hash" not in result["data"]


def test_manage_schema_design():
    result = manage_schema(
        mode="design",
        operations=[
            {
                "thought": "Need a graph for users",
                "thought_number": 2,
                "total_thoughts": 5,
                "next_thought_needed": True,
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["thought_number"] == 2
    assert result["data"]["total_thoughts"] == 5
    assert result["data"]["next_thought_needed"] is True


def test_manage_schema_design_does_not_fetch_live_schema(monkeypatch):
    def raise_connection_error():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", raise_connection_error
    )

    result = manage_schema(
        mode="design",
        operations=[
            {
                "thought": "Need a graph for users",
                "thought_number": 1,
                "total_thoughts": 4,
                "next_thought_needed": True,
            }
        ],
    )

    assert result["ok"] is True


def test_manage_schema_validate_valid(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(mode="validate", operations=[_property_key()])

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_manage_schema_validate_returns_connection_failed_when_schema_unreachable(
    monkeypatch,
):
    def raise_connection_error():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", raise_connection_error
    )

    result = manage_schema(mode="validate", operations=[_property_key()])

    assert result["ok"] is False
    assert result["error"]["type"] == "CONNECTION_FAILED"
    assert result["error"]["retryable"] is True
    assert result["error"]["details"]["stage"] == "schema_fetch"


def test_manage_schema_validate_invalid_missing_name(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[{"type": "create_property_key", "data_type": "TEXT"}],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert result["data"]["errors"][0]["operation_index"] == 0
    assert "missing required field: name" in result["data"]["errors"][0]["reason"]


def test_manage_schema_validate_rejects_delete(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[{"type": "delete_vertex_label", "name": "person"}],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "unsupported delete/drop type" in result["data"]["errors"][0]["reason"]


def test_manage_schema_validate_rejects_unknown_property_key(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            {
                "type": "create_vertex_label",
                "name": "person",
                "properties": ["name", "age"],
                "primary_keys": ["name"],
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 0
    assert "undefined property key" in error["reason"]
    assert "age" in error["reason"]


def test_manage_schema_validate_rejects_unknown_edge_endpoint(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            {
                "type": "create_edge_label",
                "name": "created",
                "source_label": "person",
                "target_label": "software",
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 0
    assert "target_label references undefined vertex label: software" == error["reason"]


def test_manage_schema_validate_rejects_duplicate_vertex_label(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[{"type": "create_vertex_label", "name": "person"}],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 0
    assert error["reason"] == "vertex label already exists: person"


def test_manage_schema_validate_rejects_primary_key_label_without_primary_keys(
    monkeypatch,
):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[_vertex_label("person", properties=["name"])],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert result["data"]["errors"][0]["reason"] == (
        "primary_keys is required when id_strategy is PRIMARY_KEY"
    )


def test_manage_schema_validate_rejects_primary_key_not_in_properties(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name"), _live_pk("age")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[_vertex_label("person", properties=["name"], primary_keys=["age"])],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert result["data"]["errors"][0]["reason"] == (
        "primary_keys must be included in properties: age"
    )


def test_manage_schema_validate_rejects_unknown_primary_key_property(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _vertex_label("person", properties=["name", "age"], primary_keys=["age"])
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert any(
        error["reason"] == "primary_keys references undefined property key(s): age"
        for error in result["data"]["errors"]
    )


def test_manage_schema_validate_rejects_non_string_primary_key(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[_vertex_label("person", properties=["name"], primary_keys=[1])],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert result["data"]["errors"][0]["reason"] == (
        "primary_keys must contain non-empty string names"
    )


def test_manage_schema_validate_rejects_duplicate_primary_key(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _vertex_label("person", properties=["name"], primary_keys=["name", "name"])
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert result["data"]["errors"][0]["reason"] == (
        "primary_keys contains duplicate name(s): name"
    )


def test_manage_schema_validate_accepts_automatic_id_without_primary_keys(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _vertex_label("person", properties=["name"], id_strategy="AUTOMATIC")
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_manage_schema_validate_accepts_semantically_valid_operations(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(
            propertykeys=[_live_pk("name")],
            vertexlabels=[_live_vertex("person")],
            edgelabels=[_live_edge("created")],
        ),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            {
                "type": "create_index_label",
                "name": "personByName",
                "base_type": "VERTEX",
                "base_label": "person",
                "fields": ["name"],
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_manage_schema_dry_run_returns_connection_failed_when_schema_unreachable(
    monkeypatch,
):
    def raise_connection_error():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", raise_connection_error
    )

    result = manage_schema(mode="dry_run", operations=[_property_key()])

    assert result["ok"] is False
    assert result["error"]["type"] == "CONNECTION_FAILED"
    assert result["error"]["retryable"] is True
    assert result["error"]["details"]["stage"] == "schema_fetch"


def test_manage_schema_rejects_unknown_mode_as_validation_error():
    result = manage_schema(mode="typo", operations=[])

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "Unsupported manage_schema mode" in result["error"]["message"]


def test_same_batch_pk_to_vertex_label(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _property_key("age"),
            _vertex_label("person", properties=["age"], primary_keys=["age"]),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_vertex_to_edge_label(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _property_key("name"),
            _vertex_label("person", properties=["name"], primary_keys=["name"]),
            _vertex_label("software", properties=["name"], primary_keys=["name"]),
            _edge_label("created", source_label="person", target_label="software"),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_later_vertex_label_is_not_available_to_earlier_edge(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            _property_key("name"),
            _vertex_label("person", properties=["name"], primary_keys=["name"]),
            _edge_label("created", source_label="person", target_label="software"),
            _vertex_label("software", properties=["name"], primary_keys=["name"]),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "plan_hash" not in result["data"]
    assert result["data"]["errors"][0]["reason"] == (
        "target_label references undefined vertex label: software"
    )


def test_same_batch_label_to_index(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _property_key("name"),
            _vertex_label("person", properties=["name"], primary_keys=["name"]),
            _index_label("personByName", base_label="person", fields=["name"]),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_full_chain(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _property_key("name"),
            _property_key("weight"),
            _vertex_label("person", properties=["name"], primary_keys=["name"]),
            _vertex_label("software", properties=["name"], primary_keys=["name"]),
            _edge_label(
                "created",
                source_label="person",
                target_label="software",
                properties=["weight"],
            ),
            _index_label(
                "createdByWeight",
                base_type="EDGE",
                base_label="created",
                fields=["weight"],
            ),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_unknown_reference(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[_vertex_label("person", properties=["missing"])],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 0
    assert "undefined property key" in error["reason"]
    assert "missing" in error["reason"]


def test_same_batch_duplicate_definition(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[_property_key("age"), _property_key("age")],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 1
    assert error["reason"] == (
        "duplicate create_property_key name age within the same batch"
    )


def test_same_batch_edge_missing_endpoint(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _property_key("name"),
            _vertex_label("person", properties=["name"], primary_keys=["name"]),
            _edge_label("created", source_label="person", target_label="software"),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 2
    assert error["reason"] == "target_label references undefined vertex label: software"


def test_manage_schema_dry_run(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(mode="dry_run", operations=[_property_key()])

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", result["data"]["plan_hash"])
    assert "mutation_summary" in result["data"]
    assert isinstance(result["data"]["warnings"], list)


def test_manage_schema_readonly_preview_does_not_issue_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )
    issue = Mock()
    monkeypatch.setattr(manage_schema_module, "issue_plan", issue)

    result = manage_schema(mode="dry_run", operations=[_property_key()])

    assert result["ok"] is True
    assert result["data"]["confirmable"] is False
    assert result["data"]["readonly_preview_only"] is True
    issue.assert_not_called()


def test_manage_schema_dry_run_invalid_schema_has_no_plan_hash(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_vertex_label",
                "name": "person",
                "properties": ["age"],
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "plan_hash" not in result["data"]


def test_dry_run_rejects_invalid_id_strategy_enum(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            _vertex_label(
                "person",
                properties=["name"],
                primary_keys=["name"],
                id_strategy="FOO",
            )
        ],
    )

    _assert_dry_run_invalid(result)
    assert result["data"]["errors"][0]["reason"] == "unsupported id_strategy: 'FOO'"


def test_dry_run_rejects_id_strategy_with_trailing_whitespace(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            _vertex_label(
                "person",
                properties=["name"],
                primary_keys=["name"],
                id_strategy="PRIMARY_KEY ",
            )
        ],
    )

    _assert_dry_run_invalid(result)
    assert "unsupported id_strategy" in result["data"]["errors"][0]["reason"]


def test_dry_run_rejects_non_string_id_strategy(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            _vertex_label(
                "person",
                properties=["name"],
                primary_keys=["name"],
                id_strategy=123,
            )
        ],
    )

    _assert_dry_run_invalid(result)
    assert result["data"]["errors"][0]["reason"] == (
        "id_strategy must be a string, got int"
    )


def test_dry_run_accepts_all_valid_id_strategies(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    for id_strategy in manage_schema_module.VERTEX_LABEL_ID_STRATEGIES:
        operation = _vertex_label(
            f"person_{id_strategy.lower()}",
            properties=["name"],
            id_strategy=id_strategy,
        )
        if id_strategy == "PRIMARY_KEY":
            operation["primary_keys"] = ["name"]
        result = manage_schema(
            mode="dry_run",
            operations=[_property_key("name"), operation],
            nonce=f"id-{id_strategy}",
        )

        assert result["ok"] is True
        assert result["data"]["valid"] is True
        assert "plan_hash" in result["data"]


def test_dry_run_rejects_invalid_data_type_enum(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {"type": "create_property_key", "name": "age", "data_type": "FOOBAR"}
        ],
    )

    _assert_dry_run_invalid(result)
    assert result["data"]["errors"][0]["reason"] == "unsupported data_type: 'FOOBAR'"


def test_dry_run_rejects_non_string_data_type(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[{"type": "create_property_key", "name": "age", "data_type": 123}],
    )

    _assert_dry_run_invalid(result)
    assert (
        result["data"]["errors"][0]["reason"] == "data_type must be a string, got int"
    )


def test_dry_run_rejects_invalid_cardinality_enum(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_property_key",
                "name": "tags",
                "data_type": "TEXT",
                "cardinality": "MANY",
            }
        ],
    )

    _assert_dry_run_invalid(result)
    assert result["data"]["errors"][0]["reason"] == "unsupported cardinality: 'MANY'"


def test_dry_run_rejects_invalid_aggregate_type_when_provided(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    invalid = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_property_key",
                "name": "score",
                "data_type": "INT",
                "aggregate_type": "AVG",
            }
        ],
    )
    valid = manage_schema(
        mode="dry_run",
        operations=[
            {"type": "create_property_key", "name": "score", "data_type": "INT"}
        ],
    )

    _assert_dry_run_invalid(invalid)
    assert invalid["data"]["errors"][0]["reason"] == (
        "unsupported aggregate_type: 'AVG'"
    )
    assert valid["ok"] is True
    assert valid["data"]["valid"] is True
    assert "plan_hash" in valid["data"]


def test_dry_run_accepts_hugegraph_1_7_aggregate_types(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    for aggregate_type in ("NONE", "OLD", "SUM", "MIN", "MAX", "SET", "LIST"):
        cardinality = aggregate_type if aggregate_type in {"SET", "LIST"} else "SINGLE"
        result = manage_schema(
            mode="dry_run",
            operations=[
                {
                    "type": "create_property_key",
                    "name": f"score_{aggregate_type.lower()}",
                    "data_type": "INT",
                    "cardinality": cardinality,
                    "aggregate_type": aggregate_type,
                }
            ],
            nonce=f"aggregate-{aggregate_type}",
        )

        assert result["ok"] is True
        assert result["data"]["valid"] is True
        assert "plan_hash" in result["data"]


def test_dry_run_rejects_invalid_aggregate_cardinality_combination(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_property_key",
                "name": "tags",
                "data_type": "TEXT",
                "cardinality": "SINGLE",
                "aggregate_type": "SET",
            }
        ],
    )

    _assert_dry_run_invalid(result)
    assert (
        result["data"]["errors"][0]["reason"]
        == "aggregate_type 'SET' is not allowed with cardinality 'SINGLE'"
    )


def test_dry_run_accepts_set_aggregate_with_set_cardinality(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_property_key",
                "name": "tags",
                "data_type": "TEXT",
                "cardinality": "SET",
                "aggregate_type": "SET",
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True


def test_dry_run_rejects_invalid_edge_frequency_when_provided(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    invalid = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_edge_label",
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "frequency": "ONCE",
            }
        ],
    )
    valid = manage_schema(
        mode="dry_run",
        operations=[_edge_label("knows", source_label="person", target_label="person")],
    )

    _assert_dry_run_invalid(invalid)
    assert invalid["data"]["errors"][0]["reason"] == "unsupported frequency: 'ONCE'"
    assert valid["ok"] is True
    assert valid["data"]["valid"] is True
    assert "plan_hash" in valid["data"]


def test_dry_run_rejects_unsupported_parent_sub_edge_fields(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    for field, value in (
        ("parent_label", "parent_edge"),
        ("parentLabel", "parent_edge"),
        ("edgelabel_type", "SUB"),
        ("edgeLabelType", "SUB"),
    ):
        operation = _edge_label("knows", source_label="person", target_label="person")
        operation[field] = value

        result = manage_schema(mode="dry_run", operations=[operation])

        _assert_dry_run_invalid(result)
        assert result["data"]["errors"][0]["reason"] == (
            f"unsupported parent/sub edge label field(s): {field}"
        )


def test_dry_run_rejects_nullable_and_sort_key_contract_violations(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(
            propertykeys=[
                _live_pk("name"),
                _live_pk("nickname"),
                _live_pk("rank"),
                _live_pk("since"),
            ],
            vertexlabels=[_live_vertex("person")],
        ),
    )

    cases = [
        (
            _vertex_label(
                "person_v",
                properties=["name"],
                primary_keys=["name"],
                nullable_keys="nickname",
            ),
            "nullable_keys must be a list",
        ),
        (
            _vertex_label(
                "person_v",
                properties=["name"],
                primary_keys=["name"],
                nullable_keys=[],
            ),
            "nullable_keys must be a non-empty list",
        ),
        (
            _vertex_label(
                "person_v",
                properties=["name"],
                primary_keys=["name"],
                nullable_keys=[""],
            ),
            "nullable_keys must contain non-empty string names",
        ),
        (
            _vertex_label(
                "person_v",
                properties=["name", "nickname"],
                primary_keys=["name"],
                nullable_keys=["nickname", "nickname"],
            ),
            "nullable_keys contains duplicate name(s): nickname",
        ),
        (
            _vertex_label(
                "person_v",
                properties=["name"],
                primary_keys=["name"],
                nullable_keys=["nickname"],
            ),
            "nullable_keys must be included in properties: nickname",
        ),
        (
            _edge_label(
                "knows",
                source_label="person",
                target_label="person",
                properties=["since"],
                sort_keys=["rank"],
            ),
            "sort_keys must be included in properties: rank",
        ),
    ]

    for operation, reason in cases:
        result = manage_schema(mode="dry_run", operations=[operation])

        _assert_dry_run_invalid(result)
        assert any(error["reason"] == reason for error in result["data"]["errors"])


def test_dry_run_accepts_nullable_and_sort_keys_subset_of_properties(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(
            propertykeys=[_live_pk("name"), _live_pk("nickname"), _live_pk("since")],
            vertexlabels=[_live_vertex("person")],
        ),
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            _vertex_label(
                "person_v",
                properties=["name", "nickname"],
                primary_keys=["name"],
                nullable_keys=["nickname"],
            ),
            _edge_label(
                "knows",
                source_label="person",
                target_label="person",
                properties=["since"],
                sort_keys=["since"],
                frequency="MULTIPLE",
            ),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert "plan_hash" in result["data"]


def test_dry_run_rejects_non_string_name(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(
            propertykeys=[_live_pk("name")],
            vertexlabels=[_live_vertex("person")],
            edgelabels=[
                _live_edge("knows", source_label="person", target_label="person")
            ],
        ),
    )
    operations = [
        {"type": "create_property_key", "name": 123, "data_type": "TEXT"},
        {"type": "create_vertex_label", "name": 123},
        {
            "type": "create_edge_label",
            "name": 123,
            "source_label": "person",
            "target_label": "person",
        },
        {
            "type": "create_index_label",
            "name": 123,
            "base_type": "VERTEX",
            "base_label": "person",
        },
    ]

    for operation in operations:
        result = manage_schema(mode="dry_run", operations=[operation])

        _assert_dry_run_invalid(result)
        assert result["data"]["errors"][0]["reason"].startswith(
            "name must be a non-empty string"
        )


def test_dry_run_rejects_blank_name(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {"type": "create_property_key", "name": "   ", "data_type": "TEXT"}
        ],
    )

    _assert_dry_run_invalid(result)
    assert result["data"]["errors"][0]["reason"] == (
        "name must be a non-empty string, got '   '"
    )


def test_dry_run_rejects_non_string_source_or_target_label(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    invalid_source = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_edge_label",
                "name": "knows",
                "source_label": 123,
                "target_label": "person",
            }
        ],
    )
    blank_target = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_edge_label",
                "name": "knows",
                "source_label": "person",
                "target_label": "   ",
            }
        ],
    )

    _assert_dry_run_invalid(invalid_source)
    _assert_dry_run_invalid(blank_target)
    assert invalid_source["data"]["errors"][0]["reason"].startswith(
        "source_label must be a non-empty string"
    )
    assert blank_target["data"]["errors"][0]["reason"].startswith(
        "target_label must be a non-empty string"
    )


def test_dry_run_rejects_non_string_base_label(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_index_label",
                "name": "personByName",
                "base_type": "VERTEX",
                "base_label": 123,
            }
        ],
    )

    _assert_dry_run_invalid(result)
    assert result["data"]["errors"][0]["reason"] == (
        "base_label must be a non-empty string, got 123"
    )


def test_dry_run_accepts_valid_property_key_enums(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    for data_type in manage_schema_module.PROPERTY_KEY_DATA_TYPES:
        result = manage_schema(
            mode="dry_run",
            operations=[_property_key(f"pk_{data_type.lower()}", data_type)],
            nonce=f"data-type-{data_type}",
        )

        assert result["ok"] is True
        assert result["data"]["valid"] is True
        assert "plan_hash" in result["data"]

    for cardinality in manage_schema_module.PROPERTY_KEY_CARDINALITIES:
        result = manage_schema(
            mode="dry_run",
            operations=[
                {
                    "type": "create_property_key",
                    "name": f"pk_{cardinality.lower()}",
                    "data_type": "TEXT",
                    "cardinality": cardinality,
                }
            ],
            nonce=f"cardinality-{cardinality}",
        )

        assert result["ok"] is True
        assert result["data"]["valid"] is True
        assert "plan_hash" in result["data"]


def test_dry_run_accepts_valid_edge_frequencies(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    for frequency in manage_schema_module.EDGE_LABEL_FREQUENCIES:
        result = manage_schema(
            mode="dry_run",
            operations=[
                {
                    "type": "create_edge_label",
                    "name": f"knows_{frequency.lower()}",
                    "source_label": "person",
                    "target_label": "person",
                    "frequency": frequency,
                }
            ],
            nonce=f"frequency-{frequency}",
        )

        assert result["ok"] is True
        assert result["data"]["valid"] is True
        assert "plan_hash" in result["data"]


def test_enum_tables_stay_in_sync_with_apply_methods():
    assert manage_schema_module.PROPERTY_KEY_DATA_TYPES == frozenset(
        manage_schema_module.PROPERTY_KEY_DATA_TYPE_METHODS
    )
    assert manage_schema_module.PROPERTY_KEY_CARDINALITIES == frozenset(
        manage_schema_module.PROPERTY_KEY_CARDINALITY_METHODS
    )
    assert manage_schema_module.PROPERTY_KEY_AGGREGATE_TYPES == (
        frozenset(manage_schema_module.PROPERTY_KEY_AGGREGATE_METHODS)
        | manage_schema_module.PROPERTY_KEY_DIRECT_AGGREGATE_TYPES
    )
    assert manage_schema_module.VERTEX_LABEL_ID_STRATEGIES == frozenset(
        manage_schema_module.VERTEX_LABEL_ID_STRATEGY_METHODS
    )
    assert manage_schema_module.EDGE_LABEL_FREQUENCIES == frozenset(
        manage_schema_module.EDGE_LABEL_FREQUENCY_METHODS
    )


def test_invalid_enum_input_never_reaches_apply_stage_error(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            _property_key("name"),
            _vertex_label(
                "person",
                properties=["name"],
                primary_keys=["name"],
                id_strategy="FOO",
            ),
        ],
    )

    _assert_dry_run_invalid(result)
    assert result["data"]["errors"][0]["operation_index"] == 1
    assert "unsupported id_strategy" in result["data"]["errors"][0]["reason"]


def test_manage_schema_dry_run_same_ops_same_hash(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    first = manage_schema(mode="dry_run", operations=[_property_key()], nonce="same")
    second = manage_schema(mode="dry_run", operations=[_property_key()], nonce="same")

    assert first["data"]["plan_hash"] == second["data"]["plan_hash"]


def test_manage_schema_dry_run_without_nonce_gets_fresh_hash(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    first = manage_schema(mode="dry_run", operations=[_property_key()])
    second = manage_schema(mode="dry_run", operations=[_property_key()])

    assert first["data"]["plan_hash"] != second["data"]["plan_hash"]


def test_manage_schema_dry_run_different_ops_different_hash(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    first = manage_schema(mode="dry_run", operations=[_property_key("age")])
    second = manage_schema(mode="dry_run", operations=[_property_key("score")])

    assert first["data"]["plan_hash"] != second["data"]["plan_hash"]


def test_manage_schema_plan_hash_schema_field_order_same_hash():
    operations = [_property_key()]
    schema = _schema(
        propertykeys=[
            {"name": "name", "data_type": "TEXT"},
            {"name": "age", "data_type": "INT"},
        ],
        vertexlabels=[
            {
                "name": "person",
                "properties": [{"name": "name"}, {"name": "age"}],
                "primary_keys": ["name"],
            },
        ],
        edgelabels=[
            {"name": "knows", "source_label": "person", "target_label": "person"},
        ],
    )
    reordered_schema = _schema(
        propertykeys=[
            {"name": "age", "data_type": "INT"},
            {"name": "name", "data_type": "TEXT"},
        ],
        vertexlabels=[
            {
                "name": "person",
                "properties": [{"name": "age"}, {"name": "name"}],
                "primaryKeys": ["name"],
            },
        ],
        edgelabels=[
            {"name": "knows", "sourceLabel": "person", "targetLabel": "person"},
        ],
    )

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(operations, reordered_schema)

    assert first == second


def test_manage_schema_plan_hash_schema_primary_key_change_different_hash():
    operations = [_property_key()]
    schema = _schema(
        vertexlabels=[
            {"name": "person", "properties": ["name", "age"], "primary_keys": ["name"]},
        ],
    )
    changed_schema = _schema(
        vertexlabels=[
            {"name": "person", "properties": ["name", "age"], "primary_keys": ["age"]},
        ],
    )

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(operations, changed_schema)

    assert first != second


def test_manage_schema_plan_hash_schema_label_index_change_different_hash():
    operations = [_property_key()]
    schema = _schema(
        vertexlabels=[
            {
                "name": "person",
                "properties": ["name"],
                "primary_keys": ["name"],
                "enable_label_index": False,
            }
        ],
    )
    changed_schema = _schema(
        vertexlabels=[
            {
                "name": "person",
                "properties": ["name"],
                "primary_keys": ["name"],
                "enable_label_index": True,
            }
        ],
    )

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(operations, changed_schema)

    assert first != second


def test_manage_schema_plan_hash_changes_when_supported_user_data_changes():
    operations = [_property_key()]
    schema = _schema(
        propertykeys=[{"name": "name", "data_type": "TEXT"}],
        vertexlabels=[
            {"name": "person", "properties": ["name"], "primary_keys": ["name"]}
        ],
    )
    schema_with_metadata = _schema(
        propertykeys=[
            {
                "id": 1,
                "name": "name",
                "data_type": "TEXT",
                "user_data": {"x": "y"},
            }
        ],
        vertexlabels=[
            {
                "id": 99,
                "name": "person",
                "properties": ["name"],
                "primary_keys": ["name"],
                "user_data": {"x": "y"},
            }
        ],
    )
    schema_with_metadata["server_time"] = "2026-05-26T00:00:00Z"

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(operations, schema_with_metadata)

    assert first != second


def test_manage_schema_plan_hash_ignores_unrelated_schema_metadata():
    operations = [_property_key()]
    schema = _schema(
        propertykeys=[{"name": "name", "data_type": "TEXT"}],
        vertexlabels=[
            {"name": "person", "properties": ["name"], "primary_keys": ["name"]}
        ],
    )
    schema_with_metadata = _schema(
        propertykeys=[{"id": 1, "name": "name", "data_type": "TEXT"}],
        vertexlabels=[
            {
                "id": 99,
                "name": "person",
                "properties": ["name"],
                "primary_keys": ["name"],
            }
        ],
    )
    schema_with_metadata["server_time"] = "2026-05-26T00:00:00Z"

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(operations, schema_with_metadata)

    assert first == second


def test_manage_schema_plan_hash_operation_order_different_hash():
    schema = _empty_schema()
    operations = [_property_key("age"), _property_key("score")]
    reordered_operations = [_property_key("score"), _property_key("age")]

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(reordered_operations, schema)

    assert first != second


def test_manage_schema_dry_run_rejects_index_apply_scope(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(
            propertykeys=[_live_pk("age")],
            vertexlabels=[_live_vertex("person", properties=["age"])],
        ),
    )

    result = manage_schema(mode="dry_run", operations=[_index_label(fields=["age"])])

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "outside P0a scope" in result["data"]["errors"][0]["reason"]


def test_manage_schema_apply_happy_path(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    state = _empty_schema()

    def live_schema():
        return state

    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", live_schema
    )
    monkeypatch.setattr(
        manage_schema_module, "_schema_manager", lambda: RecordingPropertyManager(state)
    )

    dry_run = manage_schema(
        mode="dry_run",
        operations=[_property_key()],
        nonce="schema-happy",
    )
    context = dry_run["data"]["plan_context"]
    result = manage_schema(
        mode="apply",
        operations=[_property_key()],
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "applied"
    assert result["data"]["applied_operations"] == [_property_key()]


def test_manage_schema_replayed_confirmation_does_not_apply_twice(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    state = _empty_schema()
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", lambda: state
    )
    apply_calls = []

    def fake_apply(operations, *, live_schema):
        apply_calls.append((operations, live_schema))
        state["schema"]["propertykeys"].append(_live_pk("age"))
        return {
            "status": "applied",
            "valid": True,
            "applied_operations": operations,
        }

    monkeypatch.setattr(manage_schema_module, "apply_schema_operations", fake_apply)
    dry_run = manage_schema(
        mode="dry_run", operations=[_property_key()], nonce="schema-replay"
    )
    context = dry_run["data"]["plan_context"]
    arguments = {
        "mode": "apply",
        "operations": [_property_key()],
        "confirm": True,
        "plan_hash": dry_run["data"]["plan_hash"],
        "nonce": context["nonce"],
        "expires_at": context["expires_at"],
    }

    first = manage_schema(**arguments)
    second = manage_schema(**arguments)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error"]["type"] == "PLAN_ALREADY_USED"
    assert state["schema"]["propertykeys"] == [_live_pk("age")]
    assert len(apply_calls) == 1


def test_manage_schema_unconsumed_schema_drift_does_not_consume_nonce(monkeypatch):
    from hugegraph_mcp.confirmation_store import ConfirmationStore

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    state = _empty_schema()
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", lambda: state
    )
    apply_calls = []

    def fake_apply(operations, *, live_schema):
        apply_calls.append((operations, live_schema))
        return {
            "status": "applied",
            "valid": True,
            "applied_operations": operations,
        }

    monkeypatch.setattr(manage_schema_module, "apply_schema_operations", fake_apply)
    dry_run = manage_schema(
        mode="dry_run", operations=[_property_key()], nonce="schema-stale"
    )
    context = dry_run["data"]["plan_context"]
    arguments = {
        "mode": "apply",
        "operations": [_property_key()],
        "confirm": True,
        "plan_hash": dry_run["data"]["plan_hash"],
        "nonce": context["nonce"],
        "expires_at": context["expires_at"],
    }

    state["schema"]["propertykeys"].append(_live_pk("other"))
    stale = manage_schema(**arguments)

    assert stale["ok"] is False
    assert stale["error"]["type"] == "PLAN_HASH_MISMATCH"
    assert ConfirmationStore.from_config().has_consumed(context["nonce"]) is False
    assert apply_calls == []

    state["schema"]["propertykeys"].clear()
    restored = manage_schema(**arguments)
    assert restored["ok"] is True
    assert len(apply_calls) == 1


def test_manage_schema_apply_canonicalizes_property_key_post_read_enums(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    state = _empty_schema()

    def live_schema():
        return state

    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", live_schema
    )
    monkeypatch.setattr(
        manage_schema_module, "_schema_manager", lambda: RecordingPropertyManager(state)
    )

    operations = [
        _property_key("age", "INTEGER"),
        _property_key("active", "BOOL"),
    ]
    dry_run = manage_schema(
        mode="dry_run",
        operations=operations,
        nonce="schema-canonical-enums",
    )
    context = dry_run["data"]["plan_context"]
    result = manage_schema(
        mode="apply",
        operations=operations,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "applied"
    assert state["schema"]["propertykeys"] == [
        {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "active", "data_type": "BOOLEAN", "cardinality": "SINGLE"},
    ]


def test_apply_property_key_options_sets_hugegraph_1_7_aggregate_types():
    for aggregate_type in ("NONE", "SET", "LIST"):
        builder = RecordingPropertyBuilder(f"score_{aggregate_type.lower()}")
        cardinality = aggregate_type if aggregate_type in {"SET", "LIST"} else "SINGLE"

        manage_schema_module._apply_property_key_options(
            builder,
            {
                "type": "create_property_key",
                "name": builder.name,
                "data_type": "INT",
                "cardinality": cardinality,
                "aggregate_type": aggregate_type,
            },
        )

        assert builder.data_type == "INT"
        assert builder.cardinality == cardinality
        assert builder.aggregate_type == aggregate_type


def test_manage_schema_apply_fails_when_post_read_fields_do_not_match(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    state = _empty_schema()

    def live_schema():
        return state

    class PropertyBuilder:
        def __init__(self, name):
            self.name = name
            self.data_type = None
            self.cardinality = None

        def asInt(self):
            self.data_type = "INT"
            return self

        def valueSingle(self):
            self.cardinality = "SINGLE"
            return self

        def calcSum(self):
            return self

        def create(self):
            state["schema"]["propertykeys"].append(
                {
                    "name": self.name,
                    "data_type": self.data_type,
                    "cardinality": self.cardinality,
                    "aggregate_type": "MAX",
                }
            )
            return "ok"

    class FakeManager:
        def propertyKey(self, name):
            return PropertyBuilder(name)

    operation = {
        "type": "create_property_key",
        "name": "age",
        "data_type": "INT",
        "aggregate_type": "SUM",
    }
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", live_schema
    )
    monkeypatch.setattr(manage_schema_module, "_schema_manager", lambda: FakeManager())

    dry_run = manage_schema(
        mode="dry_run",
        operations=[operation],
        nonce="schema-post-read",
    )
    context = dry_run["data"]["plan_context"]
    result = manage_schema(
        mode="apply",
        operations=[operation],
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PARTIAL_APPLY"
    assert result["error"]["details"]["status"] == "failed"
    assert result["error"]["details"]["failed_operation"] == operation
    assert "post-read schema" in result["error"]["details"]["error"]


def test_operation_observed_checks_vertex_and_edge_declared_fields():
    schema = _schema(
        vertexlabels=[
            {
                "name": "person",
                "id_strategy": "PRIMARY_KEY",
                "properties": ["name", "nickname"],
                "primary_keys": ["name"],
                "nullable_keys": ["nickname"],
            }
        ],
        edgelabels=[
            {
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "properties": ["since", "rank"],
                "nullable_keys": ["rank"],
                "sort_keys": ["since"],
                "frequency": "MULTIPLE",
            }
        ],
    )

    vertex_operation = _vertex_label(
        "person",
        properties=["name", "nickname"],
        primary_keys=["name"],
        nullable_keys=["nickname"],
    )
    edge_operation = _edge_label(
        "knows",
        source_label="person",
        target_label="person",
        properties=["since", "rank"],
        nullable_keys=["rank"],
        sort_keys=["since"],
        frequency="MULTIPLE",
    )
    mismatched_edge = dict(edge_operation, sort_keys=["rank"])

    assert manage_schema_module._operation_observed(vertex_operation, schema)
    assert manage_schema_module._operation_observed(edge_operation, schema)
    assert not manage_schema_module._operation_observed(mismatched_edge, schema)


def test_operation_observed_checks_apply_defaults_for_omitted_fields():
    property_operation = _property_key("age")
    property_schema = _schema(
        propertykeys=[{"name": "age", "data_type": "INT", "cardinality": "LIST"}]
    )
    assert not manage_schema_module._operation_observed(
        property_operation, property_schema
    )

    vertex_operation = _vertex_label(
        "person", properties=["name"], primary_keys=["name"]
    )
    vertex_schema = _schema(
        vertexlabels=[
            {
                "name": "person",
                "id_strategy": "AUTOMATIC",
                "properties": ["name"],
                "primary_keys": ["name"],
            }
        ]
    )
    assert not manage_schema_module._operation_observed(vertex_operation, vertex_schema)


def test_operation_observed_rejects_fields_outside_contract():
    operation = dict(
        _property_key("age"),
        ttl=3600,
    )
    schema = _schema(
        propertykeys=[{"name": "age", "data_type": "INT", "cardinality": "SINGLE"}]
    )

    assert not manage_schema_module._operation_observed(operation, schema)


def test_schema_field_table_rejects_unimplemented_fields_before_dry_run(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_vertex_label",
                "name": "person",
                "id_strategy": "AUTOMATIC",
                "ttl": 3600,
            }
        ],
    )

    _assert_dry_run_invalid(result)
    assert any(
        error["reason"] == "unsupported field(s) for create_vertex_label: ttl"
        for error in result["data"]["errors"]
    )


def test_schema_field_table_rejects_non_object_property_key_user_data(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_property_key",
                "name": "score",
                "data_type": "INT",
                "user_data": "silently-dropped",
            }
        ],
    )

    _assert_dry_run_invalid(result)
    assert any(
        error["reason"] == "user_data must be an object"
        for error in result["data"]["errors"]
    )


def test_schema_field_table_rejects_non_object_user_data_before_plan_for_all_supported_operations(
    monkeypatch,
):
    cases = [
        (
            _empty_schema(),
            {
                "type": "create_property_key",
                "name": "score",
                "data_type": "INT",
                "user_data": "invalid",
            },
        ),
        (
            _empty_schema(),
            {
                "type": "create_vertex_label",
                "name": "person",
                "id_strategy": "AUTOMATIC",
                "user_data": ["invalid"],
            },
        ),
        (
            _schema(vertexlabels=[_live_vertex("person")]),
            {
                "type": "create_edge_label",
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "user_data": 1,
            },
        ),
    ]

    for live_schema, operation in cases:
        monkeypatch.setattr(
            manage_schema_module.schema_tools,
            "get_live_schema",
            lambda live_schema=live_schema: live_schema,
        )
        result = manage_schema(mode="dry_run", operations=[operation])

        _assert_dry_run_invalid(result)
        assert any(
            error["reason"] == "user_data must be an object"
            for error in result["data"]["errors"]
        )


def test_schema_field_table_forwards_and_matches_label_options():
    builder = Mock()
    operation = {
        "type": "create_vertex_label",
        "name": "person",
        "id_strategy": "AUTOMATIC",
        "properties": [],
        "index_labels": ["person_by_name"],
        "enable_label_index": False,
        "user_data": {"owner": "mcp"},
    }

    manage_schema_module._apply_vertex_label_options(builder, operation)

    builder.enableLabelIndex.assert_called_once_with(False)
    builder.add_parameter.assert_any_call("index_labels", ["person_by_name"])
    builder.add_parameter.assert_any_call("user_data", {"owner": "mcp"})

    observed = _schema(
        vertexlabels=[
            {
                "name": "person",
                "id_strategy": "AUTOMATIC",
                "properties": [],
                "index_labels": ["person_by_name"],
                "enable_label_index": False,
                "user_data": {"owner": "mcp"},
            }
        ]
    )
    assert manage_schema_module._operation_observed(operation, observed)


def test_schema_field_table_forwards_and_matches_edge_label_options():
    builder = Mock()
    operation = {
        "type": "create_edge_label",
        "name": "knows",
        "source_label": "person",
        "target_label": "person",
        "properties": [],
        "nullable_keys": [],
        "sort_keys": [],
        "frequency": "MULTIPLE",
        "enable_label_index": True,
        "user_data": {"owner": "mcp"},
    }

    manage_schema_module._apply_edge_label_options(builder, operation)

    builder.link.assert_called_once_with("person", "person")
    builder.multiTimes.assert_called_once_with()
    builder.enableLabelIndex.assert_called_once_with(True)
    builder.add_parameter.assert_called_once_with("user_data", {"owner": "mcp"})

    observed = _schema(
        edgelabels=[
            {
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "properties": [],
                "nullable_keys": [],
                "sort_keys": [],
                "frequency": "MULTIPLE",
                "enable_label_index": True,
                "user_data": {"owner": "mcp"},
            }
        ]
    )
    assert manage_schema_module._operation_observed(operation, observed)


def test_schema_field_table_forwards_property_key_user_data():
    builder = Mock()
    operation = {
        "type": "create_property_key",
        "name": "score",
        "data_type": "INT",
        "user_data": {"unit": "points"},
    }

    manage_schema_module._apply_property_key_options(builder, operation)

    builder.add_parameter.assert_called_once_with("user_data", {"unit": "points"})

    observed = _schema(
        propertykeys=[
            {
                "name": "score",
                "data_type": "INT",
                "cardinality": "SINGLE",
                "user_data": {"unit": "points"},
            }
        ]
    )
    assert manage_schema_module._operation_observed(operation, observed)


def test_schema_field_table_post_read_rejects_supported_field_loss():
    cases = [
        (
            {
                "type": "create_property_key",
                "name": "score",
                "data_type": "INT",
                "user_data": {"unit": "points"},
            },
            _schema(
                propertykeys=[
                    {
                        "name": "score",
                        "data_type": "INT",
                        "cardinality": "SINGLE",
                        "user_data": {},
                    }
                ]
            ),
        ),
        (
            {
                "type": "create_vertex_label",
                "name": "person",
                "id_strategy": "AUTOMATIC",
                "enable_label_index": True,
                "user_data": {"owner": "mcp"},
            },
            _schema(
                vertexlabels=[
                    {
                        "name": "person",
                        "id_strategy": "AUTOMATIC",
                        "enable_label_index": False,
                        "user_data": {"owner": "mcp"},
                    }
                ]
            ),
        ),
        (
            {
                "type": "create_edge_label",
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "enable_label_index": True,
                "user_data": {"owner": "mcp"},
            },
            _schema(
                edgelabels=[
                    {
                        "name": "knows",
                        "source_label": "person",
                        "target_label": "person",
                        "enable_label_index": True,
                        "user_data": {},
                    }
                ]
            ),
        ),
        (
            {
                "type": "create_vertex_label",
                "name": "person",
                "id_strategy": "AUTOMATIC",
                "properties": [],
            },
            _schema(
                vertexlabels=[
                    {
                        "name": "person",
                        "id_strategy": "AUTOMATIC",
                    }
                ]
            ),
        ),
    ]

    for operation, observed in cases:
        assert not manage_schema_module._operation_observed(operation, observed)


def test_schema_field_table_forwards_property_key_aggregate_and_user_data():
    builder = Mock()
    operation = {
        "type": "create_property_key",
        "name": "score",
        "data_type": "INT",
        "aggregate_type": "NONE",
        "user_data": {"unit": "points"},
    }

    manage_schema_module._apply_property_key_options(builder, operation)

    builder.add_parameter.assert_any_call("aggregate_type", "NONE")
    builder.add_parameter.assert_any_call("user_data", {"unit": "points"})


def test_manage_schema_apply_partial_failure(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    state = _empty_schema()

    def live_schema():
        return state

    class PropertyBuilder:
        def __init__(self, name):
            self.name = name
            self.data_type = None
            self.cardinality = None

        def asInt(self):
            self.data_type = "INT"
            return self

        def valueSingle(self):
            self.cardinality = "SINGLE"
            return self

        def create(self):
            state["schema"]["propertykeys"].append(
                {
                    "name": self.name,
                    "data_type": self.data_type,
                    "cardinality": self.cardinality,
                }
            )
            return "ok"

    class VertexBuilder:
        def __init__(self, name):
            self.name = name

        def usePrimaryKeyId(self):
            return self

        def properties(self, *args):
            return self

        def primaryKeys(self, *args):
            return self

        def create(self):
            raise RuntimeError("builder failed")

    class FakeManager:
        def propertyKey(self, name):
            return PropertyBuilder(name)

        def vertexLabel(self, name):
            return VertexBuilder(name)

    operations = [
        _property_key(),
        _vertex_label("person", properties=["age"], primary_keys=["age"]),
    ]
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", live_schema
    )
    monkeypatch.setattr(manage_schema_module, "_schema_manager", lambda: FakeManager())

    dry_run = manage_schema(mode="dry_run", operations=operations, nonce="partial")
    context = dry_run["data"]["plan_context"]
    result = manage_schema(
        mode="apply",
        operations=operations,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PARTIAL_APPLY"
    assert result["error"]["details"]["status"] == "partial"
    assert result["error"]["details"]["applied_operations"] == [_property_key()]
    assert "inspect_schema_tool" in result["next_actions"][0]


def test_manage_schema_apply_hash_mismatch(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="apply",
        operations=[_property_key()],
        confirm=True,
        plan_hash="bad",
        nonce="schema-hash",
        expires_at=9999999999,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_manage_schema_apply_readonly_blocks_after_valid_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    dry_run = manage_schema(
        mode="dry_run",
        operations=[_property_key()],
        nonce="readonly",
    )
    context = dry_run["data"]["plan_context"]
    result = manage_schema(
        mode="apply",
        operations=[_property_key()],
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"
