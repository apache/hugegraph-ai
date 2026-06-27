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

import sys
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from analyze_syntax import analyze_query, print_results


def test_analyze_query_counts_start_step_once_and_keeps_group_step():
    stats = analyze_query("g.V().group().by('name')")

    assert stats["steps"]["V"] == 1
    assert stats["steps"]["group"] == 1
    assert stats["steps"]["by"] == 1
    assert stats["step_count"] == 3


def test_print_results_honors_top_n(capsys):
    stats = {
        "steps": Counter({"has": 3, "out": 2}),
        "predicates": Counter(),
        "text_predicates": Counter(),
        "step_counts": [1, 2],
    }

    print_results(stats, total_queries=2, top_n=1)

    out = capsys.readouterr().out
    assert "Top 1" in out
    assert "has" in out
    assert "out" not in out
