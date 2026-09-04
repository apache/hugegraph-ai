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

import inspect
import json
from pathlib import Path

from pyhugegraph.api.gremlin import GremlinManager


def _contract() -> dict:
    path = Path(__file__).parents[1] / "contracts" / "raw_gremlin_hard_budget.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_raw_gremlin_contract_records_every_required_hard_boundary():
    contract = _contract()

    assert contract["public_raw_execution"] == "disabled"
    assert set(contract["required_capabilities"]) == {
        "readonly_principal",
        "evaluation_timeout",
        "server_result_cap",
        "streaming_http_byte_cap",
    }
    assert contract["post_materialization_item_and_byte_limits"] == ("output_guard_only")


def test_gremlin_exec_does_not_claim_unimplemented_per_request_budgets():
    parameters = inspect.signature(GremlinManager.exec).parameters
    contract = _contract()["required_capabilities"]

    assert tuple(parameters) == ("self", "gremlin")
    assert contract["evaluation_timeout"]["status"] == "not_selectable_per_request"
    assert contract["streaming_http_byte_cap"]["status"] == ("unsupported_response_is_fully_materialized")
