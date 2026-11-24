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

from unittest.mock import MagicMock

import pytest

from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData

pytestmark = [pytest.mark.unit]


def _fetcher_with_pages(pages):
    client = MagicMock()
    graph_api = MagicMock()
    graph_api.list_vertices.side_effect = pages
    client.graph.return_value = graph_api
    return FetchGraphData(client), graph_api


def test_vid_scan_paginates_to_completion_and_accepts_zero_id():
    fetcher, graph_api = _fetcher_with_pages(
        [
            {"vertices": [{"id": 0}, {"id": "1:alice"}], "page": "p2"},
            {"vertices": [{"id": "1:bob"}], "page": None},
        ]
    )

    summary = fetcher.run({}, fetch_all_vids=True)

    assert summary["vertices"] == [0, "1:alice", "1:bob"]
    assert summary["vertex_num"] == 3
    assert summary["vid_scan_complete"] is True
    assert summary["vid_scan_incomplete_reason"] is None
    assert graph_api.list_vertices.call_count == 2


@pytest.mark.parametrize(
    ("pages", "expected_reason"),
    [
        (["not-a-dict"], "invalid_page_envelope"),
        ([{"page": None}], "invalid_vertices_page"),
        ([{"vertices": None, "page": None}], "invalid_vertices_page"),
        ([{"vertices": "bad", "page": None}], "invalid_vertices_page"),
        ([{"vertices": ["not-a-dict"], "page": None}], "invalid_vertex_id"),
        ([{"vertices": [{"label": "person"}], "page": None}], "invalid_vertex_id"),
        ([{"vertices": [{"id": None}], "page": None}], "invalid_vertex_id"),
        ([{"vertices": [{"id": True}], "page": None}], "invalid_vertex_id"),
        ([{"vertices": [{"id": ""}], "page": None}], "invalid_vertex_id"),
        ([{"vertices": [{"id": "   "}], "page": None}], "invalid_vertex_id"),
        ([{"vertices": [{"id": 1.5}]}], "invalid_vertex_id"),
        ([{"vertices": [{"id": 2**63}]}], "invalid_vertex_id"),
        ([{"vertices": [{"id": {}}]}], "invalid_vertex_id"),
        ([{"vertices": [{"id": "v1"}], "page": 123}], "invalid_page_token"),
        (
            [
                {"vertices": [{"id": "v1"}], "page": "p2"},
                {"vertices": [{"id": "v2"}], "page": "p2"},
            ],
            "duplicate_page_token",
        ),
    ],
)
def test_vid_scan_fails_incomplete_on_malformed_page_or_vertex_id(pages, expected_reason):
    fetcher, _ = _fetcher_with_pages(pages)

    summary = fetcher.run({}, fetch_all_vids=True)

    assert summary["vid_scan_complete"] is False
    assert summary["vid_scan_incomplete_reason"] == expected_reason


def test_overview_scan_marks_vid_scan_incomplete():
    client = MagicMock()
    client.gremlin.return_value.exec.return_value = {
        "data": [{"vertex_num": 2, "edge_num": 0, "vertices": ["v1", "v2"], "edges": [], "note": "overview"}]
    }
    fetcher = FetchGraphData(client)

    summary = fetcher.run({})

    assert summary["vid_scan_complete"] is False
    assert summary["vid_scan_incomplete_reason"] == "overview_limit_applied"
