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

import json
import runpy
from pathlib import Path
from unittest.mock import patch

import pytest

from hugegraph_llm.api.models.graph_extract_requests import GraphExtractRequest
from hugegraph_llm.models.llms import init_llm

pytestmark = pytest.mark.contract
EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "examples"


def test_documented_property_graph_example_runs_with_the_real_domain(capsys):
    request = json.loads((EXAMPLES / "reviewed-extraction.json").read_text(encoding="utf-8"))
    validated = GraphExtractRequest.model_validate(request)
    assert validated.review_options.max_workers == 2
    clients = []

    class Model:
        def __init__(self):
            self.calls = 0

        def generate(self, *, prompt):
            self.calls += 1
            if self.calls == 2:
                return json.dumps({"decision": "pass", "issues": []})
            person, company = ("Alice", "Acme") if "Alice works for Acme." in prompt else ("Bob", "Beta")
            return json.dumps(
                {
                    "vertices": [
                        {"id": person, "label": "person", "properties": {"name": person}},
                        {"id": company, "label": "company", "properties": {"name": company}},
                    ],
                    "edges": [
                        {
                            "label": "works_for",
                            "outV": person,
                            "outVLabel": "person",
                            "inV": company,
                            "inVLabel": "company",
                            "properties": {},
                        }
                    ],
                }
            )

    def create_client(_settings, *, limit_output, raise_on_truncation):
        assert limit_output is False
        assert raise_on_truncation is True
        model = Model()
        clients.append(model)
        return model

    with patch.object(init_llm, "get_chat_llm", side_effect=create_client):
        runpy.run_path(str(EXAMPLES / "reviewed_property_graph.py"), run_name="__main__")
    results = json.loads(capsys.readouterr().out)
    assert [result["status"] for result in results] == ["final", "final"]
    assert [result["graph"]["vertices"][0]["id"] for result in results] == ["1:Alice", "1:Bob"]
    assert all(len(result["graph"]["edges"]) == 1 for result in results)
    assert all(result["llm_calls"] == 2 for result in results)
    assert len(clients) == 2 and all(client.calls == 2 for client in clients)
