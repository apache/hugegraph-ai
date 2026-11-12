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

"""Nested semantic batches obey the run limiter, cancellation and deadline."""

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from support import extraction_input as _extraction_input
from support import make_store as _store

from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationContext, EvaluationRecordStatus
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeProvenance,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderUsage,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.contracts.identity import ComponentRef, EvaluationRunId
from hugegraph_llm_eval.evaluation.judges.base import JudgeDescriptor, JudgeOptions, JudgeRequest, JudgeResult
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.limits import SemaphoreLimiter
from hugegraph_llm_eval.evaluation.options import CancellationToken
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic import (
    SemanticEntityEvaluator,
    SemanticVerdict,
    SemanticVerdictOutput,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer

pytest.importorskip("networkx", reason="install hugegraph-llm-eval[graph] to run semantic matching contracts")


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 25, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class _CountingJudge:
    """Thread-safe judge that records the peak number of concurrent calls."""

    def __init__(self, delay: float = 0.0) -> None:
        self.descriptor = JudgeDescriptor.create(provider="probe", model="judge", configuration={"temperature": 0})
        self.delay = delay
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.calls = 0

    def judge(self, request: JudgeRequest, options: JudgeOptions) -> JudgeResult:
        del options
        with self.lock:
            self.calls += 1
            call_index = self.calls
            self.current += 1
            self.peak = max(self.peak, self.current)
        try:
            time.sleep(self.delay)
            output = _verdicts(call_index)
        finally:
            with self.lock:
                self.current -= 1
        return _result(request, output)


class _BlockingJudge(_CountingJudge):
    """Signal the first call, then wait for the test to release it."""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def judge(self, request: JudgeRequest, options: JudgeOptions) -> JudgeResult:
        self.started.set()
        self.release.wait(5)
        return super().judge(request, options)


class _AdvancingJudge(_CountingJudge):
    """Move the evaluator clock past the deadline after the first call."""

    def __init__(self, clock: _Clock, deadline: datetime) -> None:
        super().__init__()
        self.clock = clock
        self.deadline = deadline

    def judge(self, request: JudgeRequest, options: JudgeOptions) -> JudgeResult:
        result = super().judge(request, options)
        self.clock.now = self.deadline + timedelta(seconds=1)
        return result


def _verdicts(call_index: int) -> SemanticVerdictOutput:
    return SemanticVerdictOutput(
        verdicts=tuple(
            SemanticVerdict(
                reference_index=index,
                candidate_index=None,
                match_score=None,
                match_issues=("no_semantic_match",),
                reason=f"call {call_index} found no match",
            )
            for index in (0, 1)
        )
    )


def _result(request: JudgeRequest, output: SemanticVerdictOutput) -> JudgeResult:
    usage = ProviderUsage(
        provider="probe",
        model="judge",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        cost_usd=0.0,
    )
    descriptor = JudgeDescriptor.create(provider="probe", model="judge", configuration={"temperature": 0})
    provenance = JudgeProvenance(
        provider="probe",
        model="judge",
        configuration_digest=descriptor.configuration_digest,
        prompt=request.prompt,
        rubric=request.rubric,
        attempts=(
            ProviderAttempt(
                attempt_index=1,
                provider="probe",
                model="judge",
                status=ProviderAttemptStatus.COMPLETED,
                latency_ms=0,
                usage=usage,
            ),
        ),
    )
    return JudgeResult(output=output, provenance=provenance, usage=usage)


def _content() -> JudgeContent:
    return JudgeContent(component=ComponentRef(namespace="test", name="prompt", revision="v1"), text="match entities")


def _evaluator(store, judge, clock) -> SemanticEntityEvaluator:
    return SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content(),
        rubric=_content(),
        clock=clock,
    )


def _input(store, candidates: int = 300):
    candidate = {"vertices": [{"label": "Person", "name": f"p-{i}"} for i in range(candidates)], "edges": []}
    reference = {"vertices": [{"label": "Person", "name": "p-0"}, {"label": "Person", "name": "p-1"}], "edges": []}
    return _extraction_input(store, candidate_payload=candidate, reference_payload=reference)


def _context(*, max_concurrency: int, cancellation: CancellationToken | None = None) -> EvaluationContext:
    return EvaluationContext(
        run_id=EvaluationRunId.new(),
        request_key="semantic-concurrency",
        deadline=None,
        cancellation=cancellation or CancellationToken(),
        max_concurrency=max_concurrency,
        limiter=SemaphoreLimiter(max_concurrency),
    )


def test_nested_batches_never_exceed_the_run_limiter() -> None:
    store = _store()
    judge = _CountingJudge(delay=0.1)
    context = _context(max_concurrency=2)

    first = _evaluator(store, judge, _Clock()).evaluate(_input(store), context)
    second = _evaluator(store, judge, _Clock()).evaluate(_input(store), context)

    assert first.status is EvaluationRecordStatus.COMPLETED
    assert second.status is EvaluationRecordStatus.COMPLETED
    assert judge.calls == 4
    assert judge.peak <= 2


def test_cancellation_between_batches_cancels_the_record() -> None:
    store = _store()
    judge = _BlockingJudge()
    token = CancellationToken()
    context = _context(max_concurrency=1, cancellation=token)
    evaluator = _evaluator(store, judge, _Clock())

    threading.Timer(0.1, lambda: _cancel_after_first_call(judge, token)).start()
    draft = evaluator.evaluate(_input(store), context)

    assert draft.status is EvaluationRecordStatus.CANCELLED
    assert draft.failure is not None
    assert draft.failure.category is FailureCategory.CANCELLED
    assert judge.calls == 1


def _cancel_after_first_call(judge: _BlockingJudge, token: CancellationToken) -> None:
    assert judge.started.wait(5)
    token.cancel("operator stopped the run")
    judge.release.set()


def test_deadline_between_batches_fails_the_record() -> None:
    store = _store()
    clock = _Clock()
    deadline = clock.now + timedelta(seconds=30)
    judge = _AdvancingJudge(clock, deadline)
    context = EvaluationContext(
        run_id=EvaluationRunId.new(),
        request_key="semantic-deadline",
        deadline=deadline,
        cancellation=CancellationToken(),
        max_concurrency=1,
        limiter=SemaphoreLimiter(1),
    )

    draft = _evaluator(store, judge, clock).evaluate(_input(store), context)

    assert draft.status is EvaluationRecordStatus.FAILED
    assert draft.failure is not None
    assert draft.failure.category is FailureCategory.TIMEOUT
    assert judge.calls == 1
