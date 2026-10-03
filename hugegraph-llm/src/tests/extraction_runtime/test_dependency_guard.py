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

pytestmark = pytest.mark.contract


def test_runtime_has_no_forbidden_domain_or_host_imports() -> None:
    package = Path(__file__).parents[2] / "hugegraph_llm" / "extraction_runtime"
    forbidden = (
        "hugegraph_llm.api",
        "hugegraph_llm.car_graph_workflow",
        "hugegraph_llm.flows",
        "hugegraph_llm.nodes",
        "hugegraph_llm.operators",
        "pyhugegraph",
    )
    violations: list[str] = []

    for source in package.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(forbidden):
                    violations.append(f"{source.relative_to(package)} imports {name}")

    assert violations == []


def test_core_and_provider_do_not_import_the_inventory_conformance_domain() -> None:
    package = Path(__file__).parents[2] / "hugegraph_llm" / "extraction_runtime"
    violations: list[str] = []

    for subtree in (package / "v1", package / "provider"):
        for source in subtree.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                else:
                    names = []
                if any(name.startswith("hugegraph_llm.extraction_runtime.conformance") for name in names):
                    violations.append(str(source.relative_to(package)))

    assert violations == []
