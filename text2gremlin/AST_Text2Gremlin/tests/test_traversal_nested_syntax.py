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

import re
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from base.generator import check_gremlin_syntax
from base.GremlinExpr import AnonymousTraversal, Predicate, TextPredicate
from base.GremlinParse import Step, Traversal
from base.GremlinTransVisitor import GremlinTransVisitor
from base.TraversalGenerator import TraversalGenerator

NESTED_QUERIES = [
    "g.V().filter(__.out('knows'))",
    "g.V().filter(__.identity())",
    "g.V().where(__.out('knows'))",
    "g.V().not(__.out('knows'))",
    "g.V().and(__.out('knows'), __.hasLabel('person'))",
    "g.V().or(__.out('knows'), __.hasLabel('software'))",
    "g.V().sideEffect(__.out('knows').count())",
    "g.V().repeat(__.out('knows')).times(2)",
    "g.V().repeat(__.out('knows')).until(P.eq('marko'))",
    "g.V().repeat(__.out('knows')).emit(P.eq('marko'))",
    "g.V().union(__.out('knows'), __.in('created'))",
    "g.V().match(__.as('a').out('knows').as('b'))",
    "g.V().optional(__.out('knows'))",
    "g.V().coalesce(__.out('knows'), __.in('created'))",
    "g.V().choose(__.hasLabel('person'), __.out('knows'), __.in('created'))",
    "g.V().flatMap(__.out('knows'))",
    "g.V().map(__.values('name'))",
    "g.V().where('name', P.within('marko', 'vadas'))",
    "g.V().where(TextP.containing('mar'))",
]


def test_nested_traversal_queries_are_parseable():
    failures = []
    for query in NESTED_QUERIES:
        ok, message = check_gremlin_syntax(query)
        if not ok:
            failures.append((query, message))

    assert failures == []


class _GremlinBase:
    def get_token_desc(self, name: str, *args) -> str:
        return name

    def get_schema_desc(self, name: str) -> str:
        return name


class _Schema:
    def get_edge_labels(self):
        return ["knows", "created"]

    def get_vertex_labels(self):
        return ["person", "software"]

    def get_properties_with_type(self, label: str):
        return [{"name": "name", "type": "STRING"}]

    def get_instances(self, label: str):
        return [{"name": "marko"}, {"name": "vadas"}]


class _SchemaWithSiblings(_Schema):
    def get_properties_with_type(self, label: str):
        return [{"name": "name", "type": "STRING"}, {"name": "city", "type": "STRING"}]

    def get_instances(self, label: str):
        return [
            {"name": "marko", "city": "beijing"},
            {"name": "vadas", "city": "shanghai"},
            {"name": "josh", "city": "hangzhou"},
        ]


class _Recipe:
    def __init__(self, steps):
        self.steps = steps


class _SiblingController:
    def get_chain_category(self, step_count: int) -> str:
        return "medium"

    def select_sibling_options(self, recipe_option, all_options, chain_category):
        return [recipe_option, *[option for option in all_options if option != recipe_option]]

    def get_value_fill_count(self, is_terminal: bool, available_count: int) -> int:
        return min(2, available_count)


class _MultiParamController(_SiblingController):
    max_total = {}
    config = {
        "property_generalization": {
            "medium": {
                "additional_random_max": 2,
            }
        }
    }

    def select_multi_param_schema_options(self, recipe_params, all_options, chain_category):
        return [recipe_params]

    def should_apply_random_enhancement(self, is_terminal: bool, current_enhancement_count: int) -> bool:
        return False


def _anonymous_out(label: str) -> AnonymousTraversal:
    traversal = AnonymousTraversal()
    traversal.add_step(Step("out", [label]))
    return traversal


def _anonymous_match_pattern() -> AnonymousTraversal:
    traversal = AnonymousTraversal()
    traversal.add_step(Step("as", ["a"]))
    traversal.add_step(Step("out", ["knows"]))
    traversal.add_step(Step("as", ["b"]))
    return traversal


