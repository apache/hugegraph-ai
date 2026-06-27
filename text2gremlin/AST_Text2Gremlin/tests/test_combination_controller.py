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

# ruff: noqa: E402

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from base.CombinationController import CombinationController


def _controller() -> CombinationController:
    config_path = PROJECT_DIR / "base" / "combination_control_config.json"
    with config_path.open(encoding="utf-8") as f:
        config = json.load(f)
    return CombinationController(config)


def test_select_multi_param_schema_options_returns_empty_combination_for_no_params():
    controller = _controller()

    assert controller.select_multi_param_schema_options([], ["person", "movie"], "short") == [[]]


def test_select_multi_param_schema_options_preserves_single_param_count():
    controller = _controller()

    combinations = controller.select_multi_param_schema_options(
        ["person"],
        ["person", "movie", "software"],
        "short",
    )

    assert combinations == [["person"], ["movie"], ["software"]]


def test_select_multi_param_schema_options_preserves_multi_param_count():
    controller = _controller()

    combinations = controller.select_multi_param_schema_options(
        ["person", "movie"],
        ["person", "movie", "software", "book", "city"],
        "short",
    )

    assert combinations[0] == ["person", "movie"]
    assert all(len(combo) == 2 for combo in combinations)
