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

# ruff: noqa: E402,I001

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from llm_augment import migrate_scenario
from llm_augment.migrate_scenario import (
    GeneratedSample,
    build_migration_prompt,
    filter_generated_samples,
    get_migration_config,
    infer_operation_type,
)


SIMPLE_SCHEMA = {
    "vertices": [{"label": "user", "properties": ["name"]}],
    "edges": [],
}


def test_same_operation_prompt_is_default_and_uses_configured_sample_count():
    config = get_migration_config({})

    assert config["migration_mode"] == "same_operation"
    assert config["same_operation_sample_count"] == 3

    prompt = build_migration_prompt(
        "Find all users",
        "g.V().hasLabel('user')",
        SIMPLE_SCHEMA,
        migration_mode=config["migration_mode"],
        sample_count=config["same_operation_sample_count"],
    )

    assert "生成 3 条样本" in prompt
    assert "只生成与原始 Gremlin 同类型的 read 操作" in prompt
    assert "2 条 read类型语句" not in prompt
    assert "1 条 create类型语句" not in prompt


def test_same_operation_prompt_uses_operation_matching_examples():
    create_prompt = build_migration_prompt(
        "Create a movie",
        "g.addV('movie').property('title', 'Dune')",
        SIMPLE_SCHEMA,
        migration_mode="same_operation",
    )
    update_prompt = build_migration_prompt(
        "Update a movie title",
        "g.V().hasLabel('movie').property('title', 'Dune 2')",
        SIMPLE_SCHEMA,
        migration_mode="same_operation",
    )
    delete_prompt = build_migration_prompt(
        "Delete a movie",
        "g.V().hasLabel('movie').drop()",
        SIMPLE_SCHEMA,
        migration_mode="same_operation",
    )

    assert '"operation": "create"' in create_prompt
    assert '"query": "g.addV' in create_prompt
    assert '"operation": "update"' in update_prompt
    assert ".property(" in update_prompt
    assert '"operation": "delete"' in delete_prompt
    assert ".drop()" in delete_prompt


def test_migration_config_can_override_mode_and_sample_count():
    config = get_migration_config(
        {
            "migration": {
                "migration_mode": "mixed_operations",
                "same_operation_sample_count": 5,
            }
        }
    )

    assert config["migration_mode"] == "mixed_operations"
    assert config["same_operation_sample_count"] == 5


def test_mixed_operations_prompt_keeps_crud_distribution_guidance():
    prompt = build_migration_prompt(
        "Find all users",
        "g.V().hasLabel('user')",
        SIMPLE_SCHEMA,
        migration_mode="mixed_operations",
        sample_count=3,
    )

    assert "2 条 read类型语句" in prompt
    assert "1 条 create类型语句" in prompt
    assert "1 条 update类型" in prompt
    assert "1 条 delete类型语句" in prompt


def test_infer_operation_type_from_gremlin():
    assert infer_operation_type("g.addV('person').property('name', 'marko')") == "create"
    assert infer_operation_type("g.V().has('id', 1).property('name', 'josh')") == "update"
    assert infer_operation_type("g.V().has('id', 1).drop()") == "delete"
    assert infer_operation_type("g.V().hasLabel('person')") == "read"


def test_same_operation_filter_rejects_mismatched_operation_and_query_type():
    samples = [
        GeneratedSample(
            operation="read",
            language_style="zh_formal",
            query="g.V().hasLabel('person')",
            natural_language="查询所有人",
        ),
        GeneratedSample(
            operation="create",
            language_style="zh_formal",
            query="g.addV('person')",
            natural_language="创建一个人",
        ),
        GeneratedSample(
            operation="read",
            language_style="zh_formal",
            query="g.V().hasLabel('person').drop()",
            natural_language="删除人",
        ),
    ]

    filtered = filter_generated_samples(samples, "read", "same_operation")

    assert len(filtered) == 1
    assert filtered[0]["query"] == "g.V().hasLabel('person')"