def _generate_queries_from_parsed_template(query: str) -> list[str]:
    recipe = GremlinTransVisitor().parse_and_visit(query)
    assert recipe is not None
    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=recipe,
        gremlin_base=_GremlinBase(),
        controller=None,
    )
    generator.controller = None
    return [generated_query for generated_query, _desc in generator.generate()]


def _generate_samples_from_parsed_template(query: str) -> list[dict]:
    recipe = GremlinTransVisitor().parse_and_visit(query)
    assert recipe is not None
    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=recipe,
        gremlin_base=_GremlinBase(),
        controller=None,
    )
    generator.controller = None
    return generator.generate_samples()


def _generate_complete_queries_from_steps(steps: list[Step]) -> list[str]:
    traversal = Traversal()
    for step in steps:
        traversal.add_step(step)

    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=traversal,
        gremlin_base=_GremlinBase(),
        controller=None,
    )
    generator.controller = None
    return [
        sample["query"] for sample in generator.generate_samples() if sample["metadata"]["sample_kind"] == "complete"
    ]


def _assert_complete_generated_sample(template: str, expected_fragment: str) -> None:
    generated_samples = _generate_samples_from_parsed_template(template)
    generated_queries = [sample["query"] for sample in generated_samples]
    complete_queries = [
        sample["query"] for sample in generated_samples if sample["metadata"]["sample_kind"] == "complete"
    ]

    assert generated_queries
    assert all("..." not in query for query in generated_queries)
    assert complete_queries
    assert any(expected_fragment in query for query in complete_queries)
    for query in complete_queries:
        ok, message = check_gremlin_syntax(query)
        assert ok, message


def _parsed_step(query: str, step_name: str) -> Step:
    recipe = GremlinTransVisitor().parse_and_visit(query)
    assert recipe is not None
    matches = [step for step in recipe.steps if step.name == step_name]
    assert matches
    return matches[-1]


def _extract_call_arguments(query: str, call: str) -> list[str]:
    start = query.index(f".{call}(") + len(call) + 2
    depth = 0
    current = []
    args = []
    for char in query[start:]:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            if depth == 0:
                args.append("".join(current).strip())
                return args
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    raise AssertionError(f"unterminated {call} call in {query}")


def test_filter_generation_formats_anonymous_traversal_with_prefix():
    step = Step("filter", [_anonymous_out("knows")])
    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=_Recipe([step]),
        gremlin_base=_GremlinBase(),
        controller=None,
    )

    options = generator._handle_filter_step(step, current_label="person", current_type="vertex", remaining_steps=[])
    query_parts = [option["query_part"] for option in options]

    assert query_parts
    assert all(".filter(out(" not in query_part for query_part in query_parts)
    assert any(query_part.startswith(".filter(__.") for query_part in query_parts)


def test_where_generation_uses_predicate_formatter_for_all_where_forms():
    generator = TraversalGenerator(
        schema=object(),
        recipe=_Recipe([]),
        gremlin_base=_GremlinBase(),
        controller=None,
    )
    cases = [
        (Step("where", [Predicate("eq", "marko")]), ".where(P.eq('marko'))"),
        (
            Step("where", ["name", Predicate("within", ["marko", "vadas"])]),
            ".where('name', P.within('marko', 'vadas'))",
        ),
        (Step("where", [TextPredicate("containing", "mar")]), ".where(TextP.containing('mar'))"),
    ]

    for step, expected in cases:
        options = generator._handle_filter_step(
            step,
            current_label="person",
            current_type="vertex",
            remaining_steps=[],
        )
        assert any(option["query_part"] == expected for option in options)


def test_parse_generate_filter_predicate_keeps_complete_sample_and_syntax():
    cases = [
        ("g.V().filter(P.eq('marko'))", "filter(P.eq('marko'))"),
        ("g.V().filter(TextP.containing('mar'))", "filter(TextP.containing('mar'))"),
    ]

    for template, expected_fragment in cases:
        _assert_complete_generated_sample(template, expected_fragment)


