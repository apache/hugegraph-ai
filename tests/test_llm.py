# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Ollama adapter: parsing, JSON extraction, proposer wiring, assistant
endpoint; plus opt-in live integration (see TestLiveOllama)."""
from __future__ import annotations

import json
import os

import httpx
import pytest
import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.llm import LLMError, extract_json
from ontogeny_ext_ollama import OllamaChat
from ontogeny.evolve.proposer import DecidingProposer

# Every test in this module runs against MockTransport; the unit suite must be
# hermetic (no LAN endpoint, no model, no tokens). The LIVE tests at the bottom
# are the single exception and stay opt-in: they only run when the operator
# explicitly points the suite at a reachable endpoint via ONTOGENY_TEST_LIVE_LLM_URL.
OLLAMA_URL = "http://ollama.test:11434"  # never dialed; MockTransport intercepts
MODEL = os.environ.get("ONTOGENY_TEST_LIVE_LLM_MODEL", "qwen3.8:27b")


def _ollama_transport(payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


class TestOllamaChat:
    async def test_chat_parses_content_and_thinking(self):
        client = OllamaChat(OLLAMA_URL, MODEL, http=httpx.AsyncClient(transport=_ollama_transport({
            "model": MODEL, "message": {"role": "assistant", "content": "hello", "thinking": "hmm"},
            "done": True, "eval_count": 3,
        })))
        out = await client.chat([{"role": "user", "content": "hi"}])
        assert out["content"] == "hello" and out["thinking"] == "hmm" and out["eval_count"] == 3

    async def test_chat_unreachable_raises_llm_error(self):
        def boom(request):
            raise httpx.ConnectError("nope")

        client = OllamaChat("http://127.0.0.1:1", MODEL, http=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
        with pytest.raises(LLMError):
            await client.chat([{"role": "user", "content": "x"}])

    async def test_chat_json_tolerates_fences(self):
        client = OllamaChat(OLLAMA_URL, MODEL, http=httpx.AsyncClient(transport=_ollama_transport({
            "message": {"content": 'Sure!\n```json\n{"mutations": [{"mutation": "enum-widen"}], "rationale": "r"}\n```\nDone.'},
        })))
        out = await client.chat_json([{"role": "user", "content": "p"}])
        assert out["value"]["mutations"][0]["mutation"] == "enum-widen"


class TestExtractJson:
    def test_plain(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        assert extract_json('```json\n[1, 2]\n```') == [1, 2]

    def test_prose_wrapped(self):
        assert extract_json('answer: {"a": {"b": 2}} thanks') == {"a": {"b": 2}}

    def test_garbage_raises(self):
        with pytest.raises(LLMError):
            extract_json("no json here at all")


class TestDecidingProposerOverOllama:
    async def test_valid_output_accepted(self, golden_pkg_path):
        client = OllamaChat(OLLAMA_URL, MODEL, http=httpx.AsyncClient(transport=_ollama_transport({
            "message": {"content": json.dumps({
                "act": True, "analysis": "n/a",
                "mutations": [{"mutation": "add-optional-property", "object": "production-order",
                               "prop": "workgroup", "type": "string"}],
                "rationale": "filter evidence",
            })},
        })))
        proposer = DecidingProposer(client)
        from ontogeny.registry import compile_package

        from ontogeny.core import load_package
        pkg = load_package(golden_pkg_path)
        compiled = compile_package(pkg)
        out = await proposer.propose({"kind": "add-optional-property", "object": "production-order",
                                      "prop": "workgroup"}, compiled)
        assert out and out["origin"] == "llm" and out["mutations"][0]["prop"] == "workgroup"

    async def test_out_of_catalog_falls_back_or_declines(self, golden_pkg_path):
        client = OllamaChat(OLLAMA_URL, MODEL, http=httpx.AsyncClient(transport=_ollama_transport({
            "message": {"content": json.dumps({"act": True,
                                               "mutations": [{"mutation": "policy-loosen"}], "rationale": "x"})},
        })))
        proposer = DecidingProposer(client)
        from ontogeny.core import load_package
        from ontogeny.registry import compile_package

        compiled = compile_package(load_package(golden_pkg_path))
        # unknown gap kind: the heuristic fallback has no template either -> no proposal
        out = await proposer.propose({"kind": "x", "object": "production-order"}, compiled)
        assert out is None and proposer.stats["llm_rejected"] == 1


class TestAssistantEndpoint:
    @pytest_asyncio.fixture()
    async def client(self, golden_pkg_path, tmp_path):
        from ontogeny.api import build_app
        from ontogeny.service import ServiceContext

        ollama = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
            "message": {"role": "assistant",
                        "content": 'Use the ontology.\n```json\n{"mutations": [{"mutation": "add-optional-property", "object": "production-order", "prop": "wg", "type": "string"}], "rationale": "gap"}\n```'},
        })))
        settings = Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path/'a.db'}",
                            env={"ERP_DSN": "sqlite+aiosqlite:///:memory:"},
                            llm_base_url="http://ollama.test", llm_model=MODEL)
        sc = ServiceContext(settings, str(golden_pkg_path), llm_http=ollama)
        await sc.initialize()
        transport = httpx.ASGITransport(app=build_app(sc))
        import json as J
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     headers={"X-Ontogeny-Principal": J.dumps({"id": "ci-admin", "is_admin": True})}) as c:
            yield c, ollama
        await ollama.aclose()

    async def test_chat_grounding_and_proposals(self, client):
        c, _ = client
        r = await c.post("/api/v1/assistant/chat", json={
            "messages": [{"role": "user", "content": "Which properties does the production-order object have?"}],
            "propose": True,
        })
        assert r.status_code == 200
        body = r.json()
        assert "content" in body
        assert body["proposals"] and body["proposals"][0]["prop"] == "wg"

    async def test_llm_status(self, client):
        c, _ = client
        r = await c.get("/api/v1/admin/llm/status")
        assert r.status_code == 200 and r.json()["configured"] is True

    async def test_503_when_unconfigured(self, golden_pkg_path, tmp_path):
        from ontogeny.api import build_app
        from ontogeny.service import ServiceContext

        sc = ServiceContext(Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path/'b.db'}",
                                     env={"ERP_DSN": "sqlite+aiosqlite:///:memory:"}),
                            str(golden_pkg_path))
        await sc.initialize()
        transport = httpx.ASGITransport(app=build_app(sc))
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     headers={"X-Ontogeny-Principal": json.dumps({"id": "ci"})}) as c:
            r = await c.post("/api/v1/assistant/chat", json={"messages": []})
        assert r.status_code == 503


# ---------------------------------------------------------------- live tests


async def _ollama_reachable(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            resp = await c.get(f"{url}/api/tags")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


class TestLiveOllama:
    """Opt-in integration against a real Ollama endpoint.

    Disabled by default so the unit suite stays hermetic and reproducible.
    Enable by exporting ONTOGENY_TEST_LIVE_LLM_URL (the endpoint is still probed
    first; an unreachable one skips rather than fails):
        ONTOGENY_TEST_LIVE_LLM_URL=http://host:11434 uv run pytest tests/test_llm.py
    """

    URL = os.environ.get("ONTOGENY_TEST_LIVE_LLM_URL", "")

    async def test_live_chat(self):
        if not self.URL:
            pytest.skip("live LLM tests are opt-in (set ONTOGENY_TEST_LIVE_LLM_URL)")
        if not await _ollama_reachable(self.URL):
            pytest.skip("ollama endpoint unreachable")
        client = OllamaChat(self.URL, MODEL)
        out = await client.chat([{"role": "user", "content": "Reply with the single word: pong"}],
                                options={"num_predict": 64})
        assert out["content"].strip()

    async def test_live_deciding_proposer(self, golden_pkg_path):
        if not self.URL:
            pytest.skip("live LLM tests are opt-in (set ONTOGENY_TEST_LIVE_LLM_URL)")
        if not await _ollama_reachable(self.URL):
            pytest.skip("ollama endpoint unreachable")
        from ontogeny.core import load_package
        from ontogeny.registry import compile_package

        client = OllamaChat(self.URL, MODEL)
        proposer = DecidingProposer(client)
        compiled = compile_package(load_package(golden_pkg_path))
        gap = {"kind": "add-optional-property", "object": "production-order", "prop": "workgroup"}
        out = await proposer.propose(gap, compiled)
        # the live model decides; whatever it decides must be a valid catalog
        # mutation with a rationale, or an honest decline
        if out is None:
            assert proposer.stats["llm_declined"] + proposer.stats["llm_rejected"] >= 1
        else:
            assert out["mutations"][0]["mutation"] in ("add-optional-property", "enum-widen")
            assert out["rationale"]
