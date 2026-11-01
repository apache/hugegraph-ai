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

import ast
import importlib.util
import json
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "client_api.py"
SPEC = importlib.util.spec_from_file_location("client_api", PATH)
assert SPEC is not None and SPEC.loader is not None
client_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client_api)


class ClientContractTest(unittest.TestCase):
    def test_static_resources_and_named_algorithms_match_the_contract(self):
        root = client_api.PACKAGE
        contract = json.loads((root / "api/server_contract.json").read_text())
        self.assertEqual([], client_api.check_operation_bindings(contract))
        for filename, generated in (
            ("rest.py", client_api.render_resources()),
            ("olap.py", client_api.render_algorithms(contract)),
        ):
            self.assertEqual(ast.dump(ast.parse((root / "api" / filename).read_text())), ast.dump(ast.parse(generated)))

    def test_openapi_changes_report_added_removed_and_changed_parameters(self):
        contract = {
            "operations": {
                "vertex.get": {"method": "GET", "path": "vertices/{id}", "query": ["limit"]},
                "obsolete.get": {"method": "GET", "path": "obsolete", "query": []},
            }
        }
        document = {
            "paths": {
                "/vertices/{vertex_id}": {"get": {"parameters": [{"in": "query", "name": "page"}]}},
                "/new": {"post": {}},
            }
        }
        changes = client_api.compare_openapi(document, contract)
        self.assertIn("ADDED POST /new", changes)
        self.assertIn("MISSING GET /obsolete", changes)
        self.assertTrue(any("PARAMETERS GET /vertices/{}" in change and "page" in change for change in changes))

    def test_openapi_path_level_parameters_and_explicit_platform_exclusions(self):
        contract = {
            "operations": {"list": {"method": "GET", "path": "vertices", "query": ["page"]}},
            "platform_operations": [{"method": "GET", "path": "application.wadl"}],
        }
        document = {
            "paths": {
                "/vertices": {"parameters": [{"in": "query", "name": "page"}], "get": {}},
                "/application.wadl": {"get": {}},
            }
        }
        self.assertEqual([], client_api.compare_openapi(document, contract))

    def test_invalid_openapi_input_fails_instead_of_reporting_an_empty_api(self):
        with self.assertRaises(ValueError):
            client_api.compare_openapi({}, {"operations": {}})