def test_parse_generate_choose_predicate_condition_keeps_complete_sample_and_syntax():
    cases = [
        (
            "g.V().choose(P.eq('marko'), __.out('acted_in'))",
            "choose(P.eq('marko'), __.out('acted_in'))",
        ),
        (
            "g.V().choose(P.eq('marko'), __.out('acted_in'), __.in('directed'))",
            "choose(P.eq('marko'), __.out('acted_in'), __.in('directed'))",
        ),
        (
            "g.V().choose(TextP.containing('mar'), __.values('name'))",
            "choose(TextP.containing('mar'), __.values('name'))",
        ),
    ]

    for template, expected_fragment in cases:
        _assert_complete_generated_sample(template, expected_fragment)


@pytest.mark.parametrize(
    ("template", "expected_token", "expected_fragment"),
    [
        ("g.V().choose(T.label)", "T.label", "choose(T.label)"),
        ("g.V().choose(Column.keys)", "Column.keys", "choose(Column.keys)"),
        ("g.V().choose(label)", "label", "choose(label)"),
    ],
)
def test_parse_generate_choose_function_keeps_raw_token_complete_sample_and_syntax(
    template: str, expected_token: str, expected_fragment: str
):
    step = _parsed_step(template, "choose")

    assert step.params
    assert step.params[0] is not None
    assert str(step.params[0]) == expected_token
    _assert_complete_generated_sample(template, expected_fragment)


@pytest.mark.parametrize(
    ("template", "step_name", "expected_param_count", "expected_fragment"),
    [
        ("g.V().range(0, 10)", "range", 2, "range(0, 10)"),
        ("g.V().limit(5)", "limit", 1, "limit(5)"),
        ("g.V().skip(2)", "skip", 1, "skip(2)"),
        ("g.V().tail(2)", "tail", 1, "tail(2)"),
    ],
)
def test_parse_generate_numeric_param_steps_preserve_arity_and_syntax(
    template: str,
    step_name: str,
    expected_param_count: int,
    expected_fragment: str,
):
    step = _parsed_step(template, step_name)
    generated_samples = _generate_samples_from_parsed_template(template)
    complete_queries = [
        sample["query"] for sample in generated_samples if sample["metadata"]["sample_kind"] == "complete"
    ]

    assert len(step.params) == expected_param_count
    assert complete_queries
    assert any(expected_fragment in query for query in complete_queries), complete_queries
    for query in complete_queries:
        ok, message = check_gremlin_syntax(query)
        assert ok, message


def test_parse_generate_sample_param_preserves_literal_and_syntax():
    template = "g.V().sample(3)"
    step = _parsed_step(template, "sample")
    generated_samples = _generate_samples_from_parsed_template(template)
    complete_queries = [
        sample["query"] for sample in generated_samples if sample["metadata"]["sample_kind"] == "complete"
    ]

    assert step.params == [3]
    assert complete_queries
    assert any("sample(3)" in query for query in complete_queries), complete_queries
    for query in complete_queries:
        ok, message = check_gremlin_syntax(query)
        assert ok, message


