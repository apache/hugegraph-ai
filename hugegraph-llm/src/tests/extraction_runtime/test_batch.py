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

from threading import Barrier, Event, Lock

import pytest

from hugegraph_llm.extraction_runtime.conformance import InventoryBundleV1, InventoryPolicyV1
from hugegraph_llm.extraction_runtime.provider import ProviderResponseV1, ReplayEntryV1, ReplayProvider
from hugegraph_llm.extraction_runtime.v1 import (
    ExtractionEngineV1,
    GateDisposition,
    GraphStateV1,
    NormalizedChunkV1,
    RepairReason,
    RepairRequestV1,
    ReviewBudgetV1,
    RunControlV1,
    TerminalKind,
    run_chunks_v1,
)

pytestmark = pytest.mark.contract


def _chunk(ordinal: int) -> NormalizedChunkV1:
    return NormalizedChunkV1(
        document_id="inventory", chunk_id=f"chunk-{ordinal}", ordinal=ordinal, text=f"Item {ordinal}"
    )


def _prepare(chunk, bundle_type=InventoryBundleV1, policy=None):
    template = InventoryBundleV1(ReplayProvider(()), policy)
    initial = {"items": [{"sku": chunk.chunk_id, "count": 0}]}
    repaired = {"items": [{"sku": chunk.chunk_id, "count": chunk.ordinal + 1}]}
    snapshot = GraphStateV1().promote_initial(initial)
    validation = template.validate_schema(snapshot, chunk)
    identity = template.identify(snapshot, chunk)
    review = template.review(snapshot, chunk, validation, identity)
    repair_request = RepairRequestV1(
        reason=RepairReason.REVIEW,
        expected_graph_digest=snapshot.graph_digest,
        context={"review_disposition": review.disposition.value, "review_findings": list(review.findings)},
    )
    entries = tuple(
        ReplayEntryV1(
            request.adaptation.requested_digest,
            request.adaptation.effective_digest,
            ProviderResponseV1(output={"graph": graph}, model=template.model),
        )
        for request, graph in (
            (template.plan_extract(chunk), initial),
            (template.plan_repair(snapshot, chunk, repair_request), repaired),
        )
    )
    bundle = bundle_type(ReplayProvider(entries), policy)
    control = RunControlV1(
        budget=ReviewBudgetV1(max_reviews=2, max_fixes=1), provider_execution=bundle.provider_execution()
    )
    return bundle, control


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_concurrency_limit_and_chunk_state_isolation(workers):
    barrier = Barrier(workers, timeout=5)
    lock = Lock()
    active = 0
    peak = 0
    instances = []

    class ConcurrentInventoryBundle(InventoryBundleV1):
        def extract(self, chunk):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                instances.append(self)
            try:
                barrier.wait()
                return super().extract(chunk)
            finally:
                with lock:
                    active -= 1

    chunks = tuple(_chunk(i) for i in range(workers * 2))
    results = run_chunks_v1(
        chunks=iter(chunks),
        prepare=lambda chunk: _prepare(chunk, ConcurrentInventoryBundle),
        max_workers=workers,
    )

    assert peak == workers
    assert active == 0
    assert len({id(bundle) for bundle in instances}) == len(chunks)
    assert len({id(bundle.provider) for bundle in instances}) == len(chunks)
    assert all(bundle.provider.remaining == 0 for bundle in instances)
    assert tuple(item.chunk for item in results) == chunks
    for item in results:
        result = item.result
        assert result.intent.kind is TerminalKind.FINAL
        assert result.budget.reviews_used == 2
        assert result.budget.fixes_used == 1
        assert result.current_graph.revision == 1
        assert result.artifact.graph == {"items": ({"sku": item.chunk.chunk_id, "count": item.chunk.ordinal + 1},)}
        assert [event.graph_revision for event in result.trace.events if event.stage == "review"] == [0, 1]


def test_results_keep_input_order_when_later_chunk_finishes_first():
    later_finished = Event()
    gate_order = []
    chunks = (_chunk(9), _chunk(2), _chunk(5))

    class OutOfOrderBundle(InventoryBundleV1):
        def extract(self, chunk):
            if chunk is chunks[0]:
                assert later_finished.wait(timeout=5)
            return super().extract(chunk)

        def final_gate(self, graph, chunk, validation, identity, review):
            gate = super().final_gate(graph, chunk, validation, identity, review)
            gate_order.append(chunk.chunk_id)
            if chunk is chunks[1]:
                later_finished.set()
            return gate

    results = run_chunks_v1(chunks=chunks, prepare=lambda chunk: _prepare(chunk, OutOfOrderBundle), max_workers=2)
    assert gate_order[0] == chunks[1].chunk_id
    assert tuple(item.chunk for item in results) == chunks
    assert all(item.result.intent.kind is TerminalKind.FINAL for item in results)


def test_batch_collects_all_terminal_kinds_despite_a_failed_chunk():
    class FailingInventoryBundle(InventoryBundleV1):
        def extract(self, chunk):
            if chunk.ordinal == 1:
                raise RuntimeError("fixture provider failure")
            return super().extract(chunk)

    def prepare(chunk):
        disposition = {3: GateDisposition.HOLD, 4: GateDisposition.BLOCK}.get(chunk.ordinal, GateDisposition.PASS)
        return _prepare(chunk, FailingInventoryBundle, InventoryPolicyV1(gate_disposition=disposition))

    results = run_chunks_v1(chunks=(_chunk(i) for i in range(5)), prepare=prepare, max_workers=2)
    assert [item.result.intent.kind for item in results] == [
        TerminalKind.FINAL,
        TerminalKind.FAILED,
        TerminalKind.FINAL,
        TerminalKind.CANDIDATE,
        TerminalKind.BLOCKED,
    ]
    assert results[1].result.intent.reason_code == "extract_failed"
    assert results[1].result.artifact.graph is None
    assert results[1].result.budget.reviews_used == 0


def test_batch_preserves_single_chunk_artifacts():
    chunks = (_chunk(0), _chunk(1), _chunk(2))
    expected = []
    for chunk in chunks:
        bundle, control = _prepare(chunk)
        expected.append(ExtractionEngineV1().run(bundle=bundle, chunk=chunk, control=control).artifact)
    for workers in (1, 3):
        results = run_chunks_v1(chunks=chunks, prepare=_prepare, max_workers=workers)
        assert [item.result.artifact for item in results] == expected


def test_empty_batch_does_not_prepare_chunks():
    def unexpected_prepare(chunk):
        pytest.fail("empty batch must not invoke prepare")

    assert run_chunks_v1(chunks=(), prepare=unexpected_prepare) == ()


def test_preparation_errors_propagate():
    def broken_prepare(chunk):
        raise ValueError("invalid bundle configuration")

    with pytest.raises(ValueError, match="invalid bundle configuration"):
        run_chunks_v1(chunks=(_chunk(0),), prepare=broken_prepare)


@pytest.mark.parametrize("workers", [0, -1])
def test_invalid_concurrency_is_rejected(workers):
    with pytest.raises(ValueError):
        run_chunks_v1(chunks=(), prepare=_prepare, max_workers=workers)
