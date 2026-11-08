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

import pytest
from pyhugegraph.api.schema_manage.edge_label import EdgeLabel
from pyhugegraph.api.schema_manage.index_label import IndexLabel
from pyhugegraph.api.schema_manage.property_key import PropertyKey
from pyhugegraph.api.schema_manage.vertex_label import VertexLabel

pytestmark = pytest.mark.contract


class DummySchemaSession:
    def __init__(self):
        self.requests = []

    def request(self, path, method="GET", validator=None, **kwargs):
        self.requests.append({"path": path, "method": method, "validator": validator, **kwargs})
        return {"ok": True}


def test_property_key_create_includes_aggregate_type_in_payload():
    session = DummySchemaSession()
    property_key = PropertyKey(session)

    property_key.create_parameter_holder()
    property_key.add_parameter("name", "score")
    property_key.as_int().value_single().calc_sum().create()

    request = session.requests[-1]
    assert request["path"] == "schema/propertykeys"
    assert request["method"] == "POST"
    assert json.loads(request["data"]) == {
        "name": "score",
        "data_type": "INT",
        "cardinality": "SINGLE",
        "aggregate_type": "SUM",
    }


def test_property_key_create_includes_user_data_in_payload():
    session = DummySchemaSession()
    property_key = PropertyKey(session)

    property_key.create_parameter_holder()
    property_key.add_parameter("name", "score")
    property_key.as_int().value_single().userdata("min", 0, "max", 100).create()

    request = session.requests[-1]
    assert request["path"] == "schema/propertykeys"
    assert request["method"] == "POST"
    assert json.loads(request["data"]) == {
        "name": "score",
        "data_type": "INT",
        "cardinality": "SINGLE",
        "user_data": {"min": 0, "max": 100},
    }


def test_index_label_create_preserves_field_order_and_deduplicates():
    session = DummySchemaSession()
    index_label = IndexLabel(session)

    index_label.create_parameter_holder()
    index_label.add_parameter("name", "personByAgeCity")
    index_label.on_v("person").by("age", "city", "age").secondary().create()

    request = session.requests[-1]
    assert request["path"] == "schema/indexlabels"
    assert request["method"] == "POST"
    assert json.loads(request["data"]) == {
        "name": "personByAgeCity",
        "base_type": "VERTEX_LABEL",
        "base_value": "person",
        "index_type": "SECONDARY",
        "fields": ["age", "city"],
    }


def _builder(builder_cls, name, session):
    builder = builder_cls(session)
    builder.create_parameter_holder()
    builder.add_parameter("name", name)
    return builder


@pytest.mark.parametrize(
    ("builder_cls", "name", "action", "expected_path", "expected_data"),
    [
        (
            PropertyKey,
            "age",
            "append",
            "schema/propertykeys/age/?action=append",
            {"name": "age", "user_data": {"min": 0}},
        ),
        (
            PropertyKey,
            "age",
            "eliminate",
            "schema/propertykeys/age/?action=eliminate",
            {"name": "age", "user_data": {"min": 0}},
        ),
        (
            VertexLabel,
            "person",
            "append",
            "schema/vertexlabels/person?action=append",
            {"name": "person", "properties": [], "nullable_keys": [], "user_data": {"min": 0}},
        ),
        (
            VertexLabel,
            "person",
            "eliminate",
            "schema/vertexlabels/person/?action=eliminate",
            {"name": "person", "user_data": {"min": 0}},
        ),
        (
            EdgeLabel,
            "knows",
            "append",
            "schema/edgelabels/knows?action=append",
            {"name": "knows", "user_data": {"min": 0}},
        ),
        (
            EdgeLabel,
            "knows",
            "eliminate",
            "schema/edgelabels/knows?action=eliminate",
            {"name": "knows", "user_data": {"min": 0}},
        ),
    ],
)
def test_schema_builder_user_data_updates_use_put_with_action(builder_cls, name, action, expected_path, expected_data):
    session = DummySchemaSession()
    builder = _builder(builder_cls, name, session).userdata("min", 0)

    getattr(builder, action)()

    request = session.requests[-1]
    assert request["method"] == "PUT"
    assert request["path"] == expected_path
    assert json.loads(request["data"]) == expected_data


@pytest.mark.parametrize(
    ("builder_cls", "name", "expected_path"),
    [
        (PropertyKey, "age", "schema/propertykeys/age"),
        (VertexLabel, "person", "schema/vertexlabels/person"),
        (EdgeLabel, "knows", "schema/edgelabels/knows"),
        (IndexLabel, "personByAge", "schema/indexlabels/personByAge"),
    ],
)
def test_schema_builder_remove_sends_delete_without_body(builder_cls, name, expected_path):
    session = DummySchemaSession()

    _builder(builder_cls, name, session).remove()

    assert session.requests == [{"path": expected_path, "method": "DELETE", "validator": None}]


@pytest.mark.parametrize(
    ("builder_cls", "action"),
    [
        (PropertyKey, "append"),
        (PropertyKey, "eliminate"),
        (PropertyKey, "remove"),
        (VertexLabel, "append"),
        (VertexLabel, "eliminate"),
        (VertexLabel, "remove"),
        (EdgeLabel, "append"),
        (EdgeLabel, "eliminate"),
        (EdgeLabel, "remove"),
        (IndexLabel, "remove"),
    ],
)
def test_schema_builder_write_clears_parameters(builder_cls, action):
    builder = _builder(builder_cls, "item", DummySchemaSession())
    if action != "remove":
        builder.userdata("min", 0)

    getattr(builder, action)()

    assert builder.get_parameter_holder().get_dic() == {}
