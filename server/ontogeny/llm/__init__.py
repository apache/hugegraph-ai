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
"""ontogeny.llm -- the platform LLM *contract*.

The core defines the interface every LLM adapter must satisfy plus the
deterministic JSON extraction helper; concrete adapters live OUTSIDE the core
in ``extensions/`` (``llm-ollama`` ships with the repo). The core never imports
an adapter: without a provider extension ``sc.llm`` is ``None`` and every LLM
consumer degrades explicitly (heuristic proposer, stub-driven agent evals,
denied sandbox capability).
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

from ..errors import OOError

__all__ = ["ChatClient", "LLMError", "extract_json"]


class LLMError(OOError):
    code = "LLM_ERROR"
    http_status = 502


class ChatClient(Protocol):
    """Structural contract for a platform LLM gateway.

    ``chat`` returns at least ``{"content": str}``; adapters may add
    ``thinking``/``model``/token fields. ``scoped`` returns a client pinned to
    another model name (used by the sandbox to honour a declared model
    override); ``health`` is a cheap liveness probe for /admin/llm/status.
    """

    model: str

    async def chat(self, messages: list[dict[str, str]], **kw: Any) -> dict[str, Any]: ...

    async def health(self) -> dict[str, Any]: ...

    def scoped(self, model: str) -> "ChatClient": ...


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Best-effort JSON extraction: fenced block -> first {...}/[...] span."""
    candidates: list[str] = []
    for m in _FENCE_RE.finditer(text):
        candidates.append(m.group(1).strip())
    # outermost braces/brackets span
    first_obj, first_arr = text.find("{"), text.find("[")
    starts = [p for p in (first_obj, first_arr) if p >= 0]
    if starts:
        start = min(starts)
        closer = "}" if text[start] == "{" else "]"
        end = text.rfind(closer)
        if end > start:
            candidates.append(text[start:end + 1])
    candidates.append(text.strip())
    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
    raise LLMError("model did not return parsable JSON", details={"text": text[:400]})
