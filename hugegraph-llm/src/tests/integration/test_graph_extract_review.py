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

"""Execute the real HTTP -> Scheduler/pycgraph -> node -> extraction runtime chain.

Only the external LLM is replaced with deterministic responses. Inline schemas
exercise schema preparation without requiring a HugeGraph server.
"""

import json
import threading
from copy import deepcopy

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from openai.resources.chat.completions import Completions
from openai.types.chat import ChatCompletion

from hugegraph_llm.api.graph_extract_api import graph_extract_http_api
from hugegraph_llm.config import llm_settings
from hugegraph_llm.flows.scheduler import Scheduler, SchedulerSingleton

SCHEMA = {
    "vertexlabels": [
        {
            "id": 1,
            "name": "person",
            "id_strategy": "PRIMARY_KEY",
            "properties": ["name"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        }
    ],
    "edgelabels": [],
    "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
}
PASS = {"decision": "pass", "issues": []}
FIX = {"decision": "fix", "issues": [{"path": "vertices[0].properties.name", "message": "Wrong name"}]}
BLOCK = {"decision": "block", "issues": [{"path": "vertices", "message": "Unsupported by the text"}]}


def graph(name):
    return {"vertices": [{"id": f"1:{name}", "label": "person", "properties": {"name": name}}], "edges": []}


class ScriptedClients:
    """Give each chunk its own scripted client and record real generate calls."""

    def __init__(self, scripts, *, concurrent_chunks=0):
        self.scripts = scripts
        self.clients = []
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(concurrent_chunks) if concurrent_chunks else None
        self.active = 0
        self.peak = 0

    def __call__(self, _settings, *, limit_output=True, raise_on_truncation=False):
        assert raise_on_truncation is not limit_output
        owner = self

        class Client:
            def __init__(self):
                self.prompts = []
                self.token = None

            def generate(self, *, prompt):
                if self.token is None:
                    matches = [token for token in owner.scripts if token in prompt]
                    assert len(matches) == 1, "Each prompt must retain exactly one source chunk"
                    self.token = matches[0]
                self.prompts.append(prompt)
                with owner.lock:
                    owner.active += 1
                    owner.peak = max(owner.peak, owner.active)
                try:
                    if owner.barrier is not None and len(self.prompts) == 1:
                        owner.barrier.wait(timeout=10)
                    output = owner.scripts[self.token][len(self.prompts) - 1]
                    if isinstance(output, Exception):
                        raise output
                    return output if isinstance(output, str) else json.dumps(output)
                finally:
                    with owner.lock:
                        owner.active -= 1

        client = Client()
        with self.lock:
            self.clients.append(client)
        return client


@pytest.fixture
def client(monkeypatch):
    # Use the actual scheduler and its actual reusable pycgraph pipelines.
    monkeypatch.setattr(SchedulerSingleton, "_instance", Scheduler())
    router = APIRouter()
    graph_extract_http_api(router)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def install_llm(monkeypatch, scripts, *, concurrent_chunks=0):
    clients = ScriptedClients(scripts, concurrent_chunks=concurrent_chunks)
    monkeypatch.setattr("hugegraph_llm.nodes.llm_node.extract_info.get_chat_llm", clients)
    return clients


def post(client, texts, **kwargs):
    return client.post("/graph/extract", json={"texts": texts, "schema": SCHEMA, **kwargs})


def test_review_and_repair_run_concurrently_through_http_and_real_scheduler(client, monkeypatch):
    clients = install_llm(
        monkeypatch,
        {
            "integration_token_alpha": [graph("Alpha"), PASS],
            "integration_token_beta": [graph("Wrong"), FIX, graph("Beta"), PASS],
        },
        concurrent_chunks=2,
    )
    response = post(
        client,
        ["integration_token_alpha", "integration_token_beta"],
        review_options={"max_workers": 2},
        include_meta=True,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert [v["properties"]["name"] for v in data["result"]["vertices"]] == ["Alpha", "Beta"]
    assert [c["index"] for c in data["chunk_results"]] == [0, 1]
    assert [c["status"] for c in data["chunk_results"]] == ["final", "final"]
    assert [c["llm_calls"] for c in data["chunk_results"]] == [2, 4]
    assert [c["reviews_used"] for c in data["chunk_results"]] == [1, 2]
    assert [c["fixes_used"] for c in data["chunk_results"]] == [0, 1]
    assert data["chunk_results"][1]["issues"] == []
    assert data["meta"] == {"vertex_count": 2, "edge_count": 0, "text_count": 2}
    assert clients.peak == 2
    assert len(clients.clients) == 2
    beta = next(c for c in clients.clients if c.token == "integration_token_beta")
    assert "Wrong name" in beta.prompts[2]
    assert "Beta" in beta.prompts[3]


def test_partial_result_preserves_all_chunks_without_include_meta(client, monkeypatch):
    clients = install_llm(
        monkeypatch,
        {
            "integration_token_pass": [graph("Accepted"), PASS],
            "integration_token_candidate": [graph("Candidate"), FIX],
            "integration_token_block": [graph("Blocked"), BLOCK],
            "integration_token_fail": ["invalid json"],
        },
    )
    response = post(client, list(clients.scripts), review_options={"max_fixes": 0})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert [v["properties"]["name"] for v in data["result"]["vertices"]] == ["Accepted"]
    assert [c["status"] for c in data["chunk_results"]] == ["final", "candidate", "blocked", "failed"]
    assert data["chunk_results"][1]["graph"]["vertices"][0]["properties"]["name"] == "Candidate"
    assert data["chunk_results"][2]["issues"]
    assert data["chunk_results"][3]["reason"]
    assert data["meta"] == {}
    assert len(clients.clients) == 4


def test_invalid_edge_is_repaired_before_review_and_reaches_merged_result(client, monkeypatch):
    schema = SCHEMA | {
        "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "person", "properties": []}]
    }
    vertices = graph("Alice")["vertices"] + graph("Bob")["vertices"]
    edge = {
        "label": "knows",
        "outV": "1:Alice",
        "outVLabel": "person",
        "inV": "1:Bob",
        "inVLabel": "person",
        "properties": {},
    }
    clients = install_llm(
        monkeypatch,
        {
            "integration_token_edge": [
                {"vertices": vertices, "edges": [edge | {"inV": "1:Missing"}]},
                {"vertices": vertices, "edges": [edge]},
                PASS,
            ]
        },
    )
    response = post(client, "integration_token_edge", schema=schema, review_options={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert data["result"]["edges"][0]["inV"] == "1:Bob"
    result = data["chunk_results"][0]
    assert result["fixes_used"] == 1
    assert result["reviews_used"] == 1
    assert result["llm_calls"] == 3
    assert "1:Missing" in clients.clients[0].prompts[1]


@pytest.mark.parametrize(
    ("script", "options", "chunk_status"),
    [
        ([graph("Candidate")], {"max_reviews": 0}, "candidate"),
        ([graph("Blocked"), BLOCK], {}, "blocked"),
        ([RuntimeError("model unavailable")], {}, "failed"),
    ],
)
def test_no_final_chunks_returns_business_failure_with_http_200(client, monkeypatch, script, options, chunk_status):
    install_llm(monkeypatch, {"integration_token_nonfinal": script})
    response = post(client, "integration_token_nonfinal", review_options=options)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["result"] == {"vertices": [], "edges": []}
    assert data["chunk_results"][0]["status"] == chunk_status
    if chunk_status == "candidate":
        chunk = data["chunk_results"][0]
        assert chunk["graph"]["vertices"] == [graph("Candidate")["vertices"][0] | {"type": "vertex"}]
        assert chunk["graph"]["edges"] == []
        assert (chunk["reviews_used"], chunk["fixes_used"], chunk["llm_calls"]) == (0, 0, 1)
    assert data["warnings"] == []


def test_valid_empty_graph_can_pass_review(client, monkeypatch):
    install_llm(monkeypatch, {"integration_token_empty": [{"vertices": [], "edges": []}, PASS]})
    response = post(client, "integration_token_empty", review_options={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert data["chunk_results"][0]["status"] == "final"
    assert data["result"] == {"vertices": [], "edges": []}
    assert data["warnings"] == []


def test_pooled_pipeline_alternates_review_and_legacy_without_state_leaks(client, monkeypatch):
    clients = install_llm(
        monkeypatch,
        {
            "integration_token_review": [graph("Reviewed"), PASS],
            "integration_token_legacy": [graph("Legacy")],
            "integration_token_null": [graph("Null")],
            "integration_token_budget": [graph("Budget")],
        },
    )
    first = post(client, "integration_token_review", review_options={})
    assert first.status_code == 200
    assert first.json()["chunk_results"][0]["status"] == "final"

    for token, kwargs in [("integration_token_legacy", {}), ("integration_token_null", {"review_options": None})]:
        response = post(client, token, **kwargs)
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"status", "result", "warnings", "meta"}
        assert data["status"] == "succeeded"
        assert len(data["result"]["vertices"]) == 1
        assert data["result"]["vertices"][0]["properties"]["name"] != "Reviewed"

    last = post(client, "integration_token_budget", review_options={"max_reviews": 0})
    assert last.status_code == 200
    assert last.json()["status"] == "failed"
    assert last.json()["result"] == {"vertices": [], "edges": []}
    assert last.json()["chunk_results"][0]["reviews_used"] == 0
    assert len(clients.clients) == 4
    assert sorted(len(c.prompts) for c in clients.clients) == [1, 1, 1, 2]


def test_empty_sentence_split_is_request_failure_in_review_mode(client, monkeypatch):
    clients = install_llm(monkeypatch, {})
    response = post(client, ".!?", split_type="sentence", review_options={})

    assert response.status_code == 500
    assert clients.clients == []


def install_sdk_responses(monkeypatch, provider, steps):
    """Replace SDK responses while retaining the real factory/client/domain/engine."""
    monkeypatch.setattr(llm_settings, "chat_llm_type", provider)
    monkeypatch.setattr(llm_settings, f"{provider}_chat_api_key", "test-key")
    monkeypatch.setattr(llm_settings, f"{provider}_chat_api_base", "http://model.invalid/v1")
    monkeypatch.setattr(llm_settings, f"{provider}_chat_language_model", "test-model")
    monkeypatch.setattr(llm_settings, f"{provider}_chat_tokens", 37)
    steps = iter(steps)
    requests = []

    def completion(**kwargs):
        requests.append(kwargs)
        content, finish_reason = next(steps)
        return ChatCompletion(
            id="test-completion",
            created=1,
            model="test-model",
            object="chat.completion",
            choices=[
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content if isinstance(content, str) else json.dumps(content),
                    },
                    "finish_reason": finish_reason,
                }
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )

    if provider == "openai":
        monkeypatch.setattr(Completions, "create", lambda _self, **kwargs: completion(**kwargs))
    else:
        monkeypatch.setattr("hugegraph_llm.models.llms.litellm.completion", completion)
    return requests


@pytest.mark.parametrize("provider", ["openai", "litellm"])
@pytest.mark.parametrize(
    ("stage", "steps", "counts", "retained_name"),
    [
        ("extract", [(graph("Incomplete"), "length")], (0, 0, 1), None),
        ("review", [(graph("Original"), "stop"), (PASS, "length")], (1, 0, 2), "Original"),
        (
            "repair",
            [(graph("Original"), "stop"), (FIX, "stop"), (graph("Incomplete"), "length")],
            (1, 1, 3),
            "Original",
        ),
        (
            "review",
            [(graph("Original"), "stop"), (FIX, "stop"), (graph("Latest"), "stop"), (PASS, "length")],
            (2, 1, 4),
            "Latest",
        ),
    ],
)
def test_sdk_length_reason_reaches_http_with_latest_graph(
    client, monkeypatch, provider, stage, steps, counts, retained_name
):
    requests = install_sdk_responses(monkeypatch, provider, steps)
    response = post(client, "The graph should be reviewed.", review_options={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["result"] == {"vertices": [], "edges": []}
    result = data["chunk_results"][0]
    assert result["status"] == "failed"
    assert result["stage"] == stage
    assert result["reason"] == f"{stage}_output_truncated: finish_reason=length"
    assert (result["reviews_used"], result["fixes_used"], result["llm_calls"]) == counts
    if retained_name is None:
        assert result["graph"] is None
    else:
        assert result["graph"]["vertices"][0]["properties"]["name"] == retained_name
    if stage == "repair":
        assert result["issues"][0]["message"] == "Wrong name"
    assert len(requests) == counts[2]  # Truncation must not trigger a retry.
    assert all("max_tokens" not in request and "max_completion_tokens" not in request for request in requests)


@pytest.mark.parametrize("provider", ["openai", "litellm"])
def test_sdk_limit_is_preserved_for_legacy_but_omitted_for_reviewed_requests(client, monkeypatch, provider):
    requests = install_sdk_responses(
        monkeypatch,
        provider,
        [(graph("Legacy"), "stop"), (graph("Reviewed"), "stop"), (PASS, "stop")],
    )
    legacy = post(client, "Legacy extraction.")
    reviewed = post(client, "Reviewed extraction.", review_options={})

    assert legacy.status_code == reviewed.status_code == 200
    assert legacy.json()["status"] == reviewed.json()["status"] == "succeeded"
    assert "chunk_results" not in legacy.json()
    assert requests[0]["max_tokens"] == 37
    assert "max_tokens" not in requests[1]
    assert "max_tokens" not in requests[2]


@pytest.mark.parametrize("provider", ["openai", "litellm"])
@pytest.mark.parametrize("options", [{}, {"review_options": None}])
@pytest.mark.parametrize(
    ("truncated_content", "expected_names"),
    [(graph("Second"), ["First", "Second"]), ('{"vertices": [', ["First"])],
)
def test_legacy_http_preserves_prior_chunks_when_later_output_is_truncated(
    client, monkeypatch, provider, options, truncated_content, expected_names
):
    requests = install_sdk_responses(monkeypatch, provider, [(graph("First"), "stop"), (truncated_content, "length")])

    response = post(client, ["First chunk.", "Second chunk."], **options)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"status", "result", "warnings", "meta"}
    assert data["status"] == "succeeded"
    assert [vertex["properties"]["name"] for vertex in data["result"]["vertices"]] == expected_names
    assert data["result"]["edges"] == []
    assert len(requests) == 2
    assert all(request["max_tokens"] == 37 for request in requests)


@pytest.mark.parametrize("kind,invalid", [("id", 2**64 + 1), ("FLOAT", 1e100), ("FLOAT", -1e100)])
@pytest.mark.parametrize("include_accepted", [False, True])
def test_numeric_http_excludes_invalid_graphs_and_preserves_chunk_evidence(
    client, monkeypatch, kind, invalid, include_accepted
):
    schema = deepcopy(SCHEMA)
    accepted, rejected = graph("Accepted"), graph("Rejected")
    if kind == "id":
        schema["vertexlabels"][0]["id_strategy"] = "CUSTOMIZE_NUMBER"
        del schema["vertexlabels"][0]["primary_keys"]
        accepted["vertices"][0]["id"] = 7
        rejected["vertices"][0]["id"] = invalid
        issue_path = "vertices[0].id"
    else:
        schema["vertexlabels"][0]["properties"].append("value")
        schema["propertykeys"].append({"name": "value", "data_type": "FLOAT", "cardinality": "SINGLE"})
        accepted["vertices"][0]["properties"]["value"] = 1.1
        rejected["vertices"][0]["properties"]["value"] = invalid
        issue_path = "vertices[0].properties.value"
    scripts = {"integration_token_numeric_rejected": [rejected, PASS]}
    if include_accepted:
        scripts = {"integration_token_numeric_accepted": [accepted, PASS], **scripts}
    clients = install_llm(monkeypatch, scripts)

    response = post(client, list(scripts), schema=schema, review_options={"max_fixes": 0})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == ("partial" if include_accepted else "failed")
    assert data["result"] == {
        "vertices": [accepted["vertices"][0] | {"type": "vertex"}] if include_accepted else [],
        "edges": [],
    }
    chunk = data["chunk_results"][-1]
    assert chunk["status"] == "blocked" and chunk["reason"] == "validation_failed"
    assert chunk["graph"]["vertices"] == [rejected["vertices"][0] | {"type": "vertex"}]
    assert any(issue["path"] == issue_path for issue in chunk["issues"])
    assert (chunk["reviews_used"], chunk["fixes_used"], chunk["llm_calls"]) == (0, 0, 1)
    rejected_client = next(item for item in clients.clients if item.token == "integration_token_numeric_rejected")
    assert len(rejected_client.prompts) == 1


@pytest.mark.parametrize("data_type,value", [("FLOAT", 3.40282347e38), ("FLOAT", -1e-50), ("DOUBLE", 1e100)])
def test_numeric_http_preserves_accepted_rounding_underflow_and_double_values(client, monkeypatch, data_type, value):
    schema = deepcopy(SCHEMA)
    schema["vertexlabels"][0]["properties"].append("value")
    schema["propertykeys"].append({"name": "value", "data_type": data_type, "cardinality": "SINGLE"})
    extracted = graph("Accepted")
    extracted["vertices"][0]["properties"]["value"] = value
    install_llm(monkeypatch, {"integration_token_numeric_valid": [extracted, PASS]})

    response = post(client, "integration_token_numeric_valid", schema=schema, review_options={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert data["chunk_results"][0]["status"] == "final"
    assert data["result"]["vertices"] == [extracted["vertices"][0] | {"type": "vertex"}]
    assert data["chunk_results"][0]["graph"]["vertices"] == data["result"]["vertices"]


@pytest.mark.parametrize("kind", ["CUSTOMIZE_UUID", "FLOAT"])
def test_http_excludes_semantic_duplicate_identities_and_keeps_chunk_evidence(client, monkeypatch, kind):
    schema = deepcopy(SCHEMA)
    accepted = graph("Accepted")
    rejected = {"vertices": graph("First")["vertices"] + graph("Second")["vertices"], "edges": []}
    if kind == "CUSTOMIZE_UUID":
        schema["vertexlabels"][0]["id_strategy"] = kind
        schema["vertexlabels"][0].pop("primary_keys")
        accepted["vertices"][0]["id"] = "a8098c1a-f86e-11da-bd1a-00112444be1f"
        values = ["a8098c1a-f86e-11da-bd1a-00112444be1e", "A8098C1A-F86E-11DA-BD1A-00112444BE1E"]
        for vertex, value in zip(rejected["vertices"], values):
            vertex["id"] = value
        issue_path = "vertices[1].id"
    else:
        schema["vertexlabels"][0]["properties"].append("value")
        schema["vertexlabels"][0]["primary_keys"] = ["value"]
        schema["propertykeys"].append({"name": "value", "data_type": "FLOAT", "cardinality": "SINGLE"})
        accepted["vertices"][0]["properties"]["value"] = 2.0
        values = [1, 1.0]
        for vertex, value in zip(rejected["vertices"], values):
            vertex["properties"]["value"] = value
        issue_path = "vertices[1].properties"
    scripts = {
        "integration_token_identity_accepted": [accepted, PASS],
        "integration_token_identity_rejected": [rejected],
    }
    clients = install_llm(monkeypatch, scripts)

    response = post(client, list(scripts), schema=schema, review_options={"max_fixes": 0})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert [vertex["properties"]["name"] for vertex in data["result"]["vertices"]] == ["Accepted"]
    chunk = data["chunk_results"][1]
    assert chunk["status"] == "blocked" and chunk["reason"] == "validation_failed"
    assert (chunk["reviews_used"], chunk["fixes_used"], chunk["llm_calls"]) == (0, 0, 1)
    assert any(issue["path"] == issue_path for issue in chunk["issues"])
    actual = [
        vertex["id"] if kind == "CUSTOMIZE_UUID" else vertex["properties"]["value"]
        for vertex in chunk["graph"]["vertices"]
    ]
    assert json.dumps(actual) == json.dumps(values)
    rejected_client = next(item for item in clients.clients if item.token == "integration_token_identity_rejected")
    assert len(rejected_client.prompts) == 1
