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

from unittest.mock import Mock

from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient

from hugegraph_llm.api.rag_api import rag_http_api


def test_graph_config_api_passes_graph_field_to_apply_graph_conf():
    apply_graph_conf = Mock(return_value=status.HTTP_200_OK)
    router = APIRouter()
    rag_http_api(
        router,
        rag_answer_func=Mock(),
        graph_rag_recall_func=Mock(),
        apply_graph_conf=apply_graph_conf,
        apply_llm_conf=Mock(),
        apply_embedding_conf=Mock(),
        apply_reranker_conf=Mock(),
        gremlin_generate_selective_func=Mock(),
    )
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).post(
        "/config/graph",
        json={
            "url": "127.0.0.1:8080",
            "graph": "custom_graph",
            "user": "admin",
            "pwd": "secret",
            "gs": "space_a",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json() == {"message": "Connection successful. Configured finished."}
    apply_graph_conf.assert_called_once_with(
        "127.0.0.1:8080",
        "custom_graph",
        "admin",
        "secret",
        "space_a",
        origin_call="http",
    )
