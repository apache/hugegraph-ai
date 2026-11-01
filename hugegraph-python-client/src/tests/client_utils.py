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

import os

from pyhugegraph.client import PyHugeClient


class ClientUtils:
    URL = "http://127.0.0.1:8080"
    GRAPH = "hugegraph"
    USERNAME = "admin"
    PASSWORD = "admin"
    GRAPHSPACE = None
    TIMEOUT = 10

    def __init__(self, service=None):
        if service is not None:
            self.URL = service.url
            self.GRAPH = service.graph
            self.USERNAME = service.user
            self.PASSWORD = service.password
            self.GRAPHSPACE = service.graphspace
        else:
            self.URL = os.getenv("HUGEGRAPH_URL", self.URL)
            self.GRAPH = os.getenv("HUGEGRAPH_GRAPH", self.GRAPH)
            self.USERNAME = os.getenv("HUGEGRAPH_USER", self.USERNAME)
            self.PASSWORD = os.getenv("HUGEGRAPH_PASSWORD", self.PASSWORD)
            self.GRAPHSPACE = os.getenv("HUGEGRAPH_GRAPHSPACE") or self.GRAPHSPACE
        self.client = PyHugeClient(
            url=self.URL,
            user=self.USERNAME,
            pwd=self.PASSWORD,
            graph=self.GRAPH,
            graphspace=self.GRAPHSPACE,
        )
        assert self.client is not None

        self.schema = self.client.schema()
        self.gremlin = self.client.gremlin()
        self.graph = self.client.graph()
        self.graphs = self.client.graphs()
        self.variable = self.client.variable()
        self.auth = self.client.auth()
        self.task = self.client.task()
        self.metrics = self.client.metrics()
        self.traverser = self.client.traverser()
        self.version = self.client.version()

    def init_property_key(self):
        schema = self.schema
        schema.property_key("name").as_text().if_not_exist().create()
        schema.property_key("age").as_int().if_not_exist().create()
        schema.property_key("city").as_text().if_not_exist().create()
        schema.property_key("lang").as_text().if_not_exist().create()
        schema.property_key("date").as_date().if_not_exist().create()
        schema.property_key("price").as_int().if_not_exist().create()
        schema.property_key("weight").as_double().if_not_exist().create()
        schema.property_key("headcount").as_int().if_not_exist().create()
        schema.property_key("floor").as_int().if_not_exist().create()

    def init_vertex_label(self):
        schema = self.schema
        schema.vertex_label("person").properties("name", "age", "city").primary_keys("name").nullable_keys(
            "city"
        ).if_not_exist().create()
        schema.vertex_label("software").properties("name", "lang", "price").primary_keys("name").nullable_keys(
            "price"
        ).if_not_exist().create()
        schema.vertex_label("book").use_customize_string_id().properties("name", "price").nullable_keys(
            "price"
        ).if_not_exist().create()
        schema.vertex_label("department").properties("name", "headcount", "floor").nullable_keys(
            "floor"
        ).if_not_exist().create()

    def init_edge_label(self):
        schema = self.schema
        schema.edge_label("knows").source_label("person").target_label("person").multi_times().properties(
            "date", "city"
        ).sort_keys("date").nullable_keys("city").if_not_exist().create()
        schema.edge_label("created").source_label("person").target_label("software").properties(
            "date", "city"
        ).nullable_keys("city").if_not_exist().create()
        schema.edge_label("reports_to").source_label("department").target_label("department").properties(
            "date"
        ).if_not_exist().create()

    def init_index_label(self):
        schema = self.schema
        schema.index_label("personByCity").on_v("person").by("city").secondary().if_not_exist().create()
        schema.index_label("personByAge").on_v("person").by("age").range().if_not_exist().create()
        schema.index_label("softwareByPrice").on_v("software").by("price").range().if_not_exist().create()
        schema.index_label("softwareByLang").on_v("software").by("lang").secondary().if_not_exist().create()
        schema.index_label("knowsByDate").on_e("knows").by("date").secondary().if_not_exist().create()
        schema.index_label("createdByDate").on_e("created").by("date").secondary().if_not_exist().create()

    def init_vertices(self):
        graph = self.graph
        graph.add_vertex("person", {"name": "marko", "age": 29, "city": "Beijing"})
        graph.add_vertex("person", {"name": "vadas", "age": 27, "city": "Hongkong"})
        graph.add_vertex("software", {"name": "lop", "lang": "java", "price": 328})
        graph.add_vertex("person", {"name": "josh", "age": 32, "city": "Beijing"})
        graph.add_vertex("software", {"name": "ripple", "lang": "java", "price": 199})
        graph.add_vertex("person", {"name": "peter", "age": 29, "city": "Shanghai"})

    def init_edges(self):
        marko_id = self._get_vertex_id("person", {"name": "marko"})
        vadas_id = self._get_vertex_id("person", {"name": "vadas"})
        josh_id = self._get_vertex_id("person", {"name": "josh"})
        peter_id = self._get_vertex_id("person", {"name": "peter"})
        lop_id = self._get_vertex_id("software", {"name": "lop"})
        ripple_id = self._get_vertex_id("software", {"name": "ripple"})

        self.graph.add_edge("knows", marko_id, vadas_id, {"date": "2012-01-10"})
        self.graph.add_edge("knows", marko_id, josh_id, {"date": "2013-01-10"})
        self.graph.add_edge("created", marko_id, lop_id, {"date": "2014-01-10", "city": "Shanghai"})
        self.graph.add_edge("created", josh_id, ripple_id, {"date": "2015-01-10", "city": "Beijing"})
        self.graph.add_edge("created", josh_id, lop_id, {"date": "2016-01-10", "city": "Beijing"})
        self.graph.add_edge("created", peter_id, lop_id, {"date": "2017-01-10", "city": "Hongkong"})

    def _get_vertex_id(self, label, properties):
        res = self._get_vertex(label, properties)
        return res.id

    def _get_vertex(self, label, properties):
        lst = self.graph.get_vertex_by_condition(label=label, limit=1, properties=properties)
        assert len(lst) == 1, "Can't find vertex."
        return lst[0]

    def clear_graph_all_data(self):
        self.graphs.clear_graph_all_data()
