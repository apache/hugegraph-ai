#!/usr/bin/env python3

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

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "docker" / "Dockerfile.nk"


class RagBinDockerfileContractTest(unittest.TestCase):
    """Protect the dependency, build-output, and runtime contracts of rag-bin."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load Dockerfile, ignore rules, and workspace metadata once."""

        cls.dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        cls.dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        cls.gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        cls.config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        cls.llm_config = tomllib.loads((ROOT / "hugegraph-llm" / "pyproject.toml").read_text(encoding="utf-8"))
        cls.lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    @staticmethod
    def _active_patterns(content: str) -> set[str]:
        """Return active non-comment patterns from an ignore file."""

        return {line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")}

    def _local_package_directories(self) -> set[str]:
        """Return workspace members and explicit local path dependencies."""

        tool_uv = self.config["tool"]["uv"]
        packages = set(tool_uv["workspace"]["members"])
        for source in tool_uv["sources"].values():
            if isinstance(source, dict) and isinstance(source.get("path"), str):
                packages.add(source["path"].rstrip("/"))
        return packages

    def test_buildkit_frontend_is_explicit(self) -> None:
        """Require the frontend used by cache and secret mounts."""

        self.assertTrue(
            self.dockerfile.startswith("# syntax=docker/dockerfile:1\n"),
            "BuildKit cache and secret mounts require an explicit frontend",
        )
        self.assertIn("--mount=type=cache,target=/root/.cache/uv", self.dockerfile)
        self.assertIn("--mount=type=secret,id=proxy_ca", self.dockerfile)

    def test_build_uses_the_committed_workspace_lockfile(self) -> None:
        """Make warm and cold image builds consume the same dependency graph."""

        docker_ignored = self._active_patterns(self.dockerignore)
        git_ignored = self._active_patterns(self.gitignore)

        self.assertTrue((ROOT / "uv.lock").is_file())
        self.assertNotIn("uv.lock", docker_ignored)
        self.assertNotIn("uv.lock", git_ignored)
        self.assertIn("COPY pyproject.toml uv.lock README.md ./", self.dockerfile)
        self.assertIn("uv sync --locked --no-install-workspace --extra nk-llm", self.dockerfile)
        self.assertNotIn("uv sync --no-install-workspace --extra nk-llm", self.dockerfile)
        self.assertGreaterEqual(self.dockerfile.count("uv sync --locked"), 2)

    def test_gradio_is_locked_to_a_published_wheel(self) -> None:
        """Use a published Gradio package that includes the built frontend."""

        self.assertNotIn("gradio", self.llm_config["tool"]["uv"]["sources"])
        gradio = [package for package in self.lock["package"] if package["name"] == "gradio"]
        self.assertEqual(1, len(gradio))
        self.assertEqual({"registry": "https://pypi.org/simple"}, gradio[0]["source"])
        self.assertTrue(gradio[0]["wheels"], "Gradio must have a published wheel with frontend assets")

    def test_filelock_security_constraint_is_locked(self) -> None:
        """Keep local-lock consumers above the first fully patched release."""

        self.assertIn("filelock>=4.2.1", self.config["tool"]["uv"]["constraint-dependencies"])
        versions = [package["version"] for package in self.lock["package"] if package["name"] == "filelock"]
        self.assertEqual(1, len(versions))
        self.assertGreaterEqual(tuple(map(int, versions[0].split("."))), (4, 2, 1))

    def test_dependency_layer_copies_all_local_package_metadata(self) -> None:
        """Keep workspace/path dependencies complete when the project grows."""

        for package in sorted(self._local_package_directories()):
            with self.subTest(package=package):
                expected = f"COPY {package}/pyproject.toml {package}/README.md ./{package}/"
                self.assertIn(expected, self.dockerfile)

    def test_uv_version_matches_ci_configuration(self) -> None:
        """Keep the image builder aligned with the repository CI toolchain."""

        expected = self.config["tool"]["hugegraph"]["ci"]["uv-version"]
        match = re.search(r"^ARG UV_VERSION=(\S+)$", self.dockerfile, re.MULTILINE)

        if match is None:
            self.fail("Dockerfile.nk must declare ARG UV_VERSION")
        self.assertEqual(expected, match.group(1))
        self.assertIn('pip install --no-cache-dir "uv==${UV_VERSION}"', self.dockerfile)

    def test_dependencies_form_a_reusable_layer(self) -> None:
        """Install locked third-party dependencies before source invalidation."""

        metadata_copy = self.dockerfile.index("COPY pyproject.toml uv.lock README.md ./")
        dependency_sync = self.dockerfile.index("uv sync --locked --no-install-workspace --extra nk-llm")
        source_copy = self.dockerfile.index("COPY . .")
        workspace_sync = self.dockerfile.index("uv sync --locked --extra nk-llm")

        self.assertLess(metadata_copy, dependency_sync)
        self.assertLess(dependency_sync, source_copy)
        self.assertLess(source_copy, workspace_sync)
        self.assertGreaterEqual(
            self.dockerfile.count("--mount=type=cache,target=/root/.cache/uv"),
            2,
        )

    def test_build_tracks_the_current_main_nuitka_scope(self) -> None:
        """Prevent retired compatibility patches from returning during rebases."""

        self.assertNotIn("patch_litellm_nuitka.py", self.dockerfile)
        self.assertNotIn("litellm.litellm_core_utils.tokenizers", self.dockerfile)
        self.assertIn(
            "--include-package-data=safehttpx,groovy,gradio,jieba",
            self.dockerfile,
        )
        self.assertIn(
            "--include-module=hugegraph_llm.demo.rag_demo.app",
            self.dockerfile,
        )

    def test_build_context_excludes_local_nuitka_outputs(self) -> None:
        """Exclude generated compiler outputs from the source context."""

        docker_ignored = self._active_patterns(self.dockerignore)

        for pattern in (
            "**/app.build/",
            "**/app.dist/",
            "**/app.onefile-build/",
        ):
            self.assertIn(pattern, docker_ignored)

    def test_runtime_excludes_nuitka_build_intermediates(self) -> None:
        """Copy the standalone app without compiler work directories."""

        runtime = self.dockerfile.split("# Stage 2: Runtime stage", maxsplit=1)[1]

        self.assertIn("mv app.dist ..", self.dockerfile)
        self.assertNotIn("mv app.*", self.dockerfile)
        self.assertIn("rm -rf app.build app.onefile-build", self.dockerfile)
        self.assertNotIn("app.build", runtime)
        self.assertNotIn("pyproject.toml", runtime)
        self.assertIn(
            "COPY --from=builder --chown=work:work /build/hugegraph-llm/app.dist",
            runtime,
        )

    def test_runtime_interface_remains_compatible(self) -> None:
        """Preserve the resources volume and public application command."""

        self.assertIn(
            'VOLUME ["/home/work/hugegraph-llm/src/hugegraph_llm/resources"]',
            self.dockerfile,
        )
        self.assertIn(
            'CMD ["./app.dist/app.bin", "--host", "0.0.0.0", "--port", "8001"]',
            self.dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
