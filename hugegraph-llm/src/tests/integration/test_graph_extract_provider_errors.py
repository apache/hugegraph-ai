# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Provider failures cross the real client, runtime, scheduler and HTTP boundary."""

import json

import httpx
import ollama
import pytest
from openai import AuthenticationError, BadRequestError
from openai.resources.chat.completions import Completions
from openai.types.chat import ChatCompletion

from hugegraph_llm.config import llm_settings
from tests.integration.test_graph_extract_review import FIX, PASS, graph, post
from tests.integration.test_graph_extract_review import client as client

pytestmark = pytest.mark.contract


def install_sdk(monkeypatch, provider, steps):
    """Keep the real client factory and only control responses at the SDK boundary."""
    monkeypatch.setattr(llm_settings, "chat_llm_type", provider)
    if provider == "openai":
        monkeypatch.setattr(llm_settings, "openai_chat_api_key", "test-key")
        monkeypatch.setattr(llm_settings, "openai_chat_api_base", "http://model.invalid/v1")
        monkeypatch.setattr(llm_settings, "openai_chat_language_model", "test-model")
    else:
        monkeypatch.setattr(llm_settings, "ollama_chat_host", "model.invalid")
        monkeypatch.setattr(llm_settings, "ollama_chat_port", 11434)
        monkeypatch.setattr(llm_settings, "ollama_chat_language_model", "test-model")
    scripted = iter(steps)
    calls = []

    def respond(_self, **kwargs):
        calls.append(kwargs)
        step = next(scripted)
        if isinstance(step, Exception):
            raise step
        content, reason = step
        message = {"role": "assistant", "content": content if isinstance(content, str) else json.dumps(content)}
        if provider == "ollama/local":
            return ollama.ChatResponse(
                model="test-model", message=message, done=True, done_reason=reason, prompt_eval_count=10, eval_count=10
            )
        return ChatCompletion(
            id="test-completion",
            created=1,
            model="test-model",
            object="chat.completion",
            choices=[{"index": 0, "message": message, "finish_reason": reason}],
        )

    monkeypatch.setattr(
        Completions if provider == "openai" else ollama.Client, "create" if provider == "openai" else "chat", respond
    )
    return calls


@pytest.mark.parametrize("failure", ["ollama_length", "bad_request", "authentication"])
@pytest.mark.parametrize(
    ("stage", "prior_steps", "counts", "retained_name"),
    [
        ("extract", [], (0, 0, 1), None),
        ("review", [(graph("Original"), "stop")], (1, 0, 2), "Original"),
        ("repair", [(graph("Original"), "stop"), (FIX, "stop")], (1, 1, 3), "Original"),
        ("review", [(graph("Original"), "stop"), (FIX, "stop"), (graph("Latest"), "stop")], (2, 1, 4), "Latest"),
    ],
)
def test_provider_failure_reaches_http_with_stage_and_last_complete_graph(
    client, monkeypatch, failure, stage, prior_steps, counts, retained_name
):
    provider = "ollama/local" if failure == "ollama_length" else "openai"
    if failure == "ollama_length":
        # Even syntactically complete JSON must be rejected when the provider reports truncation.
        last_step = (PASS if stage == "review" else graph("Truncated"), "length")
        reason = f"{stage}_output_truncated: done_reason=length"
    else:
        error_type = BadRequestError if failure == "bad_request" else AuthenticationError
        last_step = error_type(
            "private provider response",
            response=httpx.Response(400, request=httpx.Request("POST", "https://model.invalid")),
            body=None,
        )
        reason = f"{stage}_failed: {error_type.__name__}"
    calls = install_sdk(monkeypatch, provider, [*prior_steps, last_step])

    response = post(client, "The graph should be reviewed.", review_options={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["result"] == {"vertices": [], "edges": []}
    result = data["chunk_results"][0]
    assert result["status"] == "failed"
    assert result["stage"] == stage
    assert result["reason"] == reason
    assert "JSONDecodeError" not in result["reason"]
    assert "private" not in json.dumps(data)
    assert (result["reviews_used"], result["fixes_used"], result["llm_calls"]) == counts
    if retained_name is None:
        assert result["graph"] is None
    else:
        assert result["graph"]["vertices"][0]["properties"]["name"] == retained_name
    if stage == "repair":
        assert result["issues"][0]["message"] == "Wrong name"
    assert len(calls) == counts[2]
    assert all(
        "max_tokens" not in call and "max_completion_tokens" not in call and "options" not in call for call in calls
    )


@pytest.mark.parametrize("options", [{}, {"review_options": None}])
@pytest.mark.parametrize(
    ("truncated_content", "expected_names"),
    [(graph("Second"), ["First", "Second"]), ('{"vertices": [', ["First"])],
)
def test_legacy_ollama_http_keeps_truncation_compatibility(
    client, monkeypatch, options, truncated_content, expected_names
):
    calls = install_sdk(monkeypatch, "ollama/local", [(graph("First"), "stop"), (truncated_content, "length")])
    response = post(client, ["First chunk.", "Second chunk."], **options)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert "chunk_results" not in data
    assert [vertex["properties"]["name"] for vertex in data["result"]["vertices"]] == expected_names
    assert len(calls) == 2


def test_ollama_http_accepts_complete_reviewed_graph(client, monkeypatch):
    calls = install_sdk(monkeypatch, "ollama/local", [(graph("Complete"), "stop"), (PASS, "stop")])
    response = post(client, "Complete graph.", review_options={})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert data["chunk_results"][0]["status"] == "final"
    assert data["result"]["vertices"] == [graph("Complete")["vertices"][0] | {"type": "vertex"}]
    assert data["result"]["edges"] == []
    assert len(calls) == 2
