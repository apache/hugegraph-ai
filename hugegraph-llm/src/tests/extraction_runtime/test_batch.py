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

from hugegraph_llm.extraction_runtime.v1 import ChunkInput, ExtractionOptions, run_chunks_v1
from tests.extraction_runtime._bundles import ScriptedBundle

pytestmark = pytest.mark.unit


def test_batch_keeps_input_order_and_limits_whole_chunk_concurrency():
    barrier = Barrier(2, timeout=5)
    lock = Lock()
    active = peak = 0
    completed = []
    release_first = Event()

    class ConcurrentBundle(ScriptedBundle):
        def extract(self, chunk):
            barrier.wait()
            return super().extract(chunk)

        def review(self, graph, chunk):
            nonlocal active
            if chunk.index == 9:
                assert release_first.wait(5)
            result = super().review(graph, chunk)
            with lock:
                completed.append(chunk.index)
                active -= 1
            if chunk.index == 3:
                release_first.set()
            return result

    def prepare(chunk):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        return ConcurrentBundle()

    results = run_chunks_v1(
        chunks=[ChunkInput(i, "text") for i in (9, 3, 6, 0)], prepare=prepare, options=ExtractionOptions(max_workers=2)
    )
    assert [result.index for result in results] == [9, 3, 6, 0]
    assert completed[0] == 3
    assert peak == 2 and active == 0
    assert all(result.status == "final" for result in results)
    assert [result.graph["chunk"] for result in results] == [9, 3, 6, 0]


def test_preparation_and_model_failures_do_not_discard_other_chunks():
    def prepare(chunk):
        if chunk.index == 1:
            raise RuntimeError("cannot construct client")
        return ScriptedBundle(fail_at="review" if chunk.index == 2 else None)

    results = run_chunks_v1(
        chunks=[ChunkInput(i, "text") for i in range(4)], prepare=prepare, options=ExtractionOptions(max_workers=2)
    )
    assert [result.status for result in results] == ["final", "failed", "failed", "final"]
    assert results[1].stage == "prepare" and results[1].graph is None
    assert results[1].llm_calls == results[1].reviews_used == results[1].fixes_used == 0
    assert results[2].stage == "review" and results[2].llm_calls == 2


def test_parallel_repairs_keep_graphs_issues_and_budgets_local():
    results = run_chunks_v1(
        chunks=[ChunkInput(i, "text") for i in range(5)],
        prepare=lambda chunk: ScriptedBundle(
            initial=chunk.index, repaired=100 + chunk.index, decisions=("fix", "pass")
        ),
        options=ExtractionOptions(max_workers=3),
    )
    assert [result.graph["value"] for result in results] == list(range(100, 105))
    assert all((result.reviews_used, result.fixes_used, result.llm_calls) == (2, 1, 4) for result in results)
    assert all(result.status == "final" and result.issues == [] for result in results)


def test_serial_batch_and_empty_input():
    seen = []

    def prepare(chunk):
        seen.append(chunk.index)
        return ScriptedBundle()

    options = ExtractionOptions(max_workers=1)
    assert run_chunks_v1(chunks=[], prepare=prepare, options=options) == ()
    results = run_chunks_v1(chunks=[ChunkInput(2, "b"), ChunkInput(1, "a")], prepare=prepare, options=options)
    assert seen == [2, 1] and [result.index for result in results] == [2, 1]


def test_input_iteration_errors_propagate_after_started_work_finishes():
    completed = Event()

    class CompletingBundle(ScriptedBundle):
        def review(self, graph, chunk):
            result = super().review(graph, chunk)
            completed.set()
            return result

    def chunks():
        yield ChunkInput(0, "text")
        raise ValueError("broken input iterator")

    with pytest.raises(ValueError, match="broken input iterator"):
        run_chunks_v1(
            chunks=chunks(), prepare=lambda chunk: CompletingBundle(), options=ExtractionOptions(max_workers=1)
        )
    assert completed.is_set()
