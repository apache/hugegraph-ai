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

"""Verify runtime model factories consume one complete configuration snapshot."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hugegraph_llm.models.embeddings import init_embedding
from hugegraph_llm.models.rerankers import init_reranker

pytestmark = pytest.mark.unit


def test_embedding_factory_uses_one_runtime_snapshot(monkeypatch):
    snapshot = SimpleNamespace(
        embedding_type="openai",
        openai_embedding_model="snapshot-model",
        openai_embedding_api_key="snapshot-key",
        openai_embedding_api_base="http://snapshot.invalid/v1",
    )
    snapshot_provider = Mock(return_value=snapshot)
    embedding = Mock()
    embedding.get_text_embedding.return_value = [0.1, 0.2, 0.3]
    constructor = Mock(return_value=embedding)
    monkeypatch.setattr(init_embedding, "snapshot_llm_settings", snapshot_provider)
    monkeypatch.setattr(init_embedding, "OpenAIEmbedding", constructor)

    result = init_embedding.Embeddings().get_embedding()

    assert result is embedding
    snapshot_provider.assert_called_once_with()
    constructor.assert_called_once_with(
        model_name="snapshot-model",
        api_key="snapshot-key",
        api_base="http://snapshot.invalid/v1",
    )
    assert embedding.embedding_dimension == 3


@pytest.mark.parametrize(
    ("provider", "factory_name", "expected"),
    [
        (
            "cohere",
            "CohereReranker",
            {
                "api_key": "snapshot-key",
                "base_url": "http://cohere.invalid/v1",
                "model": "snapshot-model",
            },
        ),
        (
            "siliconflow",
            "SiliconReranker",
            {"api_key": "snapshot-key", "model": "snapshot-model"},
        ),
    ],
)
def test_reranker_factory_uses_one_runtime_snapshot(monkeypatch, provider, factory_name, expected):
    snapshot = SimpleNamespace(
        reranker_type=provider,
        reranker_api_key="snapshot-key",
        cohere_base_url="http://cohere.invalid/v1",
        reranker_model="snapshot-model",
    )
    snapshot_provider = Mock(return_value=snapshot)
    client = object()
    constructor = Mock(return_value=client)
    monkeypatch.setattr(init_reranker, "snapshot_llm_settings", snapshot_provider)
    monkeypatch.setattr(init_reranker, factory_name, constructor)

    assert init_reranker.Rerankers().get_reranker() is client
    snapshot_provider.assert_called_once_with()
    constructor.assert_called_once_with(**expected)
