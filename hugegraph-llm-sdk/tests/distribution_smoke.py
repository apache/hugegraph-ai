# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run using an installed wheel, outside the repository, without pytest.

    /path/to/clean-venv/bin/python -B /path/to/distribution_smoke.py

No source directory is added to sys.path. Only the installed SDK and its base
dependencies may be available; the model is a caller-owned deterministic fake.
"""

import asyncio
import importlib.abc
import importlib.metadata
import importlib.util
import io
import json
import logging
import os
import socket
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

FORBIDDEN_IMPORTS = {
    "gradio",
    "fastapi",
    "pycgraph",
    "pyhugegraph",
    "hugegraph_llm",
    "hugegraph_llm_core",
    "hugegraph_llm_eval",
    "faiss",
    "langchain",
    "langchain_text_splitters",
    "nltk",
    "numpy",
    "pandas",
    "openai",
    "ollama",
    "litellm",
}


class DependencyBoundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in FORBIDDEN_IMPORTS:
            raise AssertionError(f"Core attempted to import an application or optional dependency: {fullname}")
        return None


def prevent_writes(event, args):
    if event == "open":
        _, mode, flags = args
        writable = isinstance(mode, str) and any(flag in mode for flag in "wax+")
        writable |= bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writable:
            raise AssertionError("Core attempted a filesystem write")
    if event in {"os.mkdir", "os.remove", "os.rename", "os.rmdir"}:
        raise AssertionError(f"Core attempted a filesystem mutation: {event}")
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("Core attempted network access")


def prevent_network(*args, **kwargs):
    raise AssertionError("Core attempted network access")


def scripted(*responses):
    remaining = iter(responses)

    def generate(prompt):
        assert isinstance(prompt, str) and prompt
        return next(remaining)

    return generate


def verify_archive(path: Path) -> None:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = [PurePosixPath(name) for name in archive.namelist()]
        required = PurePosixPath("hugegraph_llm_sdk/__init__.py")
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            names = [PurePosixPath(*PurePosixPath(name).parts[1:]) for name in archive.getnames()]
        required = PurePosixPath("src/hugegraph_llm_sdk/__init__.py")
    else:
        raise ValueError(f"unsupported distribution archive: {path}")
    assert required in names, f"{path.name} is missing {required}"
    for name in names:
        assert "hugegraph_llm_eval" not in name.parts, f"{path.name} bundles the eval import package: {name}"
        assert not name.parts or name.parts[0] != "eval", f"{path.name} bundles the nested eval project: {name}"


def verify_distribution():
    distribution = importlib.metadata.distribution("hugegraph-llm-sdk")
    assert distribution.metadata["Name"] == "hugegraph-llm-sdk"
    if os.environ.get("HUGEGRAPH_LLM_SDK_TEST_INSTALLED") != "1":
        return
    specification = importlib.util.find_spec("hugegraph_llm_sdk")
    installed_module = distribution.locate_file("hugegraph_llm_sdk/__init__.py")
    assert specification is not None and Path(specification.origin).resolve() == installed_module.resolve()
    assert importlib.util.find_spec("hugegraph_llm_core") is None, "The previous import name is still available"
    try:
        importlib.metadata.distribution("hugegraph-llm-core")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError("The previous distribution is still installed")


def run():
    sys.dont_write_bytecode = True
    verify_distribution()
    sys.meta_path.insert(0, DependencyBoundary())
    socket.create_connection = prevent_network
    socket.getaddrinfo = prevent_network
    sys.addaudithook(prevent_writes)

    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    previous_handlers = tuple(root.handlers)
    previous_level = root.level
    previous_environment = dict(os.environ)
    previous_files = set(Path.cwd().rglob("*"))

    from hugegraph_llm_sdk import (
        FunctionModel,
        adesign_schema,
        aextract_graph,
        design_schema,
        extract_graph,
        validate_schema,
    )

    schema = {
        "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
        "vertexlabels": [{"name": "person", "properties": ["name"], "primary_keys": ["name"], "nullable_keys": []}],
        "edgelabels": [],
    }
    draft = design_schema("Alice is a person.", model=FunctionModel(generate=scripted(json.dumps(schema))))
    assert draft.issues == []
    draft.schema["vertexlabels"][0]["name"] = "contact"
    assert validate_schema(draft.schema) == []
    graph = {
        "vertices": [{"id": "Alice", "label": "contact", "properties": {"name": "Alice"}}],
        "edges": [],
    }
    validated = []

    def business_rule(candidate, supplied_schema, text):
        assert supplied_schema == draft.schema and text == "Alice is a contact."
        validated.append(candidate["vertices"][0]["properties"]["name"])
        return []

    model = FunctionModel(generate=scripted(json.dumps(graph), json.dumps({"decision": "pass", "issues": []})))
    result = extract_graph("Alice is a contact.", schema=draft.schema, model=model, validators=[business_rule])
    assert result.status == "succeeded" and result.chunks[0].status == "final"
    assert result.graph["vertices"][0]["label"] == "contact" and validated == ["Alice"]

    async def async_flow():
        responses = iter([json.dumps(schema), json.dumps({"vertices": [], "edges": []})])

        async def generate(prompt):
            await asyncio.sleep(0)
            return next(responses)

        async_model = FunctionModel(agenerate=generate)
        async_draft = await adesign_schema("No people here.", model=async_model)
        assert async_draft.issues == []
        extracted = await aextract_graph("No people here.", schema=async_draft.schema, model=async_model, review=False)
        assert extracted.status == "succeeded" and extracted.chunks[0].status == "validated"

    asyncio.run(async_flow())
    assert tuple(root.handlers) == previous_handlers and root.level == previous_level
    assert dict(os.environ) == previous_environment
    assert set(Path.cwd().rglob("*")) == previous_files
    assert not (FORBIDDEN_IMPORTS & {name.partition(".")[0] for name in sys.modules})
    print("Independent wheel smoke passed: schema, extraction, async, and dependency isolation.")  # noqa: T201


if __name__ == "__main__":
    for archive_path in sys.argv[1:]:
        verify_archive(Path(archive_path))
    run()
