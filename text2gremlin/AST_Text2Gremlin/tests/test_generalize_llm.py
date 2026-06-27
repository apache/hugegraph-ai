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

# ruff: noqa: E402

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from llm_augment import generalize_llm


def test_translation_prompt_has_complete_length_requirement():
    prompt = generalize_llm.build_translation_prompt(
        {"query": "g.V()", "description": "查询所有顶点"},
        [*generalize_llm.FIXED_STYLES, "mixed_lang", "abbreviated"],
    )

    assert "各风格表达方式要有明显差异，长度要自然" in prompt
    assert "各风格表达方式要有明显差异，长度\n" not in prompt
    assert "}\n```\n\n### 实际输入" in prompt


def test_translate_one_retries_transient_llm_exception(monkeypatch):
    monkeypatch.setattr(generalize_llm, "pick_random_styles", lambda n=2: ["mixed_lang", "abbreviated"])
    monkeypatch.setattr(generalize_llm.random, "random", lambda: 0)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(generalize_llm.asyncio, "sleep", no_sleep)

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        async def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary network error")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"zh_formal":"q1","zh_casual":"q2","en_formal":"q3",'
                                '"en_casual":"q4","mixed_lang":"q5","abbreviated":"q6"}'
                            )
                        )
                    )
                ]
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = asyncio.run(
        generalize_llm.translate_one(
            client,
            {"query": "g.V()", "description": "查询所有顶点"},
            asyncio.Semaphore(1),
            {"model": "test", "temperature": 0, "max_retries": 2, "timeout": 1},
        )
    )

    assert completions.calls == 2
    assert "_error" not in result
    assert len(result["translations"]) == 6


def test_translate_one_preserves_source_metadata(monkeypatch):
    monkeypatch.setattr(generalize_llm, "pick_random_styles", lambda n=2: ["mixed_lang", "abbreviated"])

    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"zh_formal":"q1","zh_casual":"q2","en_formal":"q3",'
                                '"en_casual":"q4","mixed_lang":"q5","abbreviated":"q6"}'
                            )
                        )
                    )
                ]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    metadata = {"source_id": "movie-001", "template": "vertex_scan"}

    result = asyncio.run(
        generalize_llm.translate_one(
            client,
            {"query": "g.V()", "description": "查询所有顶点", "metadata": metadata},
            asyncio.Semaphore(1),
            {"model": "test", "temperature": 0, "max_retries": 1, "timeout": 1},
        )
    )

    assert result["metadata"] == metadata


def test_fallback_result_preserves_metadata_and_error():
    metadata = {"source_id": "movie-002", "template": "fallback"}

    result = generalize_llm._fallback_result(
        {"query": "g.V()", "description": "查询所有顶点", "metadata": metadata},
        ["zh_formal"],
        error="boom",
    )

    assert result["metadata"] == metadata
    assert result["_error"] == "boom"
