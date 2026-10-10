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
"""Ollama chat client (a pluggable LLM adapter implementing ontogeny.llm.ChatClient).

Talks to an Ollama /api/chat endpoint (stream=false); understands the
``thinking`` field emitted by reasoning models (qwen3 etc.). JSON extraction
is core-provided (ontogeny.llm.extract_json) so adapters only own transport.
"""
from __future__ import annotations

from typing import Any

import httpx

from ontogeny.llm import LLMError, extract_json  # core contract, never the reverse


class OllamaChat:
    def __init__(self, base_url: str, model: str, *, http: httpx.AsyncClient | None = None,
                 timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._http = http
        self.timeout = timeout

    async def client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def health(self) -> dict[str, Any]:
        """Cheap liveness probe against /api/tags."""
        c = await self.client()
        try:
            resp = await c.get(f"{self.base_url}/api/tags", timeout=5.0)
            return {"ok": resp.status_code == 200, "models": [m.get("name") for m in resp.json().get("models", [])]}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}

    async def chat(self, messages: list[dict[str, str]], *, think: bool = False,
                   options: dict[str, Any] | None = None) -> dict[str, Any]:
        c = await self.client()
        payload: dict[str, Any] = {"model": self.model, "stream": False, "messages": messages}
        if think:
            payload["think"] = True
        if options:
            payload["options"] = options
        try:
            resp = await c.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"ollama chat failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        message = data.get("message") or {}
        return {
            "content": message.get("content", ""),
            "thinking": message.get("thinking") or None,
            "model": data.get("model"),
            "eval_count": data.get("eval_count"),
        }

    async def chat_json(self, messages: list[dict[str, str]], **kw: Any) -> Any:
        """Chat expecting a JSON answer; tolerates fences and prose wrappers."""
        out = await self.chat(messages, **kw)
        return {"value": extract_json(out["content"]), "raw": out}

    def scoped(self, model: str) -> "OllamaChat":
        """Same gateway, another model name (sandbox model-override path);
        shares the transport, so nothing to close by the caller."""
        return OllamaChat(self.base_url, model, http=self._http, timeout=self.timeout)


class OpenAICompatibleChat:
    """Generic OpenAI-compatible /chat/completions client for external gateways."""

    def __init__(self, base_url: str, model: str, *, api_key: str | None = None,
                 http: httpx.AsyncClient | None = None, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or ""
        self._http = http
        self.timeout = timeout

    async def client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def health(self) -> dict[str, Any]:
        c = await self.client()
        try:
            resp = await c.get(f"{self.base_url}/models", headers=self._headers(), timeout=5.0)
            data = resp.json() if resp.status_code == 200 else {}
            return {"ok": resp.status_code == 200,
                    "models": [m.get("id") for m in data.get("data", []) if m.get("id")]}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}

    async def chat(self, messages: list[dict[str, str]], *, think: bool = False,
                   options: dict[str, Any] | None = None) -> dict[str, Any]:
        c = await self.client()
        payload: dict[str, Any] = {"model": self.model, "stream": False, "messages": messages}
        if options:
            payload.update(options)
        try:
            resp = await c.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            raise LLMError(f"openai-compatible endpoint unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"openai-compatible chat failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        return {
            "content": message.get("content", ""),
            "thinking": message.get("reasoning_content") or message.get("reasoning") or None,
            "model": data.get("model"),
            "eval_count": usage.get("completion_tokens"),
        }

    async def chat_json(self, messages: list[dict[str, str]], **kw: Any) -> Any:
        out = await self.chat(messages, **kw)
        return {"value": extract_json(out["content"]), "raw": out}

    def scoped(self, model: str) -> "OpenAICompatibleChat":
        return OpenAICompatibleChat(self.base_url, model, api_key=self.api_key,
                                    http=self._http, timeout=self.timeout)
