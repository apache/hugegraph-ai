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

"""End-to-end benchmark: baseline vs. enhanced extraction strategy.

Each scenario drives the same ``PropertyGraphExtract`` pipeline twice — once
with ``extract_strategy="baseline"``, once with ``extract_strategy="enhanced"``
— feeding a deterministic ``FakeLLM`` per-chunk response set. The output of
each run is scored by :class:`GraphExtractionEvaluator` against ground truth.

Design invariants asserted here:

* Enhanced never regresses the F1 of any scenario relative to baseline
  (``enhanced.overall_f1 >= baseline.overall_f1``).
* Enhanced wins strictly on the scenarios it was designed to fix
  (cross-chunk edges, alias mismatch, type coercion).

The numeric table produced by :func:`test_benchmark_produces_comparison_table`
is the source of truth for ``docs/quality/schema-based-graph-extract-report.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

import pytest

from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced import (
    GraphExtractionEvaluator,
    GraphSchemaIndex,
)
from tests.fixtures.fake_llm import FakeLLM

pytestmark = pytest.mark.contract

# --------------------------------------------------------------------- schema

SCHEMA: Dict[str, Any] = {
    "propertykeys": [
        {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "year", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
    ],
    "vertexlabels": [
        {
            "id": 1,
            "name": "Person",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["name"],
            "properties": ["name", "age"],
            "nullable_keys": ["age"],
        },
        {
            "id": 2,
            "name": "Movie",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["title"],
            "properties": ["title", "year"],
            "nullable_keys": ["year"],
        },
    ],
    "edgelabels": [
        {
            "name": "ACTED_IN",
            "source_label": "Person",
            "target_label": "Movie",
            "properties": ["role"],
        },
    ],
}


# --------------------------------------------------------------- scenario type


@dataclass(frozen=True)
class Scenario:
    """A benchmark scenario: LLM responses, chunks, and expected ground truth."""

    name: str
    description: str
    chunks: Sequence[str]
    responses: Sequence[str]
    expected: Mapping[str, Sequence[Mapping[str, Any]]]


def _vertex(label: str, vid: str, **props):
    return {"label": label, "type": "vertex", "id": vid, "properties": props}


def _edge(label: str, out_v: str, in_v: str, **props):
    return {
        "label": label,
        "type": "edge",
        "outV": out_v,
        "inV": in_v,
        "outVLabel": "Person",
        "inVLabel": "Movie",
        "properties": props,
    }


def _r(vertices, edges) -> str:
    return json.dumps({"vertices": vertices, "edges": edges}, ensure_ascii=False)


# ------------------------------------------------------- benchmark scenarios


def _build_scenarios() -> List[Scenario]:
    scenarios: List[Scenario] = []

    # 1. Simple well-formed — both should be perfect.
    scenarios.append(
        Scenario(
            name="s01_simple_well_formed",
            description="Well-formed single-chunk extraction; both strategies must be perfect.",
            chunks=["Tom Hanks starred in Forrest Gump."],
            responses=[
                _r(
                    [
                        {"label": "Person", "type": "vertex", "id": "v1", "properties": {"name": "Tom Hanks"}},
                        {"label": "Movie", "type": "vertex", "id": "v2", "properties": {"title": "Forrest Gump"}},
                    ],
                    [
                        {
                            "label": "ACTED_IN",
                            "type": "edge",
                            "outV": "v1",
                            "inV": "v2",
                            "outVLabel": "Person",
                            "inVLabel": "Movie",
                            "properties": {"role": "Forrest"},
                        }
                    ],
                )
            ],
            expected={
                "vertices": [
                    _vertex("Person", "1:Tom Hanks", name="Tom Hanks"),
                    _vertex("Movie", "2:Forrest Gump", title="Forrest Gump"),
                ],
                "edges": [_edge("ACTED_IN", "1:Tom Hanks", "2:Forrest Gump", role="Forrest")],
            },
        )
    )

    # 2. Extra property (not in schema) — both filter it out.
    scenarios.append(
        Scenario(
            name="s02_extra_property_filtered",
            description="LLM emits a property outside the schema; both strategies must drop it.",
            chunks=["Tom Hanks is an actor."],
            responses=[
                _r(
                    [
                        {
                            "label": "Person",
                            "type": "vertex",
                            "id": "v1",
                            "properties": {"name": "Tom Hanks", "email": "tom@example.com"},
                        }
                    ],
                    [],
                )
            ],
            expected={"vertices": [_vertex("Person", "1:Tom Hanks", name="Tom Hanks")], "edges": []},
        )
    )

    # 3. Wrong property type — enhanced coerces "62" (str) → 62 (int); baseline keeps str.
    scenarios.append(
        Scenario(
            name="s03_type_coercion_int",
            description="LLM emits INT age as string; enhanced coerces, baseline keeps str.",
            chunks=["Tom Hanks is 62."],
            responses=[
                _r(
                    [
                        {
                            "label": "Person",
                            "type": "vertex",
                            "id": "v1",
                            "properties": {"name": "Tom Hanks", "age": "62"},
                        }
                    ],
                    [],
                )
            ],
            expected={"vertices": [_vertex("Person", "1:Tom Hanks", name="Tom Hanks", age=62)], "edges": []},
        )
    )

    # 4. Missing primary key — both strategies drop the vertex.
    scenarios.append(
        Scenario(
            name="s04_missing_primary_key",
            description="LLM emits a Person with no name; both strategies must drop it.",
            chunks=["Someone starred in Forrest Gump."],
            responses=[
                _r(
                    [
                        {
                            "label": "Person",
                            "type": "vertex",
                            "id": "v1",
                            "properties": {"age": 60},
                        }
                    ],
                    [],
                )
            ],
            expected={"vertices": [], "edges": []},
        )
    )

    # 5. Duplicate vertex across chunks — enhanced dedupes; baseline reports raw duplicates.
    scenarios.append(
        Scenario(
            name="s05_duplicate_vertex_across_chunks",
            description="Same Person mentioned in two chunks; enhanced dedupes.",
            chunks=[
                "Tom Hanks starred in Forrest Gump.",
                "Tom Hanks won an Oscar.",
            ],
            responses=[
                _r(
                    [
                        {"label": "Person", "type": "vertex", "id": "v1", "properties": {"name": "Tom Hanks"}},
                    ],
                    [],
                ),
                _r(
                    [
                        {"label": "Person", "type": "vertex", "id": "v1", "properties": {"name": "Tom Hanks"}},
                    ],
                    [],
                ),
            ],
            expected={"vertices": [_vertex("Person", "1:Tom Hanks", name="Tom Hanks")], "edges": []},
        )
    )

    # 6. Cross-chunk edge — enhanced repairs via alias table; baseline drops.
    scenarios.append(
        Scenario(
            name="s06_cross_chunk_edge",
            description="Edge references a vertex defined in a different chunk.",
            chunks=[
                "Tom Hanks is an actor.",
                "He starred in Forrest Gump as Forrest.",
            ],
            responses=[
                _r(
                    [
                        {"label": "Person", "type": "vertex", "id": "v1", "properties": {"name": "Tom Hanks"}},
                    ],
                    [],
                ),
                _r(
                    [
                        {"label": "Movie", "type": "vertex", "id": "v2", "properties": {"title": "Forrest Gump"}},
                    ],
                    [
                        {
                            "label": "ACTED_IN",
                            "type": "edge",
                            "outV": "v1",
                            "inV": "v2",
                            "outVLabel": "Person",
                            "inVLabel": "Movie",
                            "properties": {"role": "Forrest"},
                        }
                    ],
                ),
            ],
            expected={
                "vertices": [
                    _vertex("Person", "1:Tom Hanks", name="Tom Hanks"),
                    _vertex("Movie", "2:Forrest Gump", title="Forrest Gump"),
                ],
                "edges": [_edge("ACTED_IN", "1:Tom Hanks", "2:Forrest Gump", role="Forrest")],
            },
        )
    )

    # 7. Alias mismatch — chunk 1 emits raw id, chunk 2 emits canonical id for same entity.
    scenarios.append(
        Scenario(
            name="s07_alias_mismatch",
            description="Chunk 1 uses raw id 'v1'; chunk 2 refers to the same entity by canonical id.",
            chunks=[
                "Tom Hanks is an actor.",
                "Tom Hanks starred in Forrest Gump.",
            ],
            responses=[
                _r(
                    [
                        {"label": "Person", "type": "vertex", "id": "v1", "properties": {"name": "Tom Hanks"}},
                    ],
                    [],
                ),
                _r(
                    [
                        {
                            "label": "Movie",
                            "type": "vertex",
                            "id": "v2",
                            "properties": {"title": "Forrest Gump"},
                        },
                    ],
                    [
                        {
                            "label": "ACTED_IN",
                            "type": "edge",
                            "outV": "1:Tom Hanks",
                            "inV": "v2",
                            "outVLabel": "Person",
                            "inVLabel": "Movie",
                            "properties": {"role": "Forrest"},
                        }
                    ],
                ),
            ],
            expected={
                "vertices": [
                    _vertex("Person", "1:Tom Hanks", name="Tom Hanks"),
                    _vertex("Movie", "2:Forrest Gump", title="Forrest Gump"),
                ],
                "edges": [_edge("ACTED_IN", "1:Tom Hanks", "2:Forrest Gump", role="Forrest")],
            },
        )
    )

    # 8. Invalid label — both strategies drop unknown labels.
    scenarios.append(
        Scenario(
            name="s08_invalid_label",
            description="LLM emits a label outside the schema; both strategies must drop it.",
            chunks=["Directed by someone."],
            responses=[
                _r(
                    [
                        {"label": "Director", "type": "vertex", "id": "v1", "properties": {"name": "Someone"}},
                        {"label": "Person", "type": "vertex", "id": "v2", "properties": {"name": "Tom Hanks"}},
                    ],
                    [],
                )
            ],
            expected={"vertices": [_vertex("Person", "1:Tom Hanks", name="Tom Hanks")], "edges": []},
        )
    )

    # 9. Malformed JSON — both strategies handle gracefully; neither emits vertices/edges.
    scenarios.append(
        Scenario(
            name="s09_malformed_json",
            description="LLM output not parseable as JSON; both strategies must return empty.",
            chunks=["Empty chunk."],
            responses=["Not JSON at all; the LLM went off script."],
            expected={"vertices": [], "edges": []},
        )
    )

    # 10. Combined win: coerce + cross-chunk edge.
    scenarios.append(
        Scenario(
            name="s10_coerce_and_cross_chunk",
            description="Cross-chunk edge with a string-typed INT property; enhanced wins on both.",
            chunks=[
                "Tom Hanks is 62.",
                "He starred in Forrest Gump released in 1994.",
            ],
            responses=[
                _r(
                    [
                        {
                            "label": "Person",
                            "type": "vertex",
                            "id": "v1",
                            "properties": {"name": "Tom Hanks", "age": "62"},
                        }
                    ],
                    [],
                ),
                _r(
                    [
                        {
                            "label": "Movie",
                            "type": "vertex",
                            "id": "v2",
                            "properties": {"title": "Forrest Gump", "year": "1994"},
                        },
                    ],
                    [
                        {
                            "label": "ACTED_IN",
                            "type": "edge",
                            "outV": "v1",
                            "inV": "v2",
                            "outVLabel": "Person",
                            "inVLabel": "Movie",
                            "properties": {"role": "Forrest"},
                        }
                    ],
                ),
            ],
            expected={
                "vertices": [
                    _vertex("Person", "1:Tom Hanks", name="Tom Hanks", age=62),
                    _vertex("Movie", "2:Forrest Gump", title="Forrest Gump", year=1994),
                ],
                "edges": [_edge("ACTED_IN", "1:Tom Hanks", "2:Forrest Gump", role="Forrest")],
            },
        )
    )

    return scenarios


# ------------------------------------------------------------ runtime harness


def _run(scenario: Scenario, *, strategy: str) -> Dict[str, Any]:
    llm = FakeLLM(scenario.responses)
    extractor = PropertyGraphExtract(llm=llm, example_prompt="", extract_strategy=strategy)
    context = {"schema": SCHEMA, "chunks": list(scenario.chunks)}
    result = extractor.run(context)
    return {"vertices": result.get("vertices", []), "edges": result.get("edges", [])}


@pytest.fixture(scope="module")
def evaluator() -> GraphExtractionEvaluator:
    return GraphExtractionEvaluator(GraphSchemaIndex(SCHEMA))


@pytest.fixture(scope="module")
def scenarios() -> List[Scenario]:
    return _build_scenarios()


# --------------------------------------------------------------- benchmark


def test_benchmark_produces_comparison_table(scenarios, evaluator, capsys):
    """Runs every scenario against both strategies and prints a Markdown table.

    The table drives ``docs/quality/schema-based-graph-extract-report.md`` and
    also acts as the human-readable audit trail for the design invariants below.
    Use ``pytest -s`` to see the table locally.
    """
    header = "| scenario | baseline F1 | enhanced F1 | baseline valid% | enhanced valid% | baseline match% | enhanced match% |"
    separator = "|---|---:|---:|---:|---:|---:|---:|"
    rows: List[str] = [header, separator]
    baseline_f1_sum = 0.0
    enhanced_f1_sum = 0.0
    for scenario in scenarios:
        baseline_pred = _run(scenario, strategy="baseline")
        enhanced_pred = _run(scenario, strategy="enhanced")
        baseline_report = evaluator.evaluate(baseline_pred, scenario.expected)
        enhanced_report = evaluator.evaluate(enhanced_pred, scenario.expected)
        rows.append(
            "| {name} | {bf1:.2f} | {ef1:.2f} | {bv:.2f} | {ev:.2f} | {bm:.2f} | {em:.2f} |".format(
                name=scenario.name,
                bf1=baseline_report.overall_f1,
                ef1=enhanced_report.overall_f1,
                bv=baseline_report.property_metrics.property_valid_ratio,
                ev=enhanced_report.property_metrics.property_valid_ratio,
                bm=baseline_report.property_metrics.property_exact_match_rate,
                em=enhanced_report.property_metrics.property_exact_match_rate,
            )
        )
        baseline_f1_sum += baseline_report.overall_f1
        enhanced_f1_sum += enhanced_report.overall_f1
        # Design invariant: enhanced never regresses F1.
        assert enhanced_report.overall_f1 + 1e-9 >= baseline_report.overall_f1, (
            f"{scenario.name}: enhanced F1 {enhanced_report.overall_f1} regressed vs "
            f"baseline {baseline_report.overall_f1}"
        )

    avg_baseline = baseline_f1_sum / len(scenarios)
    avg_enhanced = enhanced_f1_sum / len(scenarios)
    rows.append("| **average** | **{ab:.2f}** | **{ae:.2f}** | | | | |".format(ab=avg_baseline, ae=avg_enhanced))
    # Print to stdout so `pytest -s` captures the exact table to paste into the report.
    print("\n" + "\n".join(rows))
    assert avg_enhanced >= avg_baseline


def test_enhanced_wins_on_cross_chunk_edge(scenarios, evaluator):
    scenario = next(s for s in scenarios if s.name == "s06_cross_chunk_edge")
    baseline_report = evaluator.evaluate(_run(scenario, strategy="baseline"), scenario.expected)
    enhanced_report = evaluator.evaluate(_run(scenario, strategy="enhanced"), scenario.expected)
    assert baseline_report.edge_metrics.f1 == 0.0
    assert enhanced_report.edge_metrics.f1 == 1.0


def test_enhanced_wins_on_alias_mismatch(scenarios, evaluator):
    scenario = next(s for s in scenarios if s.name == "s07_alias_mismatch")
    baseline_report = evaluator.evaluate(_run(scenario, strategy="baseline"), scenario.expected)
    enhanced_report = evaluator.evaluate(_run(scenario, strategy="enhanced"), scenario.expected)
    assert baseline_report.edge_metrics.f1 == 0.0
    assert enhanced_report.edge_metrics.f1 == 1.0


def test_enhanced_wins_on_type_coercion(scenarios, evaluator):
    scenario = next(s for s in scenarios if s.name == "s03_type_coercion_int")
    baseline_report = evaluator.evaluate(_run(scenario, strategy="baseline"), scenario.expected)
    enhanced_report = evaluator.evaluate(_run(scenario, strategy="enhanced"), scenario.expected)
    assert enhanced_report.property_metrics.property_exact_match_rate == 1.0
    assert baseline_report.property_metrics.property_exact_match_rate < 1.0


def test_enhanced_matches_baseline_on_well_formed_input(scenarios, evaluator):
    scenario = next(s for s in scenarios if s.name == "s01_simple_well_formed")
    baseline_report = evaluator.evaluate(_run(scenario, strategy="baseline"), scenario.expected)
    enhanced_report = evaluator.evaluate(_run(scenario, strategy="enhanced"), scenario.expected)
    assert baseline_report.overall_f1 == 1.0
    assert enhanced_report.overall_f1 == 1.0
