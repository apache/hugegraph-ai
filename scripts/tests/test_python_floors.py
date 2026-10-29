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

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PythonFloorContractTest(unittest.TestCase):
    def test_ontogeny_uses_python_312_throughout(self) -> None:
        config = tomllib.loads((ROOT / "ontogeny" / "pyproject.toml").read_text(encoding="utf-8"))
        root_config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(">=3.12", config["project"]["requires-python"])
        self.assertIn("Programming Language :: Python :: 3.12", config["project"]["classifiers"])
        self.assertNotIn("per-file-target-version", root_config["tool"]["ruff"])
        dockerfile = (ROOT / "ontogeny" / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM python:3.12-slim", dockerfile)
        workflow = (ROOT / ".github" / "workflows" / "ontogeny-ci.yml").read_text(encoding="utf-8")
        self.assertEqual(2, workflow.count('python-version: "3.12"'))
        self.assertNotIn('python-version: "3.10"', workflow)

    def test_standalone_ml_matches_client_python_floor(self) -> None:
        ml_config = tomllib.loads((ROOT / "hugegraph-ml" / "pyproject.toml").read_text(encoding="utf-8"))
        client_config = tomllib.loads((ROOT / "hugegraph-python-client" / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            client_config["project"]["requires-python"].split(",", 1)[0],
            ml_config["project"]["requires-python"].split(",", 1)[0],
        )
        self.assertIn("- python 3.12+", (ROOT / "hugegraph-ml" / "README.md").read_text(encoding="utf-8"))
        self.assertNotIn(
            "current Python range conflicts",
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
