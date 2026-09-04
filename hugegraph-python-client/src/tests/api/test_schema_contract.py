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
from pyhugegraph.api.schema_manage.index_label import IndexLabel
from pyhugegraph.api.schema_manage.property_key import PropertyKey

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
    property_key.asInt().valueSingle().calcSum().create()

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
    property_key.asInt().valueSingle().userdata("min", 0, "max", 100).create()

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
    index_label.onV("person").by("age", "city", "age").secondary().create()

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
