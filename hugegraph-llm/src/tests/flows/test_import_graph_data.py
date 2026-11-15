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

"""Regression tests for ``ImportGraphDataFlow`` partial-import reporting.

Issue #373 / PR #422 review: when the server creates one vertex but rejects
another, the flow returned success without identifying the skipped vertex or
its dependent edges. The flow/API result must name both so callers can repair
their input.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from hugegraph_llm.flows.import_graph_data import ImportGraphDataFlow

pytestmark = [pytest.mark.contract]

SCHEMA = {
    "propertykeys": [
        {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
    ],
    "vertexlabels": [
        {"name": "person", "properties": ["name", "age"], "primary_keys": ["name"], "nullable_keys": ["age"]},
    ],
    "edgelabels": [
        {"name": "knows", "source_label": "person", "target_label": "person", "properties": ["role"]},
    ],
}

DATA = {
    "vertices": [
        {"label": "person", "properties": {"name": "Alice", "age": 30}},
        {"label": "person", "properties": {"name": "Bob", "age": 40}},
    ],
    "edges": [
        {"label": "knows", "properties": {"role": "coworker"}, "outV": "person:Alice", "inV": "person:Bob"},
    ],
}


def test_import_flow_reports_skipped_vertex_and_dependent_edges():
    """One created + one server-rejected vertex: the result names the vertex and its dependent edge."""
    mock_client = MagicMock()
    mock_client.graph.return_value.add_vertex.side_effect = [MagicMock(id=":1234"), None]

    with patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.PyHugeClient", return_value=mock_client):
        flow = ImportGraphDataFlow()
        pipeline = flow.build_flow(DATA, json.dumps(SCHEMA))
        assert not pipeline.init().isErr()
        assert not pipeline.run().isErr()
        result = json.loads(flow.post_deal(pipeline))

    summary = result["import_summary"]
    assert summary["imported_vertices"] == 1
    assert summary["imported_edges"] == 0
    assert summary["skipped_vertices"] == [{"id": "person:Bob", "reason": "server rejected the vertex"}]
    assert len(summary["skipped_edges"]) == 1
    skipped_edge = summary["skipped_edges"][0]
    assert (skipped_edge["label"], skipped_edge["outV"], skipped_edge["inV"]) == ("knows", "person:Alice", "person:Bob")
    assert "person:Bob" in skipped_edge["reason"]
