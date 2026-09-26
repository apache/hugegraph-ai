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

from __future__ import annotations

from typing import cast
from unittest.mock import patch

import pytest

from hugegraph_llm.extraction_runtime.v1 import (
    DomainSemanticManifestV1,
    ExtractionEngineV1,
    GateDisposition,
    GateOutcomeV1,
    GraphSnapshotV1,
    IdentityOutcomeV1,
    JsonObject,
    NormalizedChunkV1,
    RepairOutcomeV1,
    RepairRequestV1,
    ReviewBudgetV1,
    ReviewDisposition,
    ReviewOutcomeV1,
    RunControlV1,
    SemanticResourceV1,
    TerminalKind,
    ValidationOutcomeV1,
)
from hugegraph_llm.extraction_runtime.v1 import engine as engine_module

pytestmark = pytest.mark.unit


class ScriptedInventoryBundle:
    def __init__(self, *, repair: bool = False, stale_repair: bool = False) -> None:
        self.repair_enabled = repair
        self.stale_repair = stale_repair
        self.calls: list[str] = []
        self.review_count = 0

    def semantic_manifest(self) -> DomainSemanticManifestV1:
        return DomainSemanticManifestV1(
            bundle_id="inventory",
            bundle_version="1",
            resources=(SemanticResourceV1.from_text("prompt", "extract inventory"),),
            semantics={"identity": "sku"},
        )

    def extract(self, chunk: NormalizedChunkV1) -> JsonObject:
        self.calls.append("extract")
        return {"items": [{"sku": "A", "count": 2}]}

    def validate_schema(self, graph: GraphSnapshotV1, chunk: NormalizedChunkV1) -> ValidationOutcomeV1:
        self.calls.append("schema")
        return ValidationOutcomeV1(valid=True)

    def identify(self, graph: GraphSnapshotV1, chunk: NormalizedChunkV1) -> IdentityOutcomeV1:
        self.calls.append("identity")
        item = cast(list[JsonObject], graph.graph["items"])[0]
        return IdentityOutcomeV1(valid=True, identity={"keys": [item["sku"]]})

    def review(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        validation: ValidationOutcomeV1,
        identity: IdentityOutcomeV1,
    ) -> ReviewOutcomeV1:
        self.calls.append("review")
        self.review_count += 1
        disposition = (
            ReviewDisposition.FIX if self.repair_enabled and self.review_count == 1 else ReviewDisposition.PASS
        )
        return ReviewOutcomeV1(disposition=disposition, expected_graph_digest=graph.graph_digest)

    def repair(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        request: RepairRequestV1,
    ) -> RepairOutcomeV1:
        self.calls.append("repair")
        base = "sha256:stale" if self.stale_repair else graph.graph_digest
        return RepairOutcomeV1(
            base_graph_digest=base,
            candidate_graph={"items": [{"sku": "A", "count": 3}]},
            patch={"count": 3},
        )

    def final_gate(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        validation: ValidationOutcomeV1,
        identity: IdentityOutcomeV1,
        review: ReviewOutcomeV1,
    ) -> GateOutcomeV1:
        self.calls.append("gate")
        return GateOutcomeV1(
            disposition=GateDisposition.PASS,
            expected_graph_digest=graph.graph_digest,
            report={"accepted": True},
        )


def _chunk() -> NormalizedChunkV1:
    return NormalizedChunkV1(document_id="inventory", chunk_id="inventory-0", ordinal=0, text="two bolts")


def _control() -> RunControlV1:
    return RunControlV1(
        budget=ReviewBudgetV1(max_reviews=2, max_fixes=1),
        provider_execution={"adapter": "replay/v1", "model": "inventory-script"},
    )


def test_engine_runs_fixed_no_fix_path_and_returns_uncommitted_artifact() -> None:
    bundle = ScriptedInventoryBundle()
    result = ExtractionEngineV1().run(bundle=bundle, chunk=_chunk(), control=_control())

    assert bundle.calls == ["extract", "schema", "identity", "review", "gate"]
    assert result.intent.kind is TerminalKind.FINAL
    assert result.current_graph is not None and result.current_graph.revision == 0
    assert result.artifact.intent == result.intent
    assert result.artifact.graph == result.current_graph.graph
    assert result.artifact.trace_head == result.trace.trace_head
    assert result.artifact.run_fingerprint == result.fingerprints.run_fingerprint


def test_promoted_repair_is_used_by_every_later_stage_and_artifact() -> None:
    bundle = ScriptedInventoryBundle(repair=True)
    result = ExtractionEngineV1().run(bundle=bundle, chunk=_chunk(), control=_control())

    assert bundle.calls == ["extract", "schema", "identity", "review", "repair", "schema", "identity", "review", "gate"]
    assert result.intent.kind is TerminalKind.FINAL
    assert result.current_graph is not None and result.current_graph.revision == 1
    assert result.intent.graph_digest == result.current_graph.graph_digest
    assert result.artifact.graph == result.current_graph.graph
    assert result.budget.reviews_used == 2 and result.budget.fixes_used == 1
    gate_event = next(event for event in result.trace.events if event.stage == "final_gate")
    assert gate_event.graph_revision == 1
    assert gate_event.graph_digest == result.current_graph.graph_digest


def test_stale_repair_is_failed_without_replacing_current_graph() -> None:
    bundle = ScriptedInventoryBundle(repair=True, stale_repair=True)
    result = ExtractionEngineV1().run(bundle=bundle, chunk=_chunk(), control=_control())

    assert result.intent.kind is TerminalKind.FAILED
    assert result.intent.reason_code == "repair_failed"
    assert result.current_graph is not None and result.current_graph.revision == 0
    assert result.budget.fixes_used == 0
    assert result.diagnostics[-1].code == "repair_failed"


def test_artifact_construction_failure_becomes_a_failed_terminal() -> None:
    bundle = ScriptedInventoryBundle()
    real_builder = engine_module.build_terminal_artifact_body
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("malformed artifact")
        return real_builder(**kwargs)

    with patch.object(engine_module, "build_terminal_artifact_body", side_effect=fail_once):
        result = ExtractionEngineV1().run(bundle=bundle, chunk=_chunk(), control=_control())

    assert result.intent.kind is TerminalKind.FAILED
    assert result.intent.reason_code == "artifact_construction_failed"
    assert result.current_graph is not None and result.current_graph.revision == 0
    assert result.diagnostics[-1].stage == "artifact"
    assert result.diagnostics[-1].details["exception_type"] == "ValueError"
