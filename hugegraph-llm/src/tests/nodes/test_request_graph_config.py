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

from hugegraph_llm.config import huge_settings
from hugegraph_llm.nodes.hugegraph_node.commit_to_hugegraph import Commit2GraphNode
from hugegraph_llm.nodes.hugegraph_node.fetch_graph_data import FetchGraphDataNode
from hugegraph_llm.nodes.hugegraph_node.schema import SchemaNode
from hugegraph_llm.nodes.index_node.build_semantic_index import BuildSemanticIndexNode
from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManager
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.hugegraph_utils import get_hg_client

GRAPH_CONFIG = {
    "url": "127.0.0.1:8080",
    "graph": "custom_graph",
    "user": "admin",
    "pwd": "secret",
    "gs": "space_a",
}


def test_schema_node_passes_request_graph_config_to_schema_manager(monkeypatch):
    captured = {}

    class FakeSchemaManager:
        def __init__(self, graph_name, graph_config=None):
            captured["graph_name"] = graph_name
            captured["graph_config"] = graph_config

    monkeypatch.setattr("hugegraph_llm.nodes.hugegraph_node.schema.SchemaManager", FakeSchemaManager)
    node = SchemaNode()
    node.wk_input = WkFlowInput()
    node.wk_input.schema = "custom_graph"
    node.wk_input.graph_config = GRAPH_CONFIG
    node.context = WkFlowState()

    status = node.node_init()

    assert not status.isErr()
    assert captured == {"graph_name": "custom_graph", "graph_config": GRAPH_CONFIG}


def test_commit_node_passes_request_graph_config_to_commit_operator(monkeypatch):
    captured = {}

    class FakeCommit2Graph:
        def __init__(self, graph_config=None):
            captured["graph_config"] = graph_config

    monkeypatch.setattr("hugegraph_llm.nodes.hugegraph_node.commit_to_hugegraph.Commit2Graph", FakeCommit2Graph)
    node = Commit2GraphNode()
    node.wk_input = WkFlowInput()
    node.wk_input.graph_config = GRAPH_CONFIG
    node.context = WkFlowState()

    status = node.node_init()

    assert not status.isErr()
    assert captured == {"graph_config": GRAPH_CONFIG}


def test_fetch_graph_data_node_uses_request_graph_config(monkeypatch):
    captured = {}

    class FakeFetchGraphData:
        def __init__(self, client):
            captured["client"] = client

    monkeypatch.setattr("hugegraph_llm.nodes.hugegraph_node.fetch_graph_data.FetchGraphData", FakeFetchGraphData)
    monkeypatch.setattr(
        "hugegraph_llm.nodes.hugegraph_node.fetch_graph_data.get_hg_client",
        lambda graph_config=None: {"graph_config": graph_config},
    )
    node = FetchGraphDataNode()
    node.wk_input = WkFlowInput()
    node.wk_input.graph_config = GRAPH_CONFIG
    node.context = WkFlowState()

    status = node.node_init()

    assert not status.isErr()
    assert captured == {"client": {"graph_config": GRAPH_CONFIG}}


def test_build_semantic_index_node_uses_request_graph_config(monkeypatch):
    captured = {}

    class FakeEmbeddings:
        def get_embedding(self):
            return "embedding"

    class FakeBuildSemanticIndex:
        def __init__(self, embedding, vector_index, graph_config=None):
            captured["embedding"] = embedding
            captured["vector_index"] = vector_index
            captured["graph_config"] = graph_config

    monkeypatch.setattr("hugegraph_llm.nodes.index_node.build_semantic_index.Embeddings", FakeEmbeddings)
    monkeypatch.setattr("hugegraph_llm.utils.vector_index_utils.get_vector_index_class", lambda _: "vector-index")
    monkeypatch.setattr(
        "hugegraph_llm.nodes.index_node.build_semantic_index.BuildSemanticIndex",
        FakeBuildSemanticIndex,
    )
    node = BuildSemanticIndexNode()
    node.wk_input = WkFlowInput()
    node.wk_input.graph_config = GRAPH_CONFIG
    node.context = WkFlowState()

    status = node.node_init()

    assert not status.isErr()
    assert captured == {
        "embedding": "embedding",
        "vector_index": "vector-index",
        "graph_config": GRAPH_CONFIG,
    }


def test_schema_manager_connection_falls_back_for_missing_optional_fields(monkeypatch):
    captured = {}
    monkeypatch.setattr(huge_settings, "graph_url", "127.0.0.1:8080")
    monkeypatch.setattr(huge_settings, "graph_user", "admin")
    monkeypatch.setattr(huge_settings, "graph_pwd", "global-secret")
    monkeypatch.setattr(huge_settings, "graph_space", "global-space")

    class FakeHugeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def schema(self):
            return "schema-client"

    monkeypatch.setattr("hugegraph_llm.operators.hugegraph_op.schema_manager.PyHugeClient", FakeHugeClient)

    manager = SchemaManager("custom_graph", connection={"url": "10.0.0.1:8080", "user": None})

    assert manager.schema == "schema-client"
    assert captured == {
        "url": "10.0.0.1:8080",
        "graph": "custom_graph",
        "user": "admin",
        "pwd": "global-secret",
        "graphspace": "global-space",
    }


def test_get_hg_client_preserves_explicit_empty_graphspace(monkeypatch):
    captured = {}
    monkeypatch.setattr(huge_settings, "graph_url", "127.0.0.1:8080")
    monkeypatch.setattr(huge_settings, "graph_name", "global-graph")
    monkeypatch.setattr(huge_settings, "graph_user", "admin")
    monkeypatch.setattr(huge_settings, "graph_pwd", "secret")
    monkeypatch.setattr(huge_settings, "graph_space", "global-space")

    class FakeHugeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("hugegraph_llm.utils.hugegraph_utils.PyHugeClient", FakeHugeClient)

    get_hg_client({"graph": "custom_graph", "gs": ""})

    assert captured == {
        "url": "127.0.0.1:8080",
        "graph": "custom_graph",
        "user": "admin",
        "pwd": "secret",
        "graphspace": "",
    }
