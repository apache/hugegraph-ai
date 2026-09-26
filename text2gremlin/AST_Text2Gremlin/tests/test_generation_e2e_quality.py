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
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from base.Config import Config
from base.generator import check_gremlin_syntax
from base.GremlinBase import GremlinBase
from base.GremlinTransVisitor import GremlinTransVisitor
from base.Schema import Schema
from base.TraversalGenerator import TraversalGenerator


def _generator_for(query: str) -> TraversalGenerator:
    config = Config(PROJECT_DIR / "config_example.json")
    schema = Schema(
        str(PROJECT_DIR / "db_data" / "schema" / "movie_schema.json"),
        str(PROJECT_DIR / "db_data" / "movie" / "raw_data"),
    )
    gremlin_base = GremlinBase(config)
    recipe = GremlinTransVisitor().parse_and_visit(query)
    return TraversalGenerator(schema, recipe, gremlin_base)


def test_generation_keeps_prefix_and_complete_samples_parseable():
    generator = _generator_for("g.V().hasLabel('person').out('acted_in').values('title')")

    generated = generator.generate()
    payloads = [sample.to_dict() for sample in generator.selected_samples]
    kinds = {payload["metadata"]["sample_kind"] for payload in payloads}

    assert generated
    assert "prefix" in kinds
    assert "complete" in kinds

    failures = []
    for query, _description in generated:
        ok, message = check_gremlin_syntax(query)
        if not ok:
            failures.append((query, message))

    assert failures == []


def test_generation_selection_keeps_medium_and_deep_samples():
    generator = _generator_for("g.V().hasLabel('person').out('acted_in').in('directed').values('name')")

    generator.generate()
    depths = {sample.top_level_step_count for sample in generator.selected_samples}

    assert any(depth >= 4 for depth in depths)
    assert any(2 <= depth <= 3 for depth in depths)
