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

"""Distinguish explicit vertex identities from keys added by inline schema preparation."""

import json
from copy import deepcopy

import pytest

from tests.integration import test_graph_extract_review as review_tests
from tests.integration.test_graph_extract_review import PASS, SCHEMA, install_llm, post

client = review_tests.client
TOKEN = "integration_token_custom_identity"
CUSTOM_IDS = [
    ("CUSTOMIZE_STRING", ["person1", "person2"]),
    ("CUSTOMIZE_NUMBER", [1, 2]),
    ("CUSTOMIZE_UUID", ["a8098c1a-f86e-11da-bd1a-00112444be1e", "a8098c1a-f86e-11da-bd1a-00112444be1f"]),
]


def inline_schema(strategy, *, nullable=False, data_type="TEXT"):
    schema = deepcopy(SCHEMA)
    definition = schema["vertexlabels"][0]
    definition.pop("primary_keys")
    if strategy is None:
        definition.pop("id_strategy")
    else:
        definition["id_strategy"] = strategy
    definition["nullable_keys"] = ["name"] if nullable else []
    schema["propertykeys"][0]["data_type"] = data_type
    return schema


def vertices(ids, properties):
    return {
        "vertices": [
            {"id": value, "label": "person", "properties": props} for value, props in zip(ids, properties, strict=False)
        ],
        "edges": [],
    }


@pytest.mark.parametrize(("strategy", "ids"), CUSTOM_IDS)
@pytest.mark.parametrize("case", ["same-name", "nullable-omitted", "date-properties"])
def test_custom_ids_ignore_synthesized_primary_keys(client, monkeypatch, strategy, ids, case):
    nullable = case == "nullable-omitted"
    schema = inline_schema(strategy, nullable=nullable, data_type="DATE" if case == "date-properties" else "TEXT")
    values = [0, "1970-01-01"] if case == "date-properties" else ["Alice", "Alice"]
    extracted = vertices(ids, [{} if nullable else {"name": value} for value in values])
    clients = install_llm(monkeypatch, {TOKEN: [extracted, PASS]})

    response = post(client, TOKEN, schema=schema, review_options={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    chunk = data["chunk_results"][0]
    assert chunk["status"] == "final" and chunk["issues"] == []
    assert (chunk["reviews_used"], chunk["fixes_used"], chunk["llm_calls"]) == (1, 0, 2)
    assert data["result"] == {
        "vertices": [vertex | {"type": "vertex"} for vertex in extracted["vertices"]],
        "edges": [],
    }
    review_context = json.loads(clients.clients[0].prompts[1].split("\n## Input\n")[1])
    prepared = review_context["schema"]["vertexlabels"][0]
    assert prepared["id_strategy"] == strategy
    assert prepared["primary_keys"] == ["name"]  # Exercise the real CheckSchema default.
    assert prepared["nullable_keys"] == (["name"] if nullable else [])
    assert len(clients.clients[0].prompts) == 2


@pytest.mark.parametrize(("strategy", "ids"), CUSTOM_IDS)
@pytest.mark.parametrize("problem", ["duplicate-id", "invalid-id", "required-property"])
def test_custom_ids_preserve_explicit_id_and_non_nullable_constraints(client, monkeypatch, strategy, ids, problem):
    schema = inline_schema(strategy)
    properties = [{"name": "Alice"}, {"name": "Bob"}]
    ids = list(ids)
    if problem == "duplicate-id":
        ids[1] = ids[0]
    elif problem == "invalid-id":
        ids[1] = "invalid" if strategy != "CUSTOMIZE_STRING" else 2
    else:
        properties[1] = {}
    extracted = vertices(ids, properties)
    clients = install_llm(monkeypatch, {TOKEN: [extracted, PASS]})

    response = post(client, TOKEN, schema=schema, review_options={"max_fixes": 0})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed" and data["result"] == {"vertices": [], "edges": []}
    chunk = data["chunk_results"][0]
    assert chunk["status"] == "blocked" and chunk["reason"] == "validation_failed"
    assert (chunk["reviews_used"], chunk["fixes_used"], chunk["llm_calls"]) == (0, 0, 1)
    assert chunk["graph"]["vertices"] == [vertex | {"type": "vertex"} for vertex in extracted["vertices"]]
    path = "vertices[1].properties.name" if problem == "required-property" else "vertices[1].id"
    assert any(issue["path"] == path for issue in chunk["issues"])
    assert len(clients.clients[0].prompts) == 1


@pytest.mark.parametrize("strategy", ["PRIMARY_KEY", None])
@pytest.mark.parametrize("problem", ["duplicate-key", "missing-key"])
def test_primary_key_constraints_remain_required_for_explicit_and_undeclared_strategies(
    client, monkeypatch, strategy, problem
):
    schema = inline_schema(strategy, nullable=True)
    properties = [{"name": "Alice"}, {"name": "Alice"}] if problem == "duplicate-key" else [{}]
    extracted = vertices(["person1", "person2"], properties)
    clients = install_llm(monkeypatch, {TOKEN: [extracted, PASS]})

    response = post(client, TOKEN, schema=schema, review_options={"max_fixes": 0})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed" and data["result"] == {"vertices": [], "edges": []}
    chunk = data["chunk_results"][0]
    assert chunk["status"] == "blocked" and chunk["reason"] == "validation_failed"
    expected = (
        ("vertices[1].properties", "Duplicate vertex primary key")
        if problem == "duplicate-key"
        else ("vertices[0].properties.name", "Required property is missing or empty")
    )
    assert expected in [(issue["path"], issue["message"]) for issue in chunk["issues"]]
    assert (chunk["reviews_used"], chunk["fixes_used"], chunk["llm_calls"]) == (0, 0, 1)
    assert len(clients.clients[0].prompts) == 1
