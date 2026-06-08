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
from pathlib import Path

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.integration, pytest.mark.hugegraph]

QUALITY_COMMIT_SCHEMA = {
    "propertykeys": [
        {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "lang", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "date", "data_type": "TEXT", "cardinality": "SINGLE"},
    ],
    "vertexlabels": [
        {
            "name": "quality_person",
            "properties": ["name", "age"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        },
        {
            "name": "quality_software",
            "properties": ["name", "lang"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        },
    ],
    "edgelabels": [
        {
            "name": "quality_created",
            "source_label": "quality_person",
            "target_label": "quality_software",
            "properties": ["date"],
        }
    ],
}


def test_kg_construction_smoke_uses_production_code(hugegraph_client):
    from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph
    from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData

    fixture_file = Path(__file__).resolve().parents[1] / "data" / "quality_program" / "kg_graph_output.json"
    fixture = json.loads(fixture_file.read_text(encoding="utf-8"))
    assert fixture["vertices"]
    assert fixture["edges"]

    data = {
        "schema": QUALITY_COMMIT_SCHEMA,
        "vertices": fixture["vertices"],
        "edges": fixture["edges"],
    }
    Commit2Graph().run(data)

    summary = FetchGraphData(hugegraph_client).run({})
    vertices = hugegraph_client.gremlin().exec(
        """
        g.V().hasLabel('quality_person', 'quality_software').
          project('label', 'name', 'age', 'lang').
          by(label()).
          by(values('name')).
          by(coalesce(values('age'), constant(null))).
          by(coalesce(values('lang'), constant(null)))
        """
    )["data"]
    edges = hugegraph_client.gremlin().exec(
        """
        g.E().hasLabel('quality_created').
          project('label', 'out', 'in', 'date').
          by(label()).
          by(outV().values('name')).
          by(inV().values('name')).
          by(values('date'))
        """
    )["data"]

    assert summary["vertex_num"] == len(fixture["vertices"])
    assert summary["edge_num"] == len(fixture["edges"])
    assert sorted(vertices, key=lambda item: item["label"]) == [
        {"label": "quality_person", "name": "marko", "age": 29, "lang": None},
        {"label": "quality_software", "name": "lop", "age": None, "lang": "java"},
    ]
    assert edges == [
        {
            "label": "quality_created",
            "out": "marko",
            "in": "lop",
            "date": "2026-05-31",
        }
    ]
