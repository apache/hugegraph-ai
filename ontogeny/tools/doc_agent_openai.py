#!/usr/bin/env python3

# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Example external agent backed by any OpenAI-compatible chat endpoint.

It is deliberately a separate process: ontogeny has no model client in the
document path. Point the platform at it with

    ONTOGENY_DOC_AGENT_CMD="python tools/doc_agent_openai.py"
    OPENAI_BASE_URL=https://api.openai.com/v1
    OPENAI_API_KEY=...
    OPENAI_MODEL=gpt-4.1-mini

The response is validated by the platform (schema labels/keys, types, identity),
so a malformed model answer becomes a review candidate or a failed chunk, not
corrupt ontology data.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request


def _text(document: dict) -> str:
    if document.get("text"):
        return str(document["text"])
    raw = document.get("content_b64")
    if not raw:
        return ""
    return base64.b64decode(raw).decode("utf-8", "replace")


def _chat(prompt: str) -> str:
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    body = json.dumps(
        {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            "messages": [
                {"role": "system", "content": "You extract property graphs. Reply with JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.environ.get("OPENAI_TIMEOUT_S", "300"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"model HTTP {exc.code}: {exc.read()[:800]!r}") from exc
    return payload["choices"][0]["message"]["content"]


def main() -> int:
    request = json.load(sys.stdin)
    document = request.get("document") or {}
    text = _text(document)
    schema = json.dumps(request.get("schema") or {}, ensure_ascii=False)
    prompt = (
        f"{request.get('instructions', '')}\n\n"
        f"## Schema\n{schema}\n\n## Document ({document.get('name')})\n{text}\n\n"
        f"Return the chunks JSON now."
    )
    content = _chat(prompt)
    match = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    if match:
        content = match.group(1)
    parsed = json.loads(content)
    if "chunks" not in parsed:
        parsed = {"chunks": [{"doc_id": document.get("id"), "index": 0, "text": text, "graph": parsed, "issues": []}]}
    print(json.dumps(parsed, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
