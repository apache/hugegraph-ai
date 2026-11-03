# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Load application schema examples without depending on UI or global settings."""

import json
import logging
from pathlib import Path

from hugegraph_llm_sdk.schema import normalize_few_shot_schema_json, normalize_query_examples_json

log = logging.getLogger(__name__)


def _persisted_json(examples: str | None, label: str) -> str:
    examples = (examples or "").strip()
    if not examples:
        return ""
    try:
        json.loads(examples)
    except json.JSONDecodeError as exc:
        log.warning("Ignoring invalid persisted %s: %s", label, exc)
        return ""
    return examples


def load_query_examples(
    *, resource_path: str, persisted: str = "", language: str = "EN", fallback_resource_path: str | None = None
) -> str:
    """Prefer a saved override, then the language resource, then English examples."""
    saved = _persisted_json(persisted, "schema generator query examples")
    if saved:
        return normalize_query_examples_json(saved)

    directories = [Path(resource_path) / "prompt_examples"]
    if fallback_resource_path:
        directories.append(Path(fallback_resource_path) / "prompt_examples")
    names = ["query_examples_CN.json", "query_examples.json"] if language.upper() == "CN" else ["query_examples.json"]
    for directory in directories:
        for name in names:
            try:
                examples = json.loads((directory / name).read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            return normalize_query_examples_json(examples)
    return "[]"


def load_schema_fewshot_examples(
    *, resource_path: str, persisted: str = "", fallback_resource_path: str | None = None
) -> str:
    """Load a saved example schema or the application's bundled JSON example."""
    saved = _persisted_json(persisted, "schema generator few-shot examples")
    if saved:
        return normalize_few_shot_schema_json(saved)
    roots = [resource_path] + ([fallback_resource_path] if fallback_resource_path else [])
    for root in roots:
        try:
            examples = json.loads((Path(root) / "prompt_examples" / "schema_examples.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        return normalize_few_shot_schema_json(examples)
    return "[]"
