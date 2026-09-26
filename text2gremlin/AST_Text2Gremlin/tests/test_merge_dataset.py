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

import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from llm_augment import merge_dataset
from llm_augment.merge_dataset import compute_crud_stats, guess_operation, load_from_migrated, load_from_translated


def test_guess_operation_classifies_common_gremlin_operations():
    assert guess_operation("g.addV('person').property('name', 'marko')") == "create"
    assert guess_operation("g.V().addE('knows').to(__.V().has('id', 1))") == "create"
    assert guess_operation("g.V().has('id', 1).property('name', 'josh')") == "update"
    assert guess_operation("g.V().has('id', 1).drop()") == "delete"
    assert guess_operation("g.V().hasLabel('person')") == "read"


def test_compute_crud_stats_fills_unknown_operations_in_place():
    pairs = [
        {"operation": "unknown", "gremlin": "g.V().hasLabel('person')"},
        {"operation": "", "gremlin": "g.V().has('id', 1).property('name', 'josh')"},
        {"operation": "delete", "gremlin": "g.V().has('id', 1).drop()"},
    ]

    stats = compute_crud_stats(pairs)

    assert stats == {"read": 1, "update": 1, "delete": 1}
    assert [pair["operation"] for pair in pairs] == ["read", "update", "delete"]


def test_main_exits_nonzero_when_required_inputs_are_missing(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "llm_augment.merge_dataset", "--output-dir", str(tmp_path)],
        cwd=PROJECT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "未找到 llm_translated" in result.stderr


def test_load_from_translated_skips_failed_items_and_preserves_metadata(tmp_path):
    metadata = {"source_id": "movie-001", "template": "vertex_scan"}
    translated_path = tmp_path / "translated.json"
    translated_path.write_text(
        json.dumps(
            {
                "corpus": [
                    {
                        "query": "g.V()",
                        "metadata": metadata,
                        "translations": [{"style": "zh_formal", "text": "查询所有顶点"}],
                    },
                    {
                        "query": "g.E()",
                        "metadata": {"source_id": "failed"},
                        "translations": [{"style": "zh_formal", "text": "查询所有边"}],
                        "_error": "translation failed",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    pairs = load_from_translated(str(translated_path))

    assert len(pairs) == 1
    assert pairs[0]["gremlin"] == "g.V()"
    assert pairs[0]["source_metadata"] == metadata


def test_load_from_migrated_preserves_source_metadata(tmp_path):
    source_metadata = {"source_id": "movie-002", "template": "migrate"}
    migrated_path = tmp_path / "migrated.json"
    migrated_path.write_text(
        json.dumps(
            {
                "migrations": [
                    {
                        "target_domain": "social",
                        "source_metadata": source_metadata,
                        "generated_samples": [
                            {
                                "query": "g.V().hasLabel('user')",
                                "natural_language": "Find all users",
                                "language_style": "en_formal",
                                "operation": "read",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    pairs = load_from_migrated(str(migrated_path))

    assert len(pairs) == 1
    assert pairs[0]["source_metadata"] == source_metadata


def test_main_output_corpus_preserves_source_metadata(tmp_path, monkeypatch):
    translated_metadata = {"source_id": "movie-003", "template": "translate"}
    migrated_metadata = {"source_id": "movie-004", "template": "migrate"}
    translated_path = tmp_path / "llm_translated.json"
    migrated_path = tmp_path / "migrated.json"
    output_dir = tmp_path / "out"
    translated_path.write_text(
        json.dumps(
            {
                "corpus": [
                    {
                        "query": "g.V()",
                        "metadata": translated_metadata,
                        "translations": [{"style": "zh_formal", "text": "查询所有顶点"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    migrated_path.write_text(
        json.dumps(
            {
                "migrations": [
                    {
                        "target_domain": "social",
                        "source_metadata": migrated_metadata,
                        "generated_samples": [
                            {
                                "query": "g.V().hasLabel('user')",
                                "natural_language": "Find all users",
                                "language_style": "en_formal",
                                "operation": "read",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "merge_dataset",
            "--translated",
            str(translated_path),
            "--migrated",
            str(migrated_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    merge_dataset.main()

    output_path = next(output_dir.glob("text2gremlin_dataset_*.json"))
    corpus = json.loads(output_path.read_text(encoding="utf-8"))["corpus"]
    assert [item["source_metadata"] for item in corpus] == [
        translated_metadata,
        migrated_metadata,
    ]