@pytest.mark.parametrize(
    ("template", "step_name", "expected_params", "expected_fragment"),
    [
        ("g.V().hasValue(true)", "hasValue", [True], "hasValue(true)"),
        ("g.V().hasValue(false)", "hasValue", [False], "hasValue(false)"),
        ("g.V().hasValue(null)", "hasValue", [None], "hasValue(null)"),
        ("g.V().values('active').is(true)", "is", [True], "is(true)"),
        ("g.V().constant(true)", "constant", [True], "constant(true)"),
        ("g.V().constant(false)", "constant", [False], "constant(false)"),
        ("g.V().constant(null)", "constant", [None], "constant(null)"),
        ("g.V().hasId(true)", "hasId", [True], "hasId(true)"),
        ("g.V().hasId(null)", "hasId", [None], "hasId(null)"),
        ("g.V().hasId('abc')", "hasId", ["abc"], "hasId('abc')"),
        ("g.V().hasId('abc', 'def')", "hasId", ["abc", "def"], "hasId('abc', 'def')"),
        ("g.E('abc', 'def')", "E", ["abc", "def"], "E('abc', 'def')"),
        ("g.E(true, null)", "E", [True, None], "E(true, null)"),
    ],
)
def test_parse_generate_generic_literals_preserves_gremlin_bool_and_null(
    template: str,
    step_name: str,
    expected_params: list,
    expected_fragment: str,
):
    step = _parsed_step(template, step_name)
    generated_samples = _generate_samples_from_parsed_template(template)
    complete_queries = [
        sample["query"] for sample in generated_samples if sample["metadata"]["sample_kind"] == "complete"
    ]

    assert step.params == expected_params
    assert complete_queries
    assert any(expected_fragment in query for query in complete_queries), complete_queries
    for query in complete_queries:
        assert "'true'" not in query
        assert "'false'" not in query
        assert "'null'" not in query
        assert "True" not in query
        assert "False" not in query
        assert "None" not in query
        ok, message = check_gremlin_syntax(query)
        assert ok, message


@pytest.mark.parametrize(
    ("step", "expected_fragment"),
    [
        (Step("hasValue", [True]), "hasValue(true)"),
        (Step("hasValue", [None]), "hasValue(null)"),
        (Step("property", ["active", True]), "property('active', true)"),
        (Step("inject", [True, None]), "inject(true, null)"),
    ],
)
def test_direct_steps_format_bool_and_null_as_gremlin_literals(step: Step, expected_fragment: str):
    complete_queries = _generate_complete_queries_from_steps([Step("V"), step])

    assert complete_queries
    assert any(expected_fragment in query for query in complete_queries), complete_queries
    for query in complete_queries:
        assert "'true'" not in query
        assert "'null'" not in query
        assert "True" not in query
        assert "None" not in query
        ok, message = check_gremlin_syntax(query)
        assert ok, message


@pytest.mark.parametrize(
    ("template", "expected_params", "expected_fragment"),
    [
        ("g.E('abc', 'def')", ["abc", "def"], "E('abc', 'def')"),
        ("g.E(true, null)", [True, None], "E(true, null)"),
    ],
)
def test_parse_generate_e_object_ids_with_controller_preserves_gremlin_literals(
    template: str,
    expected_params: list,
    expected_fragment: str,
):
    recipe = GremlinTransVisitor().parse_and_visit(template)
    assert recipe is not None
    assert recipe.steps[-1].name == "E"
    assert recipe.steps[-1].params == expected_params

    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=recipe,
        gremlin_base=_GremlinBase(),
        controller=_MultiParamController(),
    )
    complete_queries = [
        sample["query"] for sample in generator.generate_samples() if sample["metadata"]["sample_kind"] == "complete"
    ]

    assert complete_queries
    assert any(expected_fragment in query for query in complete_queries), complete_queries
    for query in complete_queries:
        assert "True" not in query
        assert "None" not in query
        assert "E(abc" not in query
        ok, message = check_gremlin_syntax(query)
        assert ok, message


@pytest.mark.parametrize(
    ("template", "expected_params", "expected_queries"),
    [
        ("g.V().hasId('abc')", ["abc"], {"g.V().hasId('abc')"}),
        ("g.V().hasId(true)", [True], {"g.V().hasId(true)"}),
        ("g.V().hasId(null)", [None], {"g.V().hasId(null)"}),
    ],
)
def test_parse_generate_has_id_object_id_with_controller_does_not_cross_type_generalize(
    template: str,
    expected_params: list,
    expected_queries: set[str],
):
    recipe = GremlinTransVisitor().parse_and_visit(template)
    assert recipe is not None
    assert recipe.steps[-1].name == "hasId"
    assert recipe.steps[-1].params == expected_params

    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=recipe,
        gremlin_base=_GremlinBase(),
        controller=_MultiParamController(),
    )
    complete_queries = {
        sample["query"] for sample in generator.generate_samples() if sample["metadata"]["sample_kind"] == "complete"
    }

    assert complete_queries == expected_queries
    for query in complete_queries:
        assert "True" not in query
        assert "None" not in query
        assert "hasId(abc)" not in query
        ok, message = check_gremlin_syntax(query)
        assert ok, message


