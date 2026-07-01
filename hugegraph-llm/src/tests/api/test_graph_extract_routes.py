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

from fastapi import APIRouter, FastAPI

from hugegraph_llm.api.graph_extract_api import graph_extract_http_api
from hugegraph_llm.api.rag_api import rag_http_api


def test_existing_routes_still_register():
    router = APIRouter()
    rag_http_api(
        router,
        rag_answer_func=Mock(),
        graph_rag_recall_func=Mock(),
        apply_graph_conf=Mock(),
        apply_llm_conf=Mock(),
        apply_embedding_conf=Mock(),
        apply_reranker_conf=Mock(),
        gremlin_generate_selective_func=Mock(),
    )
    graph_extract_http_api(router)
    app = FastAPI()
    app.include_router(router)

    openapi_paths = app.openapi()["paths"]
    paths = set(openapi_paths)
    assert "/rag" in paths
    assert "/text2gremlin" in paths
    assert "/config/graph" in paths
    assert "/graph/extract" in paths
    assert "/graph/extract/jobs" in paths
    assert "/graph/import" in paths
    assert "/graph/extract-and-import" in paths
    import_schema_ref = openapi_paths["/graph/import"]["post"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    extract_import_schema_ref = openapi_paths["/graph/extract-and-import"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert import_schema_ref.endswith("/GraphImportResponse")
    assert extract_import_schema_ref.endswith("/GraphExtractAndImportResponse")


def test_rag_demo_registers_graph_extract_routes_once(monkeypatch):
    from hugegraph_llm.demo.rag_demo import app as rag_demo_app

    monkeypatch.setattr(rag_demo_app.prompt, "update_yaml_file", lambda: None)
    monkeypatch.setattr(rag_demo_app, "init_rag_ui", lambda: object())
    monkeypatch.setattr(rag_demo_app.gr, "mount_gradio_app", lambda app, *args, **kwargs: app)

    app = rag_demo_app.create_app()

    graph_route_methods = [
        (path, method.upper())
        for path, path_item in app.openapi()["paths"].items()
        if path.startswith("/graph/")
        for method in path_item
        if method.upper() in {"GET", "POST", "DELETE"}
    ]
    assert len(graph_route_methods) == len(set(graph_route_methods))
    assert ("/graph/extract", "POST") in graph_route_methods
    assert ("/graph/extract/jobs", "POST") in graph_route_methods
    assert ("/graph/extract/jobs/{job_id}", "GET") in graph_route_methods
    assert ("/graph/extract/jobs/{job_id}", "DELETE") in graph_route_methods
    assert ("/graph/extract/jobs/{job_id}/result", "GET") in graph_route_methods
    assert ("/graph/import", "POST") in graph_route_methods
    assert ("/graph/extract-and-import", "POST") in graph_route_methods
