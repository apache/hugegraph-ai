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

import unittest
from contextlib import suppress

import pytest

from ..client_utils import ClientUtils

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]


class TestSchemaManager(unittest.TestCase):
    client = None
    schema = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.client.clear_graph_all_data()
        cls.schema = cls.client.schema
        cls.client.init_property_key()
        cls.client.init_vertex_label()
        cls.client.init_edge_label()
        cls.client.init_index_label()

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_get_schema(self):
        schema = self.schema.get_schema()
        self.assertEqual(4, len(schema))

    def test_get_property_keys(self):
        property_keys = self.schema.get_property_keys()
        property_key_names = {property_key.name for property_key in property_keys}
        self.assertTrue(
            {"name", "age", "city", "lang", "date", "price", "weight", "headcount", "floor"}.issubset(
                property_key_names
            )
        )

    def test_get_property_key(self):
        property_key = self.schema.get_property_key("name")
        self.assertEqual(property_key.name, "name")

    def test_get_vertex_labels(self):
        vertex_labels = self.schema.get_vertex_labels()
        vertex_label_names = {vertex_label.name for vertex_label in vertex_labels}
        self.assertTrue({"person", "software", "book", "department"}.issubset(vertex_label_names))

    def test_get_vertex_label(self):
        vertex_label = self.schema.get_vertex_label("person")
        self.assertEqual(vertex_label.name, "person")

    def test_get_edge_labels(self):
        edge_labels = self.schema.get_edge_labels()
        edge_label_names = {edge_label.name for edge_label in edge_labels}
        self.assertTrue({"knows", "created", "reports_to"}.issubset(edge_label_names))

    def test_get_edge_label(self):
        edge_label = self.schema.get_edge_label("knows")
        self.assertEqual(edge_label.name, "knows")

    def test_get_index_labels(self):
        index_labels = self.schema.get_index_labels()
        self.assertEqual(6, len(index_labels))

    def test_get_index_label(self):
        index_label = self.schema.get_index_label("personByCity")
        self.assertEqual(index_label.name, "personByCity")


def test_schema_create_and_fetch_property_vertex_edge_index(client_utils):
    schema = client_utils.schema
    try:
        schema.property_key("quality_name").as_text().if_not_exist().create()
        schema.property_key("quality_score").as_int().if_not_exist().create()
        schema.vertex_label("quality_person").properties("quality_name", "quality_score").primary_keys(
            "quality_name"
        ).if_not_exist().create()
        schema.edge_label("quality_knows").source_label("quality_person").target_label(
            "quality_person"
        ).if_not_exist().create()
        schema.index_label("quality_person_by_score").on_v("quality_person").by(
            "quality_score"
        ).range().if_not_exist().create()

        full_schema = schema.get_schema()

        assert "propertykeys" in full_schema
        assert "vertexlabels" in full_schema
        assert "edgelabels" in full_schema
        assert "indexlabels" in full_schema
        assert schema.get_property_key("quality_name").name == "quality_name"
        assert schema.get_vertex_label("quality_person").name == "quality_person"
        assert schema.get_edge_label("quality_knows").name == "quality_knows"
        assert schema.get_index_label("quality_person_by_score").name == "quality_person_by_score"
    finally:
        for remove in (
            lambda: schema.index_label("quality_person_by_score").remove(),
            lambda: schema.edge_label("quality_knows").remove(),
            lambda: schema.vertex_label("quality_person").remove(),
            lambda: schema.property_key("quality_score").remove(),
            lambda: schema.property_key("quality_name").remove(),
        ):
            with suppress(Exception):
                remove()