def test_no_param_range_numeric_fallback_generates_valid_bounds_and_syntax():
    complete_queries = _generate_complete_queries_from_steps([Step("V"), Step("range", [])])

    assert complete_queries
    for query in complete_queries:
        ok, message = check_gremlin_syntax(query)
        assert ok, message
        match = re.search(r"\.range\((\d+), (\d+)\)", query)
        assert match, query
        start, end = (int(value) for value in match.groups())
        assert start < end


def test_no_param_coin_numeric_fallback_generates_probability_and_syntax():
    complete_queries = _generate_complete_queries_from_steps([Step("V"), Step("coin", [])])

    assert complete_queries
    for query in complete_queries:
        ok, message = check_gremlin_syntax(query)
        assert ok, message
        match = re.search(r"\.coin\((\d+\.\d+)\)", query)
        assert match, query
        value = float(match.group(1))
        assert 0 < value < 1


@pytest.mark.parametrize("step_name", ["limit", "sample", "skip", "tail"])
def test_no_param_single_integer_numeric_fallbacks_preserve_one_arg_and_syntax(step_name: str):
    complete_queries = _generate_complete_queries_from_steps([Step("V"), Step(step_name, [])])

    assert complete_queries
    for query in complete_queries:
        ok, message = check_gremlin_syntax(query)
        assert ok, message
        match = re.search(rf"\.{step_name}\((\d+)\)", query)
        assert match, query


def test_empty_anonymous_traversal_generation_uses_identity_and_is_parseable():
    empty = AnonymousTraversal()
    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=_Recipe([]),
        gremlin_base=_GremlinBase(),
        controller=None,
    )
    cases = [
        generator._handle_filter_step(
            Step("filter", [empty]),
            current_label="person",
            current_type="vertex",
            remaining_steps=[],
        ),
        generator._handle_filter_step(
            Step("where", [empty]),
            current_label="person",
            current_type="vertex",
            remaining_steps=[],
        ),
        generator._handle_side_effect_step(
            Step("sideEffect", [empty]),
            current_label="person",
            current_type="vertex",
        ),
        generator._handle_special_step(
            Step("choose", [empty]),
            current_label="person",
            current_type="vertex",
            remaining_steps=[],
        ),
    ]

    query_parts = [options[0]["query_part"] for options in cases]

    assert query_parts == [
        ".filter(__.identity())",
        ".where(__.identity())",
        ".sideEffect(__.identity())",
        ".choose(__.identity())",
    ]
    for query_part in query_parts:
        ok, message = check_gremlin_syntax("g.V()" + query_part)
        assert ok, message


def test_parse_generate_deep_nested_anonymous_traversals_keep_prefixes():
    cases = [
        (
            "g.V().filter(__.filter(__.out('knows')))",
            ".filter(__.filter",
            ".filter(__.filter(__.out('knows')))",
            [".filter(out("],
        ),
        (
            "g.V().sideEffect(__.sideEffect(__.out('knows')))",
            ".sideEffect(__.sideEffect",
            ".sideEffect(__.sideEffect(__.out('knows')))",
            [".sideEffect(out("],
        ),
        (
            "g.V().filter(__.choose(__.out('knows')))",
            ".filter(__.choose",
            ".filter(__.choose(__.out('knows')))",
            [".choose(out("],
        ),
    ]

    for template, relevant_fragment, expected_fragment, forbidden_fragments in cases:
        generated_queries = _generate_queries_from_parsed_template(template)
        relevant_queries = [query for query in generated_queries if relevant_fragment in query]

        assert relevant_queries
        assert any(expected_fragment in query for query in relevant_queries)
        for query in relevant_queries:
            assert "(identity())" not in query
            for forbidden in forbidden_fragments:
                assert forbidden not in query
            ok, message = check_gremlin_syntax(query)
            assert ok, message


