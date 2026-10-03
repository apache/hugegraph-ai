# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ast
from pathlib import Path

import pytest

from hugegraph_llm.api.models.graph_extract_requests import GraphExtractRequest
from hugegraph_llm.extraction_runtime.v1 import canonical_json
from hugegraph_llm.extraction_runtime.v1.fingerprint import RUNTIME_CONTRACT
from hugegraph_llm.extraction_runtime.v1.resources import load_runtime_contract_resource

pytestmark = pytest.mark.contract


def test_runtime_contract_resource_matches_implementation() -> None:
    resource = load_runtime_contract_resource()
    assert canonical_json(resource["runtime_contract"]) == canonical_json(RUNTIME_CONTRACT)
    assert resource["public_integration"] == "none"
    assert tuple(resource["terminal_kinds"]) == ("final", "candidate", "blocked", "failed")


def test_graph_extract_route_and_defaults_remain_unchanged() -> None:
    package = Path(__file__).parents[2] / "hugegraph_llm"
    source = (package / "api" / "graph_extract_api.py").read_text(encoding="utf-8")
    assert (
        '@router.post("/graph/extract", status_code=status.HTTP_200_OK, response_model=GraphExtractResponse)' in source
    )
    assert "/extraction-jobs" not in source

    request = GraphExtractRequest(texts="one bolt", schema={"vertexlabels": [], "edgelabels": []})
    assert request.extract_type == "property_graph"
    assert request.language == "zh"
    assert request.split_type == "document"
    assert request.include_meta is False


def test_existing_scheduler_still_owns_graph_extract_flow() -> None:
    package = Path(__file__).parents[2] / "hugegraph_llm"
    source = (package / "flows" / "scheduler.py").read_text(encoding="utf-8")
    assert "from hugegraph_llm.flows.graph_extract import GraphExtractFlow" in source
    assert "self.pipeline_pool[FlowName.GRAPH_EXTRACT]" in source
    assert '"flow": GraphExtractFlow()' in source


def test_production_modules_do_not_import_the_dormant_runtime() -> None:
    package = Path(__file__).parents[2] / "hugegraph_llm"
    violations: list[str] = []

    for source in package.rglob("*.py"):
        if "extraction_runtime" in source.relative_to(package).parts:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                names = []
            if any(name.startswith("hugegraph_llm.extraction_runtime") for name in names):
                violations.append(str(source.relative_to(package)))

    assert violations == []
