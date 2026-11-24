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

"""Preserve composite TEXT keys and endpoint aliases through the real HTTP flow."""

from copy import deepcopy

import pytest

from hugegraph_llm.extraction_runtime.property_graph import PropertyGraphBundle
from hugegraph_llm.extraction_runtime.review import ChunkInput
from tests.integration import test_graph_extract_review as review_tests
from tests.integration.test_graph_extract_review import PASS, install_llm, post

client = review_tests.client

SCHEMA = {
    "vertexlabels": [
        {
            "id": 1,
            "name": "person",
            "id_strategy": "PRIMARY_KEY",
            "properties": ["a", "b"],
            "primary_keys": ["a", "b"],
            "nullable_keys": [],
        }
    ],
    "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "person", "properties": []}],
    "propertykeys": [{"name": key, "data_type": "TEXT", "cardinality": "SINGLE"} for key in ("a", "b")],
}
TOKEN = "integration_token_composite_keys"
PAIRS = [
    (("foo!bar", "baz"), ("foo", "bar!baz"), ("1:foo`!bar!baz", "1:foo!bar`!baz")),
    (("foo:bar", "baz"), ("foo", "bar:baz"), ("1:foo`:bar!baz", "1:foo!bar`:baz")),
    (("foo`!bar", "baz`:qux"), ("foo`", "bar!baz:qux"), ("1:foo``!bar!baz``:qux", "1:foo`!bar`!baz`:qux")),
    (("foo", "bar"), ("foo", "baz"), ("1:foo!bar", "1:foo!baz")),
]


def extracted_graph(first, second, endpoint_style):
    vertices = [
        {"id": f"alias{index}", "label": "person", "properties": {"b": values[1], "a": values[0]}}
        for index, values in enumerate((first, second))
    ]
    edge = {"label": "knows", "properties": {}}
    if endpoint_style == "legacy":
        edge.update(
            {
                key: {"label": "person", "properties": vertex["properties"]}
                for key, vertex in zip(("source", "target"), vertices, strict=False)
            }
        )
    else:
        edge.update({"outV": "alias0", "outVLabel": "person", "inV": "alias1", "inVLabel": "person"})
    return {"vertices": vertices, "edges": [edge]}


@pytest.mark.parametrize("first,second,ids", PAIRS)
@pytest.mark.parametrize("endpoint_style", ["explicit", "canonical", "legacy"])
@pytest.mark.parametrize("reviewed", [False, True])
def test_http_preserves_distinct_composite_keys_and_endpoint_aliases(
    client, monkeypatch, first, second, ids, endpoint_style, reviewed
):
    extracted = extracted_graph(first, second, endpoint_style)
    if endpoint_style == "canonical":
        extracted["edges"][0].update(outV=ids[0], inV=ids[1])
    clients = install_llm(monkeypatch, {TOKEN: [extracted, PASS]})
    options = {"review_options": {"max_fixes": 0}} if reviewed else {}

    response = post(client, TOKEN, schema=SCHEMA, **options)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    expected = deepcopy(extracted)
    for vertex, vertex_id in zip(expected["vertices"], ids, strict=False):
        vertex.update(id=vertex_id, type="vertex")
    expected["edges"][0].update(type="edge", outV=ids[0], outVLabel="person", inV=ids[1], inVLabel="person")
    assert data["result"] == expected
    assert len(clients.clients[0].prompts) == (2 if reviewed else 1)
    if reviewed:
        chunk = data["chunk_results"][0]
        assert chunk["status"] == "final" and chunk["issues"] == []
        assert (chunk["reviews_used"], chunk["fixes_used"], chunk["llm_calls"]) == (1, 0, 2)
        # Revalidating canonical IDs must not add another escaping layer or lose endpoints.
        bundle = PropertyGraphBundle(llm=clients.clients[0], schema=SCHEMA)
        for _ in range(2):
            assert bundle.validate(data["result"], ChunkInput(0, TOKEN)) == []
            assert data["result"] == expected
    else:
        assert "chunk_results" not in data


@pytest.mark.parametrize(
    ("first", "second", "issue_message"),
    [
        (("foo!bar", "baz"), ("foo!bar", "baz"), "Duplicate vertex primary key"),
        # HugeGraph itself does not escape existing backticks. Preserve its collision guard.
        (("foo`", "bar!baz"), ("foo!bar`", "baz"), "Duplicate vertex id"),
    ],
)
def test_http_still_blocks_identical_server_composite_ids(client, monkeypatch, first, second, issue_message):
    extracted = extracted_graph(first, second, "explicit")
    clients = install_llm(monkeypatch, {TOKEN: [extracted, PASS]})

    response = post(client, TOKEN, schema=SCHEMA, review_options={"max_fixes": 0})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed" and data["result"] == {"vertices": [], "edges": []}
    chunk = data["chunk_results"][0]
    assert chunk["status"] == "blocked" and chunk["reason"] == "validation_failed"
    assert (chunk["reviews_used"], chunk["fixes_used"], chunk["llm_calls"]) == (0, 0, 1)
    assert [vertex["properties"] for vertex in chunk["graph"]["vertices"]] == [
        vertex["properties"] for vertex in extracted["vertices"]
    ]
    assert any(issue_message in issue["message"] for issue in chunk["issues"])
    assert len(clients.clients[0].prompts) == 1