def test_parse_generate_depth_capped_nested_anonymous_traversal_uses_identity():
    generated_queries = _generate_queries_from_parsed_template(
        "g.V().filter(__.filter(__.filter(__.filter(__.out('knows')))))"
    )
    relevant_queries = [query for query in generated_queries if ".filter(__.filter(__.filter(__.filter(" in query]

    assert relevant_queries
    assert any(".filter(__.filter(__.filter(__.filter(__.identity()))))" in query for query in relevant_queries)
    for query in relevant_queries:
        assert "..." not in query
        assert "__...." not in query
        ok, message = check_gremlin_syntax(query)
        assert ok, message


def test_parse_generate_nested_predicate_steps_keep_formatter_output():
    cases = [
        (
            "g.V().filter(__.where('name', P.within('marko', 'vadas')))",
            ".filter(__.where",
            ".filter(__.where('name', P.within('marko', 'vadas')))",
            [".where()", ".where(...)"],
        ),
        (
            "g.V().filter(__.where(TextP.containing('mar')))",
            ".filter(__.where",
            ".filter(__.where(TextP.containing('mar')))",
            [".where()", ".where(...)"],
        ),
        (
            "g.V().filter(__.until(TextP.containing('mar')))",
            ".filter(__.until",
            ".filter(__.until(TextP.containing('mar')))",
            [".until()", ".until(...)"],
        ),
        (
            "g.V().filter(__.emit(TextP.containing('mar')))",
            ".filter(__.emit",
            ".filter(__.emit(TextP.containing('mar')))",
            [".emit()", ".emit(...)"],
        ),
    ]

    for template, relevant_fragment, expected_fragment, forbidden_fragments in cases:
        generated_queries = _generate_queries_from_parsed_template(template)
        relevant_queries = [query for query in generated_queries if relevant_fragment in query]

        assert relevant_queries
        assert any(expected_fragment in query for query in relevant_queries)
        for query in relevant_queries:
            assert "..." not in query
            for forbidden in forbidden_fragments:
                assert forbidden not in query
            ok, message = check_gremlin_syntax(query)
            assert ok, message


def test_parse_generate_nested_has_label_key_value_preserves_parameters():
    cases = [
        (
            "g.V().filter(__.has('person', 'name', 'marko'))",
            ".filter(__.has",
            ".filter(__.has('person', 'name', 'marko'))",
        ),
        (
            "g.V().where(__.has('person', 'name', 'marko'))",
            ".where(__.has",
            ".where(__.has('person', 'name', 'marko'))",
        ),
        (
            "g.V().not(__.has('person', 'name', 'marko'))",
            ".not(__.has",
            ".not(__.has('person', 'name', 'marko'))",
        ),
    ]

    for template, relevant_fragment, expected_fragment in cases:
        generated_samples = _generate_samples_from_parsed_template(template)
        generated_queries = [sample["query"] for sample in generated_samples]
        complete_queries = [
            sample["query"]
            for sample in generated_samples
            if sample["metadata"]["sample_kind"] == "complete" and relevant_fragment in sample["query"]
        ]

        assert generated_queries
        assert all("..." not in query for query in generated_queries)
        assert complete_queries
        assert any(expected_fragment in query for query in complete_queries)
        for query in complete_queries:
            ok, message = check_gremlin_syntax(query)
            assert ok, message


