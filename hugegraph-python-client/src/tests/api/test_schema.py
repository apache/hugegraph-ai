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
        schema = self.schema.getSchema()
        self.assertEqual(4, len(schema))

    def test_get_property_keys(self):
        property_keys = self.schema.getPropertyKeys()
        self.assertEqual(7, len(property_keys))

    def test_get_property_key(self):
        property_key = self.schema.getPropertyKey("name")
        self.assertEqual(property_key.name, "name")

    def test_get_vertex_labels(self):
        vertex_labels = self.schema.getVertexLabels()
        self.assertEqual(3, len(vertex_labels))

    def test_get_vertex_label(self):
        vertex_label = self.schema.getVertexLabel("person")
        self.assertEqual(vertex_label.name, "person")

    def test_get_edge_labels(self):
        edge_labels = self.schema.getEdgeLabels()
        self.assertEqual(2, len(edge_labels))

    def test_get_edge_label(self):
        edge_label = self.schema.getEdgeLabel("knows")
        self.assertEqual(edge_label.name, "knows")

    def test_get_index_labels(self):
        index_labels = self.schema.getIndexLabels()
        self.assertEqual(6, len(index_labels))

    def test_get_index_label(self):
        index_label = self.schema.getIndexLabel("personByCity")
        self.assertEqual(index_label.name, "personByCity")


def test_schema_create_and_fetch_property_vertex_edge_index(client_utils):
    schema = client_utils.schema
    try:
        schema.propertyKey("quality_name").asText().ifNotExist().create()
        schema.propertyKey("quality_score").asInt().ifNotExist().create()
        schema.vertexLabel("quality_person").properties("quality_name", "quality_score").primaryKeys(
            "quality_name"
        ).ifNotExist().create()
        schema.edgeLabel("quality_knows").sourceLabel("quality_person").targetLabel(
            "quality_person"
        ).ifNotExist().create()
        schema.indexLabel("quality_person_by_score").onV("quality_person").by(
            "quality_score"
        ).range().ifNotExist().create()

        full_schema = schema.getSchema()

        assert "propertykeys" in full_schema
        assert "vertexlabels" in full_schema
        assert "edgelabels" in full_schema
        assert "indexlabels" in full_schema
        assert schema.getPropertyKey("quality_name").name == "quality_name"
        assert schema.getVertexLabel("quality_person").name == "quality_person"
        assert schema.getEdgeLabel("quality_knows").name == "quality_knows"
        assert schema.getIndexLabel("quality_person_by_score").name == "quality_person_by_score"
    finally:
        for remove in (
            lambda: schema.indexLabel("quality_person_by_score").remove(),
            lambda: schema.edgeLabel("quality_knows").remove(),
            lambda: schema.vertexLabel("quality_person").remove(),
            lambda: schema.propertyKey("quality_score").remove(),
            lambda: schema.propertyKey("quality_name").remove(),
        ):
            with suppress(Exception):
                remove()
