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

"""Helpers shared by Judge adapters that drive a locally installed agent CLI."""

import subprocess

from pydantic import BaseModel

from hugegraph_llm_eval.evaluation.judges.base import JudgeRequest, OutputT

_SCHEMA_KEYWORDS = frozenset({"items", "additionalProperties", "not", "if", "then", "else", "contains"})
_SCHEMA_LISTS = frozenset({"anyOf", "oneOf", "allOf", "prefixItems"})
_SCHEMA_MAPS = frozenset({"properties", "$defs", "definitions"})
_DROPPED = frozenset({"default", "title"})


def split_messages(request: JudgeRequest[OutputT]) -> tuple[str | None, str]:
    """Return the system text and the conversation text of a Judge request."""
    system = "\n\n".join(message.content for message in request.messages if message.role == "system")
    turns = [message for message in request.messages if message.role != "system"]
    if not turns:
        return None, system
    if len(turns) == 1 and turns[0].role == "user":
        return system or None, turns[0].content
    prompt = "\n\n".join(f"[{message.role}]\n{message.content}" for message in turns)
    return system or None, prompt


def strict_json_schema(response_type: type[BaseModel]) -> dict[str, object]:
    """Return the response schema in OpenAI strict mode: all properties required, no extras, no defaults."""
    schema = response_type.model_json_schema()
    _strictify(schema)
    return schema


def _strictify(node: dict[str, object]) -> None:
    if "$ref" in node:
        for key in [key for key in node if key not in ("$ref", "$defs", "definitions")]:
            del node[key]
    for key in _DROPPED:
        node.pop(key, None)
    properties = node.get("properties")
    if isinstance(properties, dict):
        node["required"] = list(properties)
        node["additionalProperties"] = False
    for key, value in list(node.items()):
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            for child in value.values():
                _strictify(child)
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            for child in value:
                _strictify(child)
        elif key in _SCHEMA_KEYWORDS and isinstance(value, dict):
            _strictify(value)


def token_count(raw: dict[str, object], key: str) -> int:
    """Read a non-negative integer token count, treating anything else as zero."""
    value = raw.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def cli_version(executable: str, *, timeout: float = 30.0) -> str:
    """Return the first line printed by ``<executable> --version``."""
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        msg = f"cannot find the {executable!r} executable; install it or pass its full path"
        raise RuntimeError(msg) from exc
    except subprocess.TimeoutExpired as exc:
        msg = f"{executable!r} --version did not finish within {timeout:g}s"
        raise RuntimeError(msg) from exc
    lines = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not lines:
        msg = f"{executable!r} --version failed with exit code {completed.returncode}"
        raise RuntimeError(msg)
    return lines[0].strip()
