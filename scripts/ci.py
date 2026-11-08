#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Select affected CI suites; share the preflight runner and configuration."""

import json
import os
import subprocess
from pathlib import Path

from version import release_config

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "client": "hugegraph-python-client",
    "sdk": "hugegraph-llm-sdk",
    "eval": "graphrag/eval",
    "llm": "hugegraph-llm",
    "mcp": "hugegraph-mcp",
}
WORKFLOWS = {
    "client": "hugegraph-python-client.yml",
    "sdk": "hugegraph-llm-sdk.yml",
    "eval": "hugegraph-llm-eval.yml",
    "llm": "hugegraph-llm.yml",
    "mcp": "hugegraph-mcp.yml",
}
FULL_PYTHONS = {
    "client": ["3.12", "3.13", "3.14"],
    "sdk": ["3.12", "3.13", "3.14"],
    "eval": ["3.12", "3.13", "3.14"],
    "llm": ["3.12", "3.13", "3.14"],
    "mcp": ["3.12", "3.13", "3.14"],
}
SHARED = {
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/ci.yml",
    "scripts/ci.py",
    "scripts/version.py",
    "scripts/check_hugegraph.sh",
}


def select(paths: list[str], *, full: bool = False, test_set: str = "mainline") -> dict[str, bool]:
    flags = dict.fromkeys((*MODULES, "quality", "dependencies", "codeql", "license"), False)
    if full:
        return dict.fromkeys(flags, True)
    if test_set in ("codeql", "dependencies"):
        flags[test_set] = True
        return flags
    for path in paths:
        is_pyproject = Path(path).name == "pyproject.toml"
        is_documentation = Path(path).suffix.lower() in (".md", ".rst")
        # Module documentation/examples are inputs to contract tests too.
        in_module = any(path.startswith(module + "/") for module in MODULES.values())
        if is_documentation and not in_module:
            continue
        if not is_documentation:
            flags["license"] = True
        if path == ".gitattributes":
            flags["client"] = True  # Owns the source-archive build/install guard.
        if path in SHARED or path.startswith(".github/actions/"):
            for key in (*MODULES, "quality"):
                flags[key] = True
        for key, module in MODULES.items():
            if path.startswith(module + "/") or path == f".github/workflows/{WORKFLOWS[key]}":
                flags[key] = True
        if path == ".dockerignore" or path.startswith("docker/") or path == "scripts/build_llm_image.sh":
            flags["llm"] = True
        if (
            is_pyproject
            or path.endswith((".py", ".pyi"))
            or path in (".pre-commit-config.yaml", ".github/workflows/ruff.yml")
        ):
            flags["quality"] = True
        if path.endswith((".py", ".pyi")):
            flags["codeql"] = True
        if Path(path).name in ("pyproject.toml", "uv.lock") or Path(path).name.startswith("requirements"):
            flags["dependencies"] = True
            flags["codeql"] = True
        if path == ".github/workflows/codeql.yml":
            flags["codeql"] = True
        if path == ".github/workflows/check-dependencies.yml":
            flags["dependencies"] = True
    if flags["client"]:
        flags["llm"] = flags["mcp"] = True
    if flags["sdk"]:
        flags["llm"] = True
    return flags


def changed_paths(event: dict, event_name: str) -> list[str]:
    base = event["pull_request"]["base"]["sha"] if event_name == "pull_request" else event.get("before")
    if not base or set(base) == {"0"}:
        # Manual/new-branch runs validate the current tree instead of guessing.
        result = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
    else:
        # Include both sides of renames, and fail rather than silently skip on a bad diff.
        result = subprocess.run(
            ["git", "diff", "--no-renames", "--name-only", "-z", base, "HEAD"], check=True, capture_output=True
        )
    return [path for path in result.stdout.decode().split("\0") if path]


def codeql_provider(selected: dict[str, bool], repository: str) -> str:
    """Keep GitHub default setup as the single scanner when it is active."""
    if not selected["codeql"]:
        return "not-requested"
    # Unlike code-scanning settings, workflow metadata only requires actions:read.
    # Paginate so the default workflow cannot be missed in a large repository.
    raw = subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", f"repos/{repository}/actions/workflows?per_page=100"],
        text=True,
    )
    pages = json.loads(raw)
    if not isinstance(pages, list) or not pages:
        raise ValueError("Invalid GitHub workflow metadata while selecting CodeQL provider")
    for page in pages:
        for workflow in page["workflows"]:
            if workflow["path"] == "dynamic/github-code-scanning/codeql" and workflow["state"] == "active":
                selected["codeql"] = False
                return "github-default-setup"
    return "advanced-workflow"


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    event_name = os.environ["GITHUB_EVENT_NAME"]
    test_set = os.environ.get("TEST_SET", "mainline")
    full = (
        event_name == "schedule"
        or test_set == "full"
        or (event_name == "push" and os.environ.get("GITHUB_REF", "").startswith("refs/heads/release-"))
    )
    paths = changed_paths(event, event_name)
    selected = select(paths, full=full, test_set=test_set)
    provider = codeql_provider(selected, os.environ["GITHUB_REPOSITORY"])
    config = release_config(ROOT)
    outputs = {key: str(value).lower() for key, value in selected.items()}
    outputs.update(config)
    outputs["full"] = str(full).lower()
    for key in MODULES:
        outputs[key + "-pythons"] = json.dumps(FULL_PYTHONS[key] if full else [config["python-version"]])
    for key, value in outputs.items():
        if "\n" in str(value) or "\r" in str(value):
            raise ValueError(f"Output {key} must be a single line")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        for key, value in outputs.items():
            stream.write(f"{key}={value}\n")
    summary = json.dumps(
        {"full": full, "codeql_provider": provider, "suites": selected, "changed_files": paths}, indent=2
    )
    Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(f"### CI selection\n\n```json\n{summary}\n```\n")


if __name__ == "__main__":
    main()