def test_prepare_pairs_persists_source_metadata(tmp_path, monkeypatch):
    metadata = {"source_id": "movie-001", "template": "vertex_scan"}
    translated_path = tmp_path / "translated.json"
    translated_path.write_text(
        json.dumps(
            {
                "corpus": [
                    {
                        "query": "g.V()",
                        "metadata": metadata,
                        "translations": [
                            {"style": "zh_formal", "text": "查询所有顶点"},
                            {"style": "en_formal", "text": "Find all vertices"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(migrate_scenario.random, "choice", lambda styles: styles[0])
    monkeypatch.setattr(migrate_scenario.random, "shuffle", lambda pairs: None)

    pairs_path, pairs = migrate_scenario.prepare_pairs(str(translated_path), str(tmp_path))

    assert pairs[0]["source_metadata"] == metadata
    saved_pairs = json.loads(Path(pairs_path).read_text(encoding="utf-8"))["pairs"]
    assert saved_pairs[0]["source_metadata"] == metadata


def test_fallback_migration_preserves_source_metadata():
    source_metadata = {"source_id": "movie-002", "template": "fallback"}

    result = migrate_scenario._fallback_migration(
        {"text": "查询所有顶点", "gremlin": "g.V()", "source_metadata": source_metadata},
        {"domain": "social", "name_zh": "社交", "schema": SIMPLE_SCHEMA},
        "boom",
    )

    assert result["source_metadata"] == source_metadata
    assert result["_error"] == "boom"


def test_migrate_one_preserves_source_metadata():
    source_metadata = {"source_id": "movie-003", "template": "migrate"}

    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "source_pattern": "start_vertex",
                                    "source_intent": "Find all vertices",
                                    "target_domain": "social",
                                    "mapping_explanation": "Map movie vertices to users",
                                    "generated_samples": [
                                        {
                                            "operation": "read",
                                            "language_style": "en_formal",
                                            "query": "g.V().hasLabel('user')",
                                            "natural_language": "Find all users",
                                        }
                                    ],
                                }
                            )
                        )
                    )
                ]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    result = asyncio.run(
        migrate_scenario.migrate_one(
            client,
            {
                "text": "Find all movies",
                "gremlin": "g.V().hasLabel('movie')",
                "source_metadata": source_metadata,
            },
            {"domain": "social", "name_zh": "社交", "schema": SIMPLE_SCHEMA},
            asyncio.Semaphore(1),
            {"model": "test", "temperature": 0, "max_retries": 1},
            {"migration_mode": "same_operation", "same_operation_sample_count": 1},
        )
    )

    assert result["source_metadata"] == source_metadata
    assert "_error" not in result


def test_migrate_one_retries_transient_generic_exception_and_preserves_source_metadata(monkeypatch):
    source_metadata = {"source_id": "movie-004", "template": "transient_retry"}

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        async def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary 503")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "source_pattern": "start_vertex",
                                    "source_intent": "Find all movies",
                                    "target_domain": "social",
                                    "mapping_explanation": "Map movie vertices to users",
                                    "generated_samples": [
                                        {
                                            "operation": "read",
                                            "language_style": "en_formal",
                                            "query": "g.V().hasLabel('user')",
                                            "natural_language": "Find all users",
                                        }
                                    ],
                                }
                            )
                        )
                    )
                ]
            )

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(migrate_scenario.asyncio, "sleep", no_sleep)
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = asyncio.run(
        migrate_scenario.migrate_one(
            client,
            {
                "text": "Find all movies",
                "gremlin": "g.V().hasLabel('movie')",
                "source_metadata": source_metadata,
            },
            {"domain": "social", "name_zh": "社交", "schema": SIMPLE_SCHEMA},
            asyncio.Semaphore(1),
            {"model": "test", "temperature": 0, "max_retries": 2, "timeout": 1},
            {"migration_mode": "same_operation", "same_operation_sample_count": 1},
        )
    )

    assert completions.calls == 2
    assert result["source_metadata"] == source_metadata
    assert result["generated_samples"][0]["query"] == "g.V().hasLabel('user')"
    assert "_error" not in result


def test_migrate_one_reports_timeout_error_after_retries_and_preserves_source_metadata(monkeypatch):
    source_metadata = {"source_id": "movie-005", "template": "timeout_retry"}

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        async def create(self, **_kwargs):
            self.calls += 1
            await asyncio.Event().wait()

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(migrate_scenario.asyncio, "sleep", no_sleep)
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = asyncio.run(
        migrate_scenario.migrate_one(
            client,
            {
                "text": "Find all movies",
                "gremlin": "g.V().hasLabel('movie')",
                "source_metadata": source_metadata,
            },
            {"domain": "social", "name_zh": "社交", "schema": SIMPLE_SCHEMA},
            asyncio.Semaphore(1),
            {"model": "test", "temperature": 0, "max_retries": 2, "timeout": 0.001},
            {"migration_mode": "same_operation", "same_operation_sample_count": 1},
        )
    )

    assert completions.calls == 2
    assert result["source_metadata"] == source_metadata
    assert result["generated_samples"] == []
    assert "_error" in result
    assert "TimeoutError" in result["_error"] or "timeout" in result["_error"].lower()