def test_parse_generate_top_level_is_uses_predicate_formatter_output():
    cases = [
        (
            "g.V().values('name').is(P.within('marko', 'vadas'))",
            ".is(P.within('marko', 'vadas'))",
            "P.within([",
        ),
        (
            "g.V().values('name').is(TextP.containing('mar'))",
            ".is(TextP.containing('mar'))",
            "TextP.containing([",
        ),
    ]

    for template, expected_fragment, forbidden_fragment in cases:
        generated_queries = _generate_queries_from_parsed_template(template)
        relevant_queries = [query for query in generated_queries if ".is(" in query]

        assert relevant_queries
        assert any(expected_fragment in query for query in relevant_queries)
        for query in relevant_queries:
            assert forbidden_fragment not in query
            ok, message = check_gremlin_syntax(query)
            assert ok, message


def test_parse_generate_nested_multi_argument_anonymous_steps_preserve_arity():
    cases = [
        (
            "g.V().filter(__.choose(__.hasLabel('person'), __.out('knows')))",
            "choose",
            2,
            ["__.hasLabel('person')", "__.out('knows')"],
        ),
        (
            "g.V().filter(__.choose(__.hasLabel('person'), __.out('knows'), __.in('created')))",
            "choose",
            3,
            ["__.hasLabel('person')", "__.out('knows')", "__.in('created')"],
        ),
        (
            "g.V().filter(__.and(__.out('knows'), __.hasLabel('person')))",
            "and",
            2,
            ["__.out('knows')", "__.hasLabel('person')"],
        ),
        (
            "g.V().filter(__.or(__.out('knows'), __.hasLabel('person')))",
            "or",
            2,
            ["__.out('knows')", "__.hasLabel('person')"],
        ),
    ]

    for template, call, expected_arg_count, expected_args in cases:
        generated_queries = _generate_queries_from_parsed_template(template)
        relevant_queries = [query for query in generated_queries if f".filter(__.{call}(" in query]

        assert relevant_queries
        assert any(
            len(_extract_call_arguments(query, call)) == expected_arg_count
            and all(expected_arg in _extract_call_arguments(query, call) for expected_arg in expected_args)
            for query in relevant_queries
        )
        for query in relevant_queries:
            assert "..." not in query
            ok, message = check_gremlin_syntax(query)
            assert ok, message


def test_parse_generate_nested_fallback_steps_preserve_parameters_and_syntax():
    cases = [
        (
            "g.V().filter(__.out('acted_in').limit(1))",
            ".filter(",
            ".filter(__.out('acted_in').limit(1))",
            "limit(1)",
        ),
        (
            "g.V().filter(__.out('acted_in').range(0, 2))",
            ".filter(",
            ".filter(__.out('acted_in').range(0, 2))",
            "range(0, 2)",
        ),
        (
            "g.V().filter(__.out('acted_in').dedup('name'))",
            ".filter(",
            ".filter(__.out('acted_in').dedup('name'))",
            "dedup('name')",
        ),
        (
            "g.V().map(__.values('name').limit(1))",
            ".map(",
            ".map(__.values('name').limit(1))",
            "limit(1)",
        ),
    ]

    for template, call_fragment, expected_fragment, expected_param in cases:
        generated_queries = _generate_queries_from_parsed_template(template)
        relevant_queries = [query for query in generated_queries if call_fragment in query]

        assert relevant_queries
        assert all("..." not in query for query in generated_queries)
        assert any(expected_fragment in query for query in relevant_queries)
        assert any(expected_param in query for query in relevant_queries)
        for query in relevant_queries:
            ok, message = check_gremlin_syntax(query)
            assert ok, message


