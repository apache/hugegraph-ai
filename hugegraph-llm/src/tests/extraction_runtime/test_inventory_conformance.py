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

import pytest

from hugegraph_llm.extraction_runtime.conformance import InventoryBundleV1, InventoryPolicyV1
from hugegraph_llm.extraction_runtime.provider import (
    ProviderResponseV1,
    ReplayEntryV1,
    ReplayProvider,
)
from hugegraph_llm.extraction_runtime.v1 import (
    ExtractionEngineV1,
    GateDisposition,
    GraphSnapshotV1,
    GraphStateV1,
    JsonObject,
    NormalizedChunkV1,
    RepairOutcomeV1,
    RepairReason,
    RepairRequestV1,
    ReviewBudgetV1,
    RunControlV1,
    TerminalKind,
)

pytestmark = pytest.mark.contract


def _chunk() -> NormalizedChunkV1:
    return NormalizedChunkV1(
        document_id="inventory",
        chunk_id="inventory-0",
        ordinal=0,
        text="Inventory contains two bolts.",
        visible_metadata={"source": "redistributable-fixture"},
    )


def _bundle(
    initial_graph: JsonObject,
    *,
    repaired_graph: JsonObject | None = None,
    policy: InventoryPolicyV1 | None = None,
    bundle_type: type[InventoryBundleV1] = InventoryBundleV1,
) -> InventoryBundleV1:
    chunk = _chunk()
    template = InventoryBundleV1(ReplayProvider(()), policy)
    extract_request = template.plan_extract(chunk)
    entries = [
        ReplayEntryV1(
            extract_request.adaptation.requested_digest,
            extract_request.adaptation.effective_digest,
            ProviderResponseV1(output={"graph": initial_graph}, model=template.model, model_revision="fixture-1"),
        )
    ]
    if repaired_graph is not None:
        snapshot = GraphStateV1().promote_initial(initial_graph)
        validation = template.validate_schema(snapshot, chunk)
        identity = template.identify(snapshot, chunk)
        review = template.review(snapshot, chunk, validation, identity)
        request = RepairRequestV1(
            reason=RepairReason.REVIEW,
            expected_graph_digest=snapshot.graph_digest,
            context={
                "review_disposition": review.disposition.value,
                "review_findings": list(review.findings),
            },
        )
        repair_request = template.plan_repair(snapshot, chunk, request)
        entries.append(
            ReplayEntryV1(
                repair_request.adaptation.requested_digest,
                repair_request.adaptation.effective_digest,
                ProviderResponseV1(
                    output={"graph": repaired_graph, "patch": {"op": "replace-count"}},
                    model=template.model,
                    model_revision="fixture-1",
                ),
            )
        )
    return bundle_type(ReplayProvider(tuple(entries)), policy)


def _run(bundle: InventoryBundleV1, *, reviews: int = 2, fixes: int = 1):
    return ExtractionEngineV1().run(
        bundle=bundle,
        chunk=_chunk(),
        control=RunControlV1(
            budget=ReviewBudgetV1(max_reviews=reviews, max_fixes=fixes),
            provider_execution=bundle.provider_execution(),
            host_plan={"source_mapping": "fixture/v1"},
        ),
    )


def test_inventory_no_fix_conformance_is_final_and_fully_bound() -> None:
    bundle = _bundle({"items": [{"sku": "BOLT", "count": 2}]})
    result = _run(bundle)

    assert result.intent.kind is TerminalKind.FINAL
    assert result.current_graph is not None and result.current_graph.revision == 0
    assert [event.stage for event in result.trace.events] == [
        "extract",
        "schema",
        "identity",
        "review",
        "final_gate",
        "terminal",
    ]
    assert result.artifact.graph == result.current_graph.graph
    assert result.intent.graph_digest == result.current_graph.graph_digest
    assert result.artifact.trace_head == result.trace.trace_head
    assert result.artifact.run_fingerprint == result.fingerprints.run_fingerprint
    assert result.artifact.domain_semantic_digest == result.fingerprints.domain_semantic_digest
    assert result.artifact.provider_execution_digest == result.fingerprints.provider_execution_digest
    assert result.artifact.input_digest == result.fingerprints.input_digest
    assert cast(ReplayProvider, bundle.provider).remaining == 0


def test_inventory_post_fix_conformance_uses_repaired_current_graph_everywhere() -> None:
    bundle = _bundle(
        {"items": [{"sku": "BOLT", "count": 0}]},
        repaired_graph={"items": [{"sku": "BOLT", "count": 2}]},
        policy=InventoryPolicyV1(minimum_count=1),
    )
    result = _run(bundle)

    assert result.intent.kind is TerminalKind.FINAL
    assert result.current_graph is not None and result.current_graph.revision == 1
    assert result.intent.graph_digest == result.current_graph.graph_digest
    assert result.artifact.graph == result.current_graph.graph
    assert result.artifact.intent.graph_revision == 1
    assert result.budget.reviews_used == 2 and result.budget.fixes_used == 1
    assert [
        event.graph_revision for event in result.trace.events if event.stage in {"schema", "identity", "review"}
    ] == [
        0,
        0,
        0,
        1,
        1,
        1,
    ]
    assert cast(ReplayProvider, bundle.provider).remaining == 0


