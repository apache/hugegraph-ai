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

from copy import deepcopy

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]

QUALITY_SCHEMA = {
    "vertices": [
        {"vertex_label": "quality_person", "properties": ["name", "age"], "primary_keys": ["name"]},
        {"vertex_label": "quality_software", "properties": ["name", "lang"], "primary_keys": ["name"]},
    ],
    "edges": [
        {
            "edge_label": "quality_created",
            "source_vertex_label": "quality_person",
            "target_vertex_label": "quality_software",
            "properties": ["date"],
        }
    ],
}

QUALITY_GRAPH = {
    "vertices": [
        {"label": "quality_person", "properties": {"name": "marko", "age": 29}},
        {"label": "quality_software", "properties": {"name": "lop", "lang": "java"}},
    ],
    "edges": [
        {
            "label": "quality_created",
            "source": "marko",
            "target": "lop",
            "properties": {"date": "2026-05-31"},
        }
    ],
}

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

QUALITY_COMMIT_DATA = {
    "schema": QUALITY_COMMIT_SCHEMA,
    "vertices": [
        {"label": "quality_person", "properties": {"name": "marko", "age": 29}},
        {"label": "quality_software", "properties": {"name": "lop", "lang": "java"}},
    ],
    "edges": [
        {
            "label": "quality_created",
            "outV": "quality_person:marko",
            "inV": "quality_software:lop",
            "properties": {"date": "2026-05-31"},
        }
    ],
}


def _create_quality_schema(client):
    schema = client.schema()
    schema.propertyKey("name").asText().ifNotExist().create()
    schema.propertyKey("age").asInt().ifNotExist().create()
    schema.propertyKey("lang").asText().ifNotExist().create()
    schema.propertyKey("date").asText().ifNotExist().create()
    schema.vertexLabel("quality_person").properties("name", "age").primaryKeys("name").ifNotExist().create()
    schema.vertexLabel("quality_software").properties("name", "lang").primaryKeys("name").ifNotExist().create()
    schema.edgeLabel("quality_created").sourceLabel("quality_person").targetLabel("quality_software").properties(
        "date"
    ).ifNotExist().create()


def _commit_quality_graph():
    from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph

    commit = Commit2Graph()
    data = deepcopy(QUALITY_COMMIT_DATA)
    return commit.run(data)


def test_schema_manager_reads_real_schema(hugegraph_client, hugegraph_service):
    from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManager

    _create_quality_schema(hugegraph_client)

    manager = SchemaManager(graph_name=hugegraph_service.graph)
    context = manager.run({})

    assert "schema" in context
    assert "simple_schema" in context
    assert isinstance(context["schema"]["vertexlabels"], list)
    assert any(label["name"] == "quality_person" for label in context["schema"]["vertexlabels"])


def test_commit_to_graph_writes_vertices_and_edges(hugegraph_client):
    _commit_quality_graph()

    counts = hugegraph_client.gremlin().exec(
        """
        g.V().hasLabel('quality_person', 'quality_software').count()
        """
    )["data"][0]
    edges = hugegraph_client.gremlin().exec(
        """
        g.E().hasLabel('quality_created').
          project('out', 'in', 'date').
          by(outV().values('name')).
          by(inV().values('name')).
          by(values('date'))
        """
    )["data"]

    assert counts == 2
    assert len(edges) == 1
    assert edges[0]["out"] == "marko"
    assert edges[0]["in"] == "lop"
    assert edges[0]["date"] == "2026-05-31"


def test_fetch_graph_data_returns_counts_and_samples(hugegraph_client):
    from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData

    _commit_quality_graph()
    result = FetchGraphData(hugegraph_client).run({})

    assert {"vertex_num", "edge_num", "vertices", "edges", "note"}.issubset(result)
    assert result["vertex_num"] == 2
    assert result["edge_num"] == 1
    assert isinstance(result["vertices"], list)
    assert isinstance(result["edges"], list)


def test_gremlin_execute_surfaces_invalid_query(hugegraph_client):
    from hugegraph_llm.nodes.hugegraph_node.gremlin_execute import GremlinExecuteNode

    node = GremlinExecuteNode()
    node.wk_input = type("Input", (), {"requested_outputs": ["raw_execution_result"]})()
    result = node.operator_schedule({"raw_result": "g.V2()"})

    assert result["template_exec_res"] == ""
    assert (
        "g.V2" in result["raw_exec_res"]
        or "No signature" in result["raw_exec_res"]
        or "NotFound" in result["raw_exec_res"]
    )
