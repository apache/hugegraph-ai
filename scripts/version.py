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

"""Synchronize release metadata from the root pyproject.toml (Python 3.12+)."""

import argparse
import difflib
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "hugegraph-llm-sdk",
    "graphrag/eval",
    "hugegraph-llm",
    "hugegraph-python-client",
    "hugegraph-mcp",
    "hugegraph-ml",
    "vermeer-python-client",
)
DOCS = (
    "hugegraph-mcp/README.md",
    "hugegraph-mcp/README.zh-CN.md",
    "hugegraph-mcp/docs/releasing.md",
    "hugegraph-llm/README.md",
    "hugegraph-mcp/docs/integration.md",
    "docs/quality/hugegraph-integration.md",
    "docs/quality/test-taxonomy.md",
    "hugegraph-llm-sdk/README.md",
    "graphrag/eval/README.md",
)
DEPLOYMENT = ("docker/docker-compose-network.yml",)
VERSION_PATTERN = r"\d+\.\d+\.\d+"


def release_config(root: Path) -> dict[str, str]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    config = {"version": data["project"]["version"], **data["tool"]["hugegraph"]["release"]}
    config.update(data["tool"]["hugegraph"]["ci"])
    for tool in ("ruff", "ty"):
        requirement = next(
            (value for value in data["project"]["optional-dependencies"]["dev"] if value.startswith(f"{tool}>=")),
            None,
        )
        if requirement is None:
            raise ValueError(f"Declare {tool} with >= in root project.optional-dependencies.dev")
        config[f"{tool}-version"] = requirement.split(">=", 1)[1]
    if not re.fullmatch(VERSION_PATTERN, config["version"]):
        raise ValueError("Root project.version must be a release version in x.y.z format")
    for key in ("server-image", "llm-image"):
        if not isinstance(config[key], str) or not re.fullmatch(r"[\w./:@-]+", config[key]):
            raise ValueError(f"Invalid {key} in root release configuration")
    return config


def replace_one(content: str, pattern: str, replacement: str, path: str) -> str:
    updated, count = re.subn(pattern, lambda match: match[1] + replacement + match[2], content, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"{path}: expected one release field matching {pattern!r}, found {count}")
    return updated


def updates(root: Path) -> dict[Path, tuple[str, str]]:
    """Compute every edit before writing anything; leave historical versions alone."""
    config = release_config(root)
    version = config["version"]
    result = {}
    compose = (root / DEPLOYMENT[0]).read_text(encoding="utf-8")
    previous_server = re.search(r"hugegraph-server:\n    image: (.+)", compose)
    previous_llm = re.search(r"hugegraph-rag:\n    image: (.+)", compose)
    if previous_server is None or previous_llm is None:
        raise ValueError("Compose must define server and LLM image references")
    # Read the previously synchronized references before computing deployment edits.
    server_ref = previous_server[1].removeprefix("${HUGEGRAPH_SERVER_IMAGE:-").removesuffix("}")

    def image_pattern(*references: str) -> str:
        repositories = set()
        for reference in references:
            repository = reference.split("@", 1)[0]
            if ":" in repository.rsplit("/", 1)[-1]:
                repository = repository.rsplit(":", 1)[0]
            repositories.add(repository)
        names = "|".join(re.escape(name) for name in sorted(repositories))
        return rf"(?<![\w./:@-])(?:{names})(?::[\w.-]+)?(?:@sha256:[a-fA-F0-9]{{64}})?(?![\w./:@-])"

    server_pattern = image_pattern("hugegraph/hugegraph", server_ref, config["server-image"])
    llm_pattern = image_pattern("hugegraph/rag", previous_llm[1], config["llm-image"])
    for module in MODULES:
        path = f"{module}/pyproject.toml"
        original = (root / path).read_text(encoding="utf-8")
        # Restrict the replacement to [project], rather than a tool's version field.
        updated = replace_one(original, r'(\[project\]\n(?:(?!\[).|\n)*?^version = ")[^"]+("[^\n]*)', version, path)
        dependencies = tomllib.loads(original)["project"].get("dependencies", [])
        if any(dependency.startswith("hugegraph-python>=") for dependency in dependencies):
            updated = replace_one(updated, r'("hugegraph-python>=)[^"<]+(<2")', version + ",", path)
        if module == "hugegraph-llm":
            updated = replace_one(updated, r'("hugegraph-llm-sdk==)[^"]+(")', version, path)
        if updated != original:
            result[root / path] = (original, updated)

    replacements = {
        DEPLOYMENT[0]: (
            (
                r"(  hugegraph-server:\n    image: )[^\n]+($)",
                "${HUGEGRAPH_SERVER_IMAGE:-" + config["server-image"] + "}",
            ),
            (r"(  hugegraph-rag:\n    image: )[^\n]+($)", f"{config['llm-image']}:{version}"),
        ),
    }
    for path, fields in replacements.items():
        original = (root / path).read_text(encoding="utf-8")
        updated = original
        for pattern, value in fields:
            updated = replace_one(updated, pattern, value, path)
        if updated != original:
            result[root / path] = (original, updated)

    # Only executable release examples are synchronized, never migration text,
    # minimum supported versions, protocol versions or recorded server evidence.
    for path in DOCS:
        original = (root / path).read_text(encoding="utf-8")
        updated = re.sub(rf"(?<=hugegraph-mcp@){VERSION_PATTERN}", version, original)
        updated = re.sub(rf"(?<=hugegraph_mcp-){VERSION_PATTERN}(?=-py3)", version, updated)
        updated = re.sub(rf"(?<=hugegraph_llm_sdk-){VERSION_PATTERN}(?=-py3)", version, updated)
        updated = re.sub(rf"(?<=hugegraph_llm_eval-){VERSION_PATTERN}(?=-py3)", version, updated)
        updated = re.sub(server_pattern, lambda _: config["server-image"], updated)
        updated = re.sub(llm_pattern, lambda _: f"{config['llm-image']}:{version}", updated)
        if updated != original:
            result[root / path] = (original, updated)
    return result


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "check", "get"))
    parser.add_argument("--root", type=Path, default=root, help="Project snapshot to read or synchronize")
    parser.add_argument(
        "key",
        nargs="?",
        choices=("version", "server-image", "llm-image", "uv-version", "python-version", "ruff-version", "ty-version"),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if (args.command == "get") != (args.key is not None):
        parser.error("get requires a key; sync/check do not accept a key")
    try:
        if args.command == "get":
            sys.stdout.write(release_config(root)[args.key] + "\n")
            return 0
        pending = updates(root)
        for path, (original, updated) in pending.items():
            relative = str(path.relative_to(root))
            if args.command == "sync":
                path.write_text(updated, encoding="utf-8")
                sys.stdout.write(f"Updated {relative}\n")
            else:
                sys.stdout.writelines(
                    difflib.unified_diff(original.splitlines(True), updated.splitlines(True), relative, relative)
                )
        if pending and args.command == "check":
            sys.stderr.write(
                'Release metadata is out of sync. Run: "${PYTHON_FOR_RELEASE:-python3}" scripts/version.py sync\n'
            )
            return 1
    except (KeyError, OSError, ValueError) as exc:
        sys.stderr.write(f"Release configuration error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
