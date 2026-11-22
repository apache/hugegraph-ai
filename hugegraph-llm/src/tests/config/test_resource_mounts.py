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


"""Exercise deployment configuration through the real settings sources and files."""

import pytest
import yaml

from hugegraph_llm.config import paths
from hugegraph_llm.config.models import base_config, base_prompt_config


def test_resource_root_uses_assets_without_startup_copies(tmp_path, monkeypatch):
    from hugegraph_llm.config.models.base_prompt_config import resolve_prompt_yaml_path

    packaged = tmp_path / "packaged"
    (packaged / "demo").mkdir(parents=True)
    (packaged / "demo" / "example.txt").write_text("default")
    target = packaged / "data"
    monkeypatch.setattr(paths, "PACKAGED_RESOURCES", packaged)
    monkeypatch.setenv("HUGEGRAPH_LLM_RESOURCE_PATH", str(target))
    monkeypatch.delenv("HUGEGRAPH_LLM_ENV_PATH", raising=False)
    monkeypatch.delenv("HUGEGRAPH_LLM_PROMPT_CONFIG_PATH", raising=False)
    assert paths.resolve_resource_path() == target
    assert paths.resource_file("demo", "example.txt") == str(packaged / "demo" / "example.txt")
    assert not target.exists()
    assert base_config.resolve_env_path() == str(target / ".env")
    assert resolve_prompt_yaml_path() == str(target / "demo" / "config_prompt.yaml")
    (target / "demo").mkdir(parents=True)
    example = target / "demo" / "example.txt"
    example.write_text("user edit")
    assert paths.resource_file("demo", "example.txt") == str(example)


def test_missing_readonly_prompt_uses_memory_without_creating_files(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from hugegraph_llm.config.prompt_config import PromptConfig

    path = tmp_path / 'read-only' / 'config_prompt.yaml'
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(path))
    settings = PromptConfig(SimpleNamespace(language="EN"))
    settings.ensure_yaml_file_exists()
    assert settings.answer_prompt == settings.answer_prompt_EN
    assert not path.parent.exists()


@pytest.mark.contract
@pytest.mark.parametrize("contents", ["", "# No prompt overrides\n"], ids=["empty", "comments-only"])
def test_empty_prompt_file_uses_defaults_without_rewriting(tmp_path, monkeypatch, contents):
    from types import SimpleNamespace

    from hugegraph_llm.config.prompt_config import PromptConfig

    path = tmp_path / "config_prompt.yaml"
    path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(path))
    settings = PromptConfig(SimpleNamespace(language="EN"))

    settings.ensure_yaml_file_exists()

    assert settings.answer_prompt == settings.answer_prompt_EN
    assert settings.extract_graph_prompt == settings.extract_graph_prompt_EN
    assert path.read_bytes() == contents.encode("utf-8")


@pytest.mark.contract
def test_reload_empty_prompt_file_discards_saved_overrides(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from hugegraph_llm.config.prompt_config import PromptConfig

    path = tmp_path / "config_prompt.yaml"
    overrides = {
        "graph_schema": "custom schema",
        "review_graph_prompt": "custom review prompt",
        "repair_graph_prompt": "custom repair prompt",
        "graph_extract_split_type": "paragraph",
        "answer_prompt": "custom answer prompt",
    }
    path.write_text(yaml.safe_dump(overrides), encoding="utf-8")
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(path))
    settings = PromptConfig(SimpleNamespace(language="EN"))
    settings.ensure_yaml_file_exists()
    assert {key: getattr(settings, key) for key in overrides} == overrides

    path.write_bytes(b"")
    settings.ensure_yaml_file_exists()

    assert settings.graph_schema == PromptConfig.graph_schema
    assert settings.review_graph_prompt == PromptConfig.review_graph_prompt
    assert settings.repair_graph_prompt == PromptConfig.repair_graph_prompt
    assert settings.graph_extract_split_type == "document"
    assert settings.answer_prompt == PromptConfig.answer_prompt_EN
    assert path.read_bytes() == b""


def test_runtime_operators_read_bundled_assets_and_write_index_to_data_root(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock

    from hugegraph_llm.config.paths import PACKAGED_RESOURCES
    from hugegraph_llm.indices.vector_index import faiss_vector_store
    from hugegraph_llm.operators.index_op import gremlin_example_index_query
    from hugegraph_llm.operators.llm_op import prompt_generate

    root = tmp_path / 'fresh-data'
    monkeypatch.setattr(prompt_generate, "resource_path", str(root))
    examples = json.loads((PACKAGED_RESOURCES / 'prompt_examples' / 'prompt_examples.json').read_text())
    assert prompt_generate.PromptGenerate(Mock())._load_few_shot_example(examples[0]['name']) == examples[0]
    monkeypatch.setattr(gremlin_example_index_query, "resource_path", str(root))
    monkeypatch.setattr(faiss_vector_store, "resource_path", str(root))
    embedding = SimpleNamespace(
        get_embedding_dim=lambda: 2, get_texts_embeddings=lambda texts: [[float(i), 1.0] for i, _ in enumerate(texts)]
    )
    query = gremlin_example_index_query.GremlinExampleIndexQuery(
        faiss_vector_store.FaissVectorIndex, embedding=embedding
    )
    assert query.vector_index.index.ntotal > 0
    assert (root / 'gremlin_examples' / 'index.faiss').is_file()
    assert not (root / 'demo' / 'text2gremlin.csv').exists()
