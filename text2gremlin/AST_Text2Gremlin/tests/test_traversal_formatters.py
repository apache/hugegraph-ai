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

from base.GremlinExpr import Predicate, TextPredicate
from base.GremlinParse import Step
from base.TraversalGenerator import TraversalGenerator


def test_format_gremlin_value_quotes_and_escapes_strings():
    assert TraversalGenerator.format_gremlin_value("marko") == "'marko'"
    assert TraversalGenerator.format_gremlin_value("marko's bike") == "'marko\\'s bike'"
    assert TraversalGenerator.format_gremlin_value(29) == "29"
    assert TraversalGenerator.format_gremlin_value(True) == "true"
    assert TraversalGenerator.format_gremlin_value(None) == "null"


def test_format_gremlin_value_formats_sets_in_stable_order():
    values = {"marko", "vadas", "josh"}

    assert TraversalGenerator.format_gremlin_value(values) == "'josh', 'marko', 'vadas'"
    assert {TraversalGenerator.format_gremlin_value(set(values)) for _ in range(5)} == {"'josh', 'marko', 'vadas'"}


def test_format_gremlin_value_uses_raw_string_fallback_for_unknown_values():
    class RawToken:
        def __str__(self):
            return "Order.desc"

    assert TraversalGenerator.format_gremlin_value(RawToken()) == "Order.desc"


def test_format_predicate_supports_p_textp_and_nested_not():
    assert TraversalGenerator.format_predicate(Predicate("eq", "marko")) == "P.eq('marko')"
    assert TraversalGenerator.format_predicate(Predicate("within", ["marko", "vadas"])) == (
        "P.within('marko', 'vadas')"
    )
    assert TraversalGenerator.format_predicate(Predicate("not", Predicate("eq", "marko"))) == ("P.not(P.eq('marko'))")
    assert TraversalGenerator.format_predicate(TextPredicate("containing", "mar")) == "TextP.containing('mar')"


def test_format_anonymous_traversal_adds_prefix_once():
    assert TraversalGenerator.format_anonymous_traversal("out('knows')") == "__.out('knows')"
    assert TraversalGenerator.format_anonymous_traversal("__.out('knows')") == "__.out('knows')"
    assert TraversalGenerator.format_anonymous_traversal("") == "__.identity()"


def test_loop_predicate_special_steps_use_shared_predicate_formatter():
    generator = object.__new__(TraversalGenerator)

    until_options = generator._handle_special_step(Step("until", [Predicate("eq", "marko")]), None, "vertex", [])
    emit_options = generator._handle_special_step(Step("emit", [Predicate("eq", "marko")]), None, "vertex", [])

    assert until_options[0]["query_part"] == ".until(P.eq('marko'))"
    assert emit_options[0]["query_part"] == ".emit(P.eq('marko'))"


def test_format_param_reuses_shared_formatter():
    class RawToken:
        def __str__(self):
            return "Order.desc"

    generator = object.__new__(TraversalGenerator)

    assert generator._format_param(Predicate("within", ["marko", "vadas"])) == "P.within('marko', 'vadas')"
    assert generator._format_param("marko") == "'marko'"
    assert generator._format_param(RawToken()) == "Order.desc"
