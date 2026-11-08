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

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("ci", SCRIPTS / "ci.py")
assert spec is not None and spec.loader is not None
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class TestCISelection(unittest.TestCase):
    def assert_modules(self, paths, expected):
        selected = ci.select(paths)
        self.assertEqual(set(expected), {key for key in ci.MODULES if selected[key]})

    def test_multiline_config_does_not_write_any_ci_outputs(self):
        for separator in ("\n", "\r"):
            with self.subTest(separator=repr(separator)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                event = root / "event.json"
                event.write_text("{}")
                output = root / "output"
                output.write_text("existing=true\n")
                config = ci.release_config(ci.ROOT)
                config["uv-version"] += separator + "client=false"
                with (
                    patch.dict(
                        os.environ,
                        {
                            "GITHUB_EVENT_PATH": str(event),
                            "GITHUB_EVENT_NAME": "pull_request",
                            "GITHUB_REPOSITORY": "hugegraph/hugegraph-ai",
                            "GITHUB_OUTPUT": str(output),
                            "GITHUB_STEP_SUMMARY": str(root / "summary"),
                        },
                    ),
                    patch.object(ci, "changed_paths", return_value=["scripts/ci.py"]),
                    patch.object(ci, "codeql_provider", return_value="advanced-workflow"),
                    patch.object(ci, "release_config", return_value=config),
                    self.assertRaisesRegex(ValueError, "uv-version must be a single line"),
                ):
                    ci.main()
                self.assertEqual("existing=true\n", output.read_text())

    def test_repository_docs_skip_runtime_and_security_jobs(self):
        flags = ci.select(["README.md", "docs/quality/ci.md", "docs/design.rst"])
        self.assertFalse(any(flags.values()))

    def test_module_documentation_keeps_owning_contract_tests(self):
        for path in (
            "hugegraph-mcp/README.md",
            "hugegraph-mcp/README.zh-CN.md",
            "hugegraph-mcp/docs/integration.md",
        ):
            with self.subTest(path=path):
                self.assert_modules([path], {"mcp"})
                self.assertFalse(ci.select([path])["quality"])
                self.assertFalse(ci.select([path])["codeql"])

    def test_executable_and_json_examples_under_docs_are_not_skipped(self):
        example = "hugegraph-llm/docs/examples/reviewed_property_graph.py"
        self.assert_modules([example], {"llm"})
        self.assertTrue(ci.select([example])["quality"])
        self.assertTrue(ci.select([example])["codeql"])
        self.assert_modules(["hugegraph-llm/docs/examples/reviewed-extraction.json"], {"llm"})
        self.assertTrue(ci.select(["docs/examples/script.py"])["quality"])

    def test_python_prs_keep_codeql_without_github_default_setup(self):
        for path in ("hugegraph-mcp/hugegraph_mcp/server.py", "hugegraph-llm/pyproject.toml"):
            with self.subTest(path=path):
                selected = ci.select([path])
                self.assertTrue(selected["codeql"])
                with patch.object(ci.subprocess, "check_output", return_value='[{"workflows": []}]'):
                    self.assertEqual("advanced-workflow", ci.codeql_provider(selected, "apache/hugegraph-ai"))
                self.assertTrue(selected["codeql"])

    def test_client_changes_test_downstream_callers(self):
        self.assert_modules(["hugegraph-python-client/src/pyhugegraph/client.py"], {"client", "llm", "mcp"})

    def test_archive_exclusions_select_source_archive_installation_guard(self):
        self.assert_modules([".gitattributes"], {"client", "llm", "mcp"})

    def test_sdk_changes_keep_isolated_distribution_and_application_contracts(self):
        for path in (
            "hugegraph-llm-sdk/src/hugegraph_llm_sdk/api.py",
            "hugegraph-llm-sdk/README.md",
            "hugegraph-llm-sdk/examples/basic.py",
            ".github/workflows/hugegraph-llm-sdk.yml",
        ):
            with self.subTest(path=path):
                self.assert_modules([path], {"sdk", "llm"})

    def test_eval_changes_keep_isolated_distribution(self):
        for path in (
            "graphrag/eval/src/hugegraph_llm_eval/api.py",
            "graphrag/eval/README.md",
            ".github/workflows/hugegraph-llm-eval.yml",
        ):
            with self.subTest(path=path):
                self.assert_modules([path], {"eval"})

    def test_full_runtimes_cover_python_312_through_314(self):
        for module in ci.MODULES:
            with self.subTest(module=module):
                self.assertEqual(["3.12", "3.13", "3.14"], ci.FULL_PYTHONS[module])

    def test_module_changes_are_isolated(self):
        self.assert_modules(["hugegraph-llm/src/hugegraph_llm/config/hugegraph_config.py"], {"llm"})
        self.assert_modules(["hugegraph-mcp/tests/contracts/write_confirmation_v2.json"], {"mcp"})
        self.assert_modules(["docker/Dockerfile.llm"], {"llm"})
        self.assert_modules([".dockerignore"], {"llm"})

    def test_shared_config_and_workflows_do_not_skip_tests(self):
        for path in ("pyproject.toml", "scripts/ci.py", ".github/actions/setup-python-env/action.yml"):
            with self.subTest(path=path):
                self.assert_modules([path], {"client", "sdk", "eval", "llm", "mcp"})
        self.assert_modules([".github/workflows/hugegraph-llm.yml"], {"llm"})

    def test_dependency_review_requires_dependency_changes(self):
        self.assertFalse(ci.select(["hugegraph-mcp/hugegraph_mcp/server.py"])["dependencies"])
        self.assertTrue(ci.select(["hugegraph-mcp/pyproject.toml"])["dependencies"])

    def test_module_and_nested_pyprojects_always_select_quality(self):
        for path in (
            "hugegraph-llm/pyproject.toml",
            "hugegraph-llm-sdk/pyproject.toml",
            "graphrag/eval/pyproject.toml",
            "hugegraph-python-client/pyproject.toml",
            "hugegraph-mcp/pyproject.toml",
            "hugegraph-ml/pyproject.toml",
            "vermeer-python-client/pyproject.toml",
            "docs/example/pyproject.toml",
        ):
            with self.subTest(path=path):
                self.assertTrue(ci.select([path])["quality"])

    def test_full_and_on_demand_selections(self):
        self.assertTrue(all(ci.select([], full=True).values()))
        selected = ci.select([], test_set="codeql")
        self.assertEqual({"codeql"}, {key for key, value in selected.items() if value})

    def test_active_default_codeql_avoids_duplicate_advanced_scanner(self):
        selected = ci.select([], test_set="codeql")
        pages = [{"workflows": []}, {"workflows": [{"path": "dynamic/github-code-scanning/codeql", "state": "active"}]}]
        with patch.object(ci.subprocess, "check_output", return_value=json.dumps(pages)) as api:
            self.assertEqual("github-default-setup", ci.codeql_provider(selected, "hugegraph/hugegraph-ai"))
        self.assertFalse(selected["codeql"])
        self.assertIn("--paginate", api.call_args.args[0])

    def test_disabled_default_or_advanced_workflow_keeps_selected_scanner(self):
        for workflow in (
            {"path": "dynamic/github-code-scanning/codeql", "state": "disabled_manually"},
            {"path": ".github/workflows/codeql.yml", "state": "active"},
        ):
            selected = ci.select([], full=True)
            with patch.object(ci.subprocess, "check_output", return_value=json.dumps([{"workflows": [workflow]}])):
                self.assertEqual("advanced-workflow", ci.codeql_provider(selected, "hugegraph/hugegraph-ai"))
            self.assertTrue(selected["codeql"])

    def test_unselected_codeql_does_not_query_github(self):
        with patch.object(ci.subprocess, "check_output") as api:
            self.assertEqual("not-requested", ci.codeql_provider(ci.select(["README.md"]), "hugegraph/hugegraph-ai"))
            api.assert_not_called()

    def test_codeql_metadata_failures_are_not_silently_ignored(self):
        with (
            patch.object(ci.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, ["gh", "api"])),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            ci.codeql_provider(ci.select([], full=True), "hugegraph/hugegraph-ai")

    def test_deleted_and_renamed_files_are_selected_from_real_git_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args], text=True).strip()

            git("init", "-q")
            git("config", "user.email", "ci-test@example.invalid")
            git("config", "user.name", "CI Test")
            source = root / "hugegraph-python-client" / "client.py"
            source.parent.mkdir()
            source.write_text("original\n")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            git("mv", "hugegraph-python-client/client.py", "README.md")
            git("commit", "-qm", "move")
            original_run = ci.subprocess.run
            with patch.object(ci.subprocess, "run", side_effect=lambda *a, **kw: original_run(*a, cwd=root, **kw)):
                paths = ci.changed_paths({"before": base}, "push")
            self.assertIn("hugegraph-python-client/client.py", paths)
            self.assert_modules(paths, {"client", "llm", "mcp"})


if __name__ == "__main__":
    unittest.main()
