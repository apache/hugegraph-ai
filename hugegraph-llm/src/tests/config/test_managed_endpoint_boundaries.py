# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.

"""Regression coverage for managed network targets and mounted dotenv files."""

import errno
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from dotenv import dotenv_values

from hugegraph_llm.config.hugegraph_config import HugeGraphConfig
from hugegraph_llm.config.index_config import IndexConfig
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config

pytestmark = pytest.mark.contract


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(path))
    prefixes = (
        "GRAPH_",
        "OPENAI_",
        "RERANKER_",
        "COHERE_",
        "CO_",
        "QDRANT_",
        "MILVUS_",
    )
    for name in list(os.environ):
        if name.startswith(prefixes):
            monkeypatch.delenv(name)
    return path


def test_bind_mounted_dotenv_falls_back_to_in_place_write(env_file, monkeypatch):
    env_file.write_text("LANGUAGE=EN\n", encoding="utf-8")
    env_file.chmod(0o640)
    settings = LLMConfig()
    settings.language = "CN"

    def busy_replace(*_args):
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(base_config.os, "replace", busy_replace)
    settings.update_env()

    assert dotenv_values(env_file) == {"LANGUAGE": "CN"}
    assert env_file.stat().st_mode & 0o777 == 0o640
    assert list(env_file.parent.glob(".env-*")) == []


def test_managed_graph_password_owns_endpoint_before_probe(env_file, monkeypatch):
    from hugegraph_llm.demo.rag_demo import configs_block

    env_file.write_text("GRAPH_URL=http://trusted.example:8080\n", encoding="utf-8")
    monkeypatch.setenv("GRAPH_PWD", "managed-graph-secret")
    settings = HugeGraphConfig()
    probe = Mock(return_value=200)
    monkeypatch.setattr(configs_block, "huge_settings", settings)
    monkeypatch.setattr(configs_block, "test_api_connection", probe)
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_args: None)
    before = settings.model_dump()

    assert settings.environment_source("graph_url") == "GRAPH_PWD"
    with pytest.raises(ValueError, match="managed by environment"):
        configs_block.apply_graph_config(
            "http://untrusted.example:8080",
            settings.graph_name,
            settings.graph_user,
            settings.graph_pwd,
            settings.graph_space,
        )

    probe.assert_not_called()
    assert settings.model_dump() == before
    assert env_file.read_text(encoding="utf-8") == "GRAPH_URL=http://trusted.example:8080\n"


def test_managed_reranker_key_owns_endpoint_before_probe(env_file, monkeypatch):
    from hugegraph_llm.demo.rag_demo import configs_block

    monkeypatch.setenv("RERANKER_API_KEY", "managed-reranker-secret")
    settings = LLMConfig(reranker_type="cohere")
    probe = Mock(return_value=200)
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    monkeypatch.setattr(configs_block, "test_api_connection", probe)
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_args: None)
    before = settings.model_dump()

    assert settings.environment_source("cohere_base_url") == "RERANKER_API_KEY"
    with pytest.raises(ValueError, match="managed by environment"):
        configs_block.apply_reranker_config(
            settings.reranker_api_key,
            "reranker-model",
            "https://untrusted.example/v1/rerank",
        )

    probe.assert_not_called()
    assert settings.model_dump() == before
    assert not env_file.exists()


def test_managed_qdrant_key_owns_target_before_client_creation(env_file, monkeypatch):
    from hugegraph_llm.demo.rag_demo import configs_block

    monkeypatch.setenv("QDRANT_API_KEY", "managed-qdrant-secret")
    settings = IndexConfig(qdrant_host="trusted.example", cur_vector_index="Qdrant")
    client = Mock(side_effect=AssertionError("Qdrant probe must not run"))
    module = ModuleType("qdrant_client")
    module.QdrantClient = client
    monkeypatch.setitem(sys.modules, "qdrant_client", module)
    monkeypatch.setattr(configs_block, "index_settings", settings)
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_args: None)
    before = settings.model_dump()

    assert settings.environment_source("qdrant_host") == "QDRANT_API_KEY"
    assert settings.environment_source("qdrant_port") == "QDRANT_API_KEY"
    with pytest.raises(ValueError, match="managed by environment"):
        configs_block.apply_vector_engine_backend(
            "Qdrant",
            host="untrusted.example",
            port=str(settings.qdrant_port),
            api_key=settings.qdrant_api_key,
        )

    client.assert_not_called()
    assert settings.model_dump() == before
    assert not env_file.exists()


def test_managed_milvus_password_owns_target_before_connect(env_file, monkeypatch):
    from hugegraph_llm.demo.rag_demo import configs_block

    monkeypatch.setenv("MILVUS_PASSWORD", "managed-milvus-secret")
    settings = IndexConfig(
        milvus_host="trusted.example",
        milvus_user="operator",
        cur_vector_index="Milvus",
    )
    connect = Mock(side_effect=AssertionError("Milvus probe must not run"))
    module = ModuleType("pymilvus")
    module.connections = SimpleNamespace(connect=connect, disconnect=Mock())
    module.utility = SimpleNamespace(list_collections=Mock())
    monkeypatch.setitem(sys.modules, "pymilvus", module)
    monkeypatch.setattr(configs_block, "index_settings", settings)
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_args: None)
    before = settings.model_dump()

    assert settings.environment_source("milvus_host") == "MILVUS_PASSWORD"
    assert settings.environment_source("milvus_port") == "MILVUS_PASSWORD"
    with pytest.raises(ValueError, match="managed by environment"):
        configs_block.apply_vector_engine_backend(
            "Milvus",
            host="untrusted.example",
            port=str(settings.milvus_port),
            user=settings.milvus_user,
            password=settings.milvus_password,
        )

    connect.assert_not_called()
    assert settings.model_dump() == before
    assert not env_file.exists()