@pytest.mark.parametrize(
    ("bundle", "reviews", "fixes", "kind", "reason"),
    [
        (
            _bundle({"items": [{"sku": "BOLT", "count": 2}]}),
            0,
            1,
            TerminalKind.CANDIDATE,
            "quality_budget_exhausted",
        ),
        (
            _bundle(
                {"items": [{"sku": "BOLT", "count": 0}]},
                policy=InventoryPolicyV1(minimum_count=1),
            ),
            1,
            0,
            TerminalKind.CANDIDATE,
            "quality_budget_exhausted",
        ),
        (
            _bundle(
                {"items": [{"sku": "BANNED", "count": 2}]},
                policy=InventoryPolicyV1(blocked_skus=("BANNED",)),
            ),
            1,
            1,
            TerminalKind.BLOCKED,
            "review_blocked",
        ),
        (
            _bundle(
                {"items": [{"sku": "BOLT", "count": 2}]},
                policy=InventoryPolicyV1(gate_disposition=GateDisposition.HOLD),
            ),
            1,
            1,
            TerminalKind.CANDIDATE,
            "gate_hold",
        ),
        (
            _bundle(
                {"items": [{"sku": "BOLT", "count": 2}]},
                policy=InventoryPolicyV1(gate_disposition=GateDisposition.BLOCK),
            ),
            1,
            1,
            TerminalKind.BLOCKED,
            "gate_blocked",
        ),
    ],
)
def test_inventory_terminal_and_budget_matrix(
    bundle: InventoryBundleV1,
    reviews: int,
    fixes: int,
    kind: TerminalKind,
    reason: str,
) -> None:
    result = _run(bundle, reviews=reviews, fixes=fixes)
    assert result.intent.kind is kind
    assert result.intent.reason_code == reason


@pytest.mark.parametrize(
    ("graph", "reason"),
    [
        ({"items": "not-a-list"}, "schema_invalid"),
        ({"items": [{"sku": "A", "count": 1}, {"sku": "A", "count": 2}]}, "identity_invalid"),
    ],
)
def test_unsafe_inventory_graphs_are_blocked_without_fix_budget(graph: JsonObject, reason: str) -> None:
    result = _run(_bundle(graph), fixes=0)
    assert result.intent.kind is TerminalKind.BLOCKED
    assert result.intent.reason_code == reason


class StaleRepairInventoryBundle(InventoryBundleV1):
    def repair(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        request: RepairRequestV1,
    ) -> RepairOutcomeV1:
        outcome = super().repair(graph, chunk, request)
        return RepairOutcomeV1(
            base_graph_digest="sha256:stale",
            candidate_graph=outcome.candidate_graph,
            patch=outcome.patch,
        )


class MalformedRepairInventoryBundle(InventoryBundleV1):
    def repair(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        request: RepairRequestV1,
    ) -> RepairOutcomeV1:
        super().repair(graph, chunk, request)
        return RepairOutcomeV1(
            base_graph_digest=graph.graph_digest,
            candidate_graph=cast(JsonObject, {"items": [{"sku": "BOLT", "count": object()}]}),
        )


@pytest.mark.parametrize("bundle_type", [StaleRepairInventoryBundle, MalformedRepairInventoryBundle])
def test_stale_and_malformed_inventory_repairs_fail_without_promotion(
    bundle_type: type[InventoryBundleV1],
) -> None:
    bundle = _bundle(
        {"items": [{"sku": "BOLT", "count": 0}]},
        repaired_graph={"items": [{"sku": "BOLT", "count": 2}]},
        policy=InventoryPolicyV1(minimum_count=1),
        bundle_type=bundle_type,
    )
    result = _run(bundle)

    assert result.intent.kind is TerminalKind.FAILED
    assert result.intent.reason_code == "repair_failed"
    assert result.current_graph is not None and result.current_graph.revision == 0
    assert result.budget.fixes_used == 0
    assert result.diagnostics[-1].stage == "repair"


def test_provider_failure_is_a_failed_terminal_without_current_graph() -> None:
    bundle = InventoryBundleV1(ReplayProvider(()))
    result = _run(bundle)

    assert result.intent.kind is TerminalKind.FAILED
    assert result.intent.reason_code == "extract_failed"
    assert result.current_graph is None
    assert result.artifact.graph is None
    assert result.diagnostics[-1].details["exception_type"] == "ReplayExhaustedError"
