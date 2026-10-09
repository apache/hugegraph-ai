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
"""llm-ollama -- the platform LLM gateway backed by Ollama or an
OpenAI-compatible third-party endpoint.

The provider is selected at runtime: ``ollama`` (default) or ``external``.
Both satisfy the core ``ontogeny.llm.ChatClient`` contract and provide
``capability:llm`` when a base URL is configured.
"""
from .adapter import OllamaChat, OpenAICompatibleChat

__all__ = ["OllamaChat", "OpenAICompatibleChat", "register"]


def register(sc, host) -> None:
    """Provider phase: build the gateway from runtime settings, never from Git."""
    settings = sc.settings
    provider = (getattr(settings, "llm_provider", "ollama") or "ollama").lower()
    if provider in ("disabled", "none", "off"):
        return
    base_url = getattr(settings, "llm_base_url", None)
    if not base_url:
        return  # capability absent: every LLM consumer degrades explicitly
    http = getattr(sc, "llm_http", None)
    if provider == "external":
        client = OpenAICompatibleChat(
            base_url,
            getattr(settings, "llm_model", None) or "gpt-4o-mini",
            api_key=getattr(settings, "llm_api_key", None),
            http=http,
        )
    else:
        provider = "ollama"
        client = OllamaChat(
            base_url,
            getattr(settings, "llm_model", None) or "qwen3:27b",
            http=http,
        )
    sc.llm = client
    host.provide("capability:llm", {
        "extension": "llm-ollama",
        "provider": provider,
        "model": client.model,
        "base_url": client.base_url,
    })
