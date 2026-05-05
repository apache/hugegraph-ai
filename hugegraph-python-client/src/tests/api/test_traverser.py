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

from ..client_utils import ClientUtils


class TestTraverserManager(unittest.TestCase):
    client = None
    traverser = None
    graph = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.traverser = cls.client.traverser
        cls.graph = cls.client.graph
        cls.client.clear_graph_all_data()
        cls.client.init_property_key()
        cls.client.init_vertex_label()
        cls.client.init_edge_label()

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        self.client.init_vertices()
        self.client.init_edges()

    def tearDown(self):
        pass

    def test_traverser_operations(self):
        marko = self.graph.getVertexByCondition("person", properties={"name": "marko"})[0].id
        josh = self.graph.getVertexByCondition("person", properties={"name": "josh"})[0].id
        ripple = self.graph.getVertexByCondition("software", properties={"name": "ripple"})[0].id

        k_out_result = self.traverser.k_out(marko, 2)
        self.assertEqual(k_out_result["vertices"], ["1:peter", "2:ripple"])

        k_neighbor_result = self.traverser.k_neighbor(marko, 2)
        self.assertEqual(k_neighbor_result["vertices"], ["1:peter", "1:josh", "2:lop", "2:ripple", "1:vadas"])

        same_neighbors_result = self.traverser.same_neighbors(marko, josh)
        self.assertEqual(same_neighbors_result["same_neighbors"], ["2:lop"])

        jaccard_similarity_result = self.traverser.jaccard_similarity(marko, josh)
        self.assertEqual(jaccard_similarity_result["jaccard_similarity"], 0.2)

        shortest_path_result = self.traverser.shortest_path(marko, ripple, 3)
        self.assertEqual(shortest_path_result["path"], ["1:marko", "1:josh", "2:ripple"])

        all_shortest_paths_result = self.traverser.all_shortest_paths(marko, ripple, 3)
        self.assertEqual(all_shortest_paths_result["paths"], [{"objects": ["1:marko", "1:josh", "2:ripple"]}])

        weighted_shortest_path_result = self.traverser.weighted_shortest_path(marko, ripple, "weight", 3)
        self.assertEqual(weighted_shortest_path_result["vertices"], ["1:marko", "1:josh", "2:ripple"])

        single_source_shortest_path_result = self.traverser.single_source_shortest_path(marko, 2)
        self.assertEqual(
            single_source_shortest_path_result["paths"],
            {
                "1:peter": {"weight": 2.0, "vertices": ["1:marko", "2:lop", "1:peter"]},
                "1:josh": {"weight": 1.0, "vertices": ["1:marko", "1:josh"]},
                "2:lop": {"weight": 1.0, "vertices": ["1:marko", "2:lop"]},
                "2:ripple": {"weight": 2.0, "vertices": ["1:marko", "1:josh", "2:ripple"]},
                "1:vadas": {"weight": 1.0, "vertices": ["1:marko", "1:vadas"]},
            },
        )

        multi_node_shortest_path_result = self.traverser.multi_node_shortest_path([marko, josh], max_depth=2)
        self.assertEqual(
            multi_node_shortest_path_result["vertices"],
            [
                {
                    "id": "1:marko",
                    "label": "person",
                    "type": "vertex",
                    "properties": {"name": "marko", "age": 29, "city": "Beijing"},
                },
                {
                    "id": "1:josh",
                    "label": "person",
                    "type": "vertex",
                    "properties": {"name": "josh", "age": 32, "city": "Beijing"},
                },
            ],
        )

        paths_result = self.traverser.paths(marko, josh, 2)
        self.assertEqual(
            paths_result["paths"],
            [{"objects": ["1:marko", "2:lop", "1:josh"]}, {"objects": ["1:marko", "1:josh"]}],
        )

        customized_paths_result = self.traverser.customized_paths(
            {"ids": [], "label": "person", "properties": {"name": "marko"}},
            [
                {
                    "direction": "OUT",
                    "labels": ["created"],
                    "default_weight": 8,
                    "max_degree": -1,
                    "sample": 1,
                }
            ],
        )
        self.assertEqual(customized_paths_result["paths"], [{"objects": ["1:marko", "2:lop"], "weights": [8.0]}])

        sources = {"ids": [], "label": "person", "properties": {"name": "vadas"}}

        targets = {"ids": [], "label": "software", "properties": {"name": "ripple"}}

        steps = [
            {
                "direction": "IN",
                "labels": ["knows"],
                "properties": {},
                "max_degree": 10000,
                "skip_degree": 100000,
            },
            {
                "direction": "OUT",
                "labels": ["created"],
                "properties": {},
                "max_degree": 10000,
                "skip_degree": 100000,
            },
            {
                "direction": "IN",
                "labels": ["created"],
                "properties": {},
                "max_degree": 10000,
                "skip_degree": 100000,
            },
            {
                "direction": "OUT",
                "labels": ["created"],
                "properties": {},
                "max_degree": 10000,
                "skip_degree": 100000,
            },
        ]
        template_paths_result = self.traverser.template_paths(sources, targets, steps)
        self.assertEqual(
            template_paths_result["paths"],
            [{"objects": ["1:vadas", "1:marko", "2:lop", "1:josh", "2:ripple"]}],
        )

        crosspoints_result = self.traverser.crosspoints(marko, josh, 2)
        self.assertEqual(
            crosspoints_result["crosspoints"],
            [
                {"crosspoint": "2:lop", "objects": ["1:marko", "2:lop", "1:josh"]},
                {"crosspoint": "1:josh", "objects": ["1:marko", "1:josh"]},
            ],
        )

        sources = {"ids": ["2:lop", "2:ripple"]}
        path_patterns = [{"steps": [{"direction": "IN", "labels": ["created"], "max_degree": -1}]}]
        customized_crosspoints_result = self.traverser.customized_crosspoints(sources, path_patterns)
        self.assertEqual(customized_crosspoints_result["crosspoints"], ["1:josh"])

        rings_result = self.traverser.rings(marko, 3)
        self.assertEqual(rings_result["rings"], [{"objects": ["1:marko", "2:lop", "1:josh", "1:marko"]}])

        rays_result = self.traverser.rays(marko, 2)
        self.assertEqual(
            rays_result["rays"],
            [
                {"objects": ["1:marko", "2:lop", "1:josh"]},
                {"objects": ["1:marko", "2:lop", "1:peter"]},
                {"objects": ["1:marko", "1:vadas"]},
                {"objects": ["1:marko", "1:josh", "2:ripple"]},
                {"objects": ["1:marko", "1:josh", "2:lop"]},
            ],
        )

        sources = {"ids": [marko]}
        fusiform_similarity_result = self.traverser.fusiform_similarity(
            sources,
            label="knows",
            direction="OUT",
            min_neighbors=8,
            alpha=0.75,
            min_similars=1,
            top=0,
            group_property="city",
            min_groups=2,
            max_degree=10000,
            capacity=-1,
            limit=-1,
            with_intermediary=False,
            with_vertex=True,
        )
        self.assertTrue("similars" in fusiform_similarity_result)

        vertices_result = self.traverser.vertices(marko)
        self.assertEqual(
            vertices_result["vertices"],
            [
                {
                    "id": "1:marko",
                    "label": "person",
                    "type": "vertex",
                    "properties": {"name": "marko", "age": 29, "city": "Beijing"},
                }
            ],
        )

        edge_id = self.graph.getEdgeByPage("created", josh, "BOTH")[0][0]
        edges_result = self.traverser.edges(edge_id.id)
        # Use the dynamically retrieved edge ID instead of hardcoding format
        # to ensure compatibility with different HugeGraph versions (1.3.0, 1.7.0, etc.)
        expected_edge = {
            "id": edge_id.id,
            "label": "created",
            "type": "edge",
            "outV": "1:josh",
            "outVLabel": "person",
            "inV": "2:lop",
            "inVLabel": "software",
            "properties": {"city": "Beijing", "date": "2016-01-10 00:00:00.000"},
        }
        # Note: Edge ID format uses the dynamic id field instead of hardcoded format.
        # In HugeGraph 1.7.0, sub-edge labels encode both parent and child label IDs,
        # so the format differs from regular edges. Always use edge_id.id instead of assuming format.
        self.assertEqual(edges_result["edges"], [expected_edge])
