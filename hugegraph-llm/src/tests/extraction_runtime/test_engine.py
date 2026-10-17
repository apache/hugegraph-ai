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

import pytest

from hugegraph_llm.extraction_runtime.v1 import ChunkInput, ExtractionEngineV1, ExtractionOptions
from hugegraph_llm.models.llms.base import LLMOutputTruncatedError
from tests.extraction_runtime._bundles import ScriptedBundle

pytestmark = pytest.mark.unit


def run(bundle, **limits):
    return ExtractionEngineV1().run(bundle=bundle, chunk=ChunkInput(7, "text"), options=ExtractionOptions(**limits))


def test_success_uses_normalized_graph_and_counts_calls():
    bundle = ScriptedBundle()
    result = run(bundle)
    assert result.status == "final"
    assert result.index == 7
    assert result.graph == {"value": 1, "chunk": 7, "normalized": True}
    assert bundle.calls == ["extract", "validate", "review"]
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (1, 0, 2)
    assert result.issues == [] and result.stage is None


@pytest.mark.parametrize(
    ("bundle_kwargs", "limits", "status", "reason", "counts"),
    [
        ({}, {"max_reviews": 0}, "candidate", "review_budget_exhausted", (0, 0, 1)),
        ({"initial": -1}, {"max_fixes": 0}, "blocked", "validation_failed", (0, 0, 1)),
        ({"initial": -1, "repaired": -2}, {}, "blocked", "validation_failed", (0, 1, 2)),
        ({"decisions": ("fix",)}, {"max_fixes": 0}, "candidate", "fix_budget_exhausted", (1, 0, 2)),
        ({"decisions": ("block",)}, {}, "blocked", "review_blocked", (1, 0, 2)),
        ({"decisions": ("fix", "fix")}, {}, "candidate", "fix_budget_exhausted", (2, 1, 4)),
    ],
)
def test_terminal_and_budget_matrix(bundle_kwargs, limits, status, reason, counts):
    result = run(ScriptedBundle(**bundle_kwargs), **limits)
    assert (result.status, result.reason) == (status, reason)
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == counts
    assert result.llm_calls <= 1 + ExtractionOptions(**limits).max_reviews + ExtractionOptions(**limits).max_fixes


def test_validation_issues_reach_repair_then_replacement_is_reviewed():
    bundle = ScriptedBundle(initial=-1)
    result = run(bundle)
    assert result.status == "final" and result.graph["value"] == 2
    assert bundle.validated == [-1, 2]
    assert bundle.repair_issues[0][0].message == "must be non-negative"
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (1, 1, 3)


def test_repaired_graph_never_keeps_previous_review_issues():
    bundle = ScriptedBundle(decisions=("fix",))
    result = run(bundle, max_reviews=1)
    assert result.status == "candidate"
    assert result.reason == "review_budget_exhausted"
    assert result.graph["value"] == 2
    assert result.issues == []
    assert bundle.validated == [1, 2]
    assert bundle.repair_issues[0][0].message == "old review issue"


def test_repair_introducing_invalid_graph_must_be_revalidated():
    result = run(ScriptedBundle(decisions=("fix",), repaired=-1))
    assert result.status == "blocked"
    assert result.graph["value"] == -1
    assert [issue.message for issue in result.issues] == ["must be non-negative"]
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (1, 1, 3)


def test_review_runs_again_on_repaired_graph():
    bundle = ScriptedBundle(decisions=("fix", "pass"))
    result = run(bundle)
    assert result.status == "final" and result.graph["value"] == 2
    assert bundle.calls == ["extract", "validate", "review", "repair", "validate", "review"]
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (2, 1, 4)


@pytest.mark.parametrize(
    ("stage", "counts", "has_graph"),
    [
        ("extract", (0, 0, 1), False),
        ("validate", (0, 0, 1), True),
        ("review", (1, 0, 2), True),
        ("repair", (1, 1, 3), True),
    ],
)
def test_failures_count_attempts_and_preserve_previous_graph(stage, counts, has_graph):
    result = run(ScriptedBundle(decisions=("fix",), fail_at=stage))
    assert result.status == "failed" and result.stage == stage
    assert result.reason == f"{stage}_failed: ValueError"
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == counts
    assert (result.graph is not None) == has_graph
    if has_graph:
        assert result.graph["value"] == 1
    if stage == "repair":
        assert [issue.message for issue in result.issues] == ["old review issue"]


def test_engine_instance_can_run_multiple_chunks_without_state_leaks():
    engine = ExtractionEngineV1()
    first = engine.run(
        bundle=ScriptedBundle(decisions=("fix", "pass")), chunk=ChunkInput(0, "a"), options=ExtractionOptions()
    )
    second = engine.run(bundle=ScriptedBundle(), chunk=ChunkInput(1, "b"), options=ExtractionOptions())
    assert (first.graph["value"], first.fixes_used) == (2, 1)
    assert (second.graph["value"], second.fixes_used, second.llm_calls) == (1, 0, 2)


@pytest.mark.parametrize(
    ("stage", "counts", "has_graph"),
    [("extract", (0, 0, 1), False), ("review", (1, 0, 2), True), ("repair", (1, 1, 3), True)],
)
def test_output_truncation_has_public_reason_and_preserves_graph(stage, counts, has_graph):
    class TruncatedBundle(ScriptedBundle):
        def _call(self, called_stage):
            super()._call(called_stage)
            if called_stage == stage:
                raise LLMOutputTruncatedError()

    result = run(TruncatedBundle(decisions=("fix",)))
    assert result.status == "failed"
    assert result.stage == stage
    assert result.reason == f"{stage}_output_truncated: finish_reason=length"
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == counts
    assert (result.graph is not None) == has_graph
    if has_graph:
        assert result.graph["value"] == 1
    if stage == "repair":
        assert [issue.message for issue in result.issues] == ["old review issue"]