def test_has_generation_uses_predicate_formatter_for_predicate_values():
    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=_Recipe([]),
        gremlin_base=_GremlinBase(),
        controller=None,
    )
    generator.controller = None
    cases = [
        (
            _parsed_step("g.V().has('name', P.within('marko', 'vadas'))", "has"),
            ".has('name', P.within('marko', 'vadas'))",
        ),
        (
            _parsed_step("g.V().has('name', TextP.containing('mar'))", "has"),
            ".has('name', TextP.containing('mar'))",
        ),
    ]

    for step, expected in cases:
        options = generator._handle_filter_step(
            step,
            current_label="person",
            current_type="vertex",
            remaining_steps=[],
        )
        query_parts = [option["query_part"] for option in options]

        assert expected in query_parts
        assert all("default_value" not in query_part for query_part in query_parts)
        ok, message = check_gremlin_syntax("g.V()" + expected)
        assert ok, message


def test_has_predicate_generation_with_controller_keeps_original_property():
    cases = [
        (
            Step("has", ["name", Predicate("within", ["marko", "vadas"])]),
            ".has('name', P.within('marko', 'vadas'))",
        ),
        (
            Step("has", ["name", TextPredicate("containing", "mar")]),
            ".has('name', TextP.containing('mar'))",
        ),
    ]

    for step, expected in cases:
        generator = TraversalGenerator(
            schema=_SchemaWithSiblings(),
            recipe=_Recipe([step]),
            gremlin_base=_GremlinBase(),
            controller=_SiblingController(),
        )
        options = generator._handle_filter_step(
            step,
            current_label="person",
            current_type="vertex",
            remaining_steps=[],
        )
        query_parts = [option["query_part"] for option in options]

        assert query_parts == [expected]
        assert all(query_part.startswith(".has('name'") for query_part in query_parts)
        assert all(".has('city'" not in query_part for query_part in query_parts)
        ok, message = check_gremlin_syntax("g.V()" + expected)
        assert ok, message


def test_is_predicate_generation_with_known_label_does_not_expand_schema_values():
    cases = [
        (Step("is", [Predicate("within", ["marko", "vadas"])]), ".is(P.within('marko', 'vadas'))"),
        (Step("is", [TextPredicate("containing", "mar")]), ".is(TextP.containing('mar'))"),
    ]

    for step, expected in cases:
        generator = TraversalGenerator(
            schema=_SchemaWithSiblings(),
            recipe=_Recipe([step]),
            gremlin_base=_GremlinBase(),
            controller=_SiblingController(),
        )
        options = generator._handle_filter_step(
            step,
            current_label="person",
            current_type="vertex",
            remaining_steps=[],
        )
        query_parts = [option["query_part"] for option in options]

        assert query_parts == [expected]
        assert all(not query_part.startswith(".is('") for query_part in query_parts)
        ok, message = check_gremlin_syntax("g.V().values('name')" + expected)
        assert ok, message


def test_nested_empty_anonymous_traversal_argument_uses_prefixed_identity():
    inner = AnonymousTraversal()
    outer = AnonymousTraversal()
    outer.add_step(Step("filter", [inner]))
    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=_Recipe([]),
        gremlin_base=_GremlinBase(),
        controller=None,
    )
    generator.controller = None

    options = generator._handle_filter_step(
        Step("filter", [outer]),
        current_label="person",
        current_type="vertex",
        remaining_steps=[],
    )
    query_parts = [option["query_part"] for option in options]

    assert query_parts == [".filter(__.filter(__.identity()))"]
    assert all("(identity())" not in query_part for query_part in query_parts)
    for query_part in query_parts:
        ok, message = check_gremlin_syntax("g.V()" + query_part)
        assert ok, message


def test_match_generation_preserves_label_arguments_and_is_parseable():
    step = Step("match", [_anonymous_match_pattern()])
    generator = TraversalGenerator(
        schema=_Schema(),
        recipe=_Recipe([step]),
        gremlin_base=_GremlinBase(),
        controller=None,
    )

    options = generator._handle_special_step(
        step,
        current_label="person",
        current_type="vertex",
        remaining_steps=[],
    )
    query_parts = [option["query_part"] for option in options]

    assert ".match(__.as('a').out('knows').as('b'))" in query_parts
    for query_part in query_parts:
        ok, message = check_gremlin_syntax("g.V()" + query_part)
        assert ok, message
