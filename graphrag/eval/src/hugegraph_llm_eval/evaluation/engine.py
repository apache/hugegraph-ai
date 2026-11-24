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

"""In-process evaluation execution with no persistence layer."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from hugegraph_llm_eval.contracts.digests import canonical_digest
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationDefinitionItem,
    EvaluationInput,
    EvaluationRecord,
    EvaluationRecordStatus,
    EvaluationRun,
    EvaluationRunStatus,
    Evaluator,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.contracts.identity import EvaluationRunId
from hugegraph_llm_eval.evaluation.executor import EvaluatorExecutor
from hugegraph_llm_eval.evaluation.limits import RunLimits
from hugegraph_llm_eval.evaluation.options import EvaluationOptions
from hugegraph_llm_eval.evaluation.resolution import ResolvedEvaluator
from hugegraph_llm_eval.utils.clock import utc_now


class MetricEvaluator(Evaluator[EvaluationInput], Protocol):
    """Evaluator that declares the invocation key its records will carry."""

    @property
    def invocation_key(self) -> str: ...


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Ordered records plus the aggregate run status."""

    run_id: EvaluationRunId
    status: EvaluationRunStatus
    records: tuple[EvaluationRecord, ...]

    @property
    def succeeded(self) -> bool:
        return self.status is EvaluationRunStatus.COMPLETED


class EvaluationEngine:
    """Run evaluators concurrently without a store, report, or CLI."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock
        self._executor = EvaluatorExecutor(clock=clock)

    def evaluate(
        self,
        evaluators: Sequence[MetricEvaluator],
        evaluation_input: EvaluationInput,
        options: EvaluationOptions,
        *,
        limits: RunLimits | None = None,
    ) -> EvaluationResult:
        if not evaluators:
            msg = "at least one evaluator is required"
            raise ValueError(msg)
        resolved = tuple(_resolve(evaluator) for evaluator in evaluators)
        run = _run(evaluation_input, resolved, options, self._clock())
        execution = self._executor.execute(
            resolved,
            evaluation_input,
            run,
            options,
            limits if limits is not None else RunLimits.for_options(options),
        )
        return EvaluationResult(
            run_id=run.run_id,
            status=_run_status(execution.records, execution.terminal_failure),
            records=execution.records,
        )


def _resolve(evaluator: MetricEvaluator) -> ResolvedEvaluator:
    descriptor = evaluator.descriptor
    return ResolvedEvaluator(
        item=EvaluationDefinitionItem(
            invocation_key=evaluator.invocation_key,
            evaluator=descriptor.evaluator,
            implementation_digest=descriptor.implementation_digest,
        ),
        evaluator=evaluator,
    )


def _run(
    evaluation_input: EvaluationInput,
    resolved: tuple[ResolvedEvaluator, ...],
    options: EvaluationOptions,
    now: datetime,
) -> EvaluationRun:
    return EvaluationRun(
        run_id=EvaluationRunId.new(),
        request_key=options.request_key,
        definition_digest=canonical_digest(
            {
                "items": [
                    {
                        "invocation_key": item.item.invocation_key,
                        "evaluator": item.item.evaluator.model_dump(mode="json"),
                        "implementation_digest": item.item.implementation_digest.value,
                    }
                    for item in resolved
                ]
            }
        ),
        input_digest=evaluation_input.digest,
        status=EvaluationRunStatus.RUNNING,
        required_count=len(resolved),
        completed_required_count=0,
        created_at=now,
    )


def _run_status(
    records: tuple[EvaluationRecord, ...],
    terminal_failure: FailureDetail | None,
) -> EvaluationRunStatus:
    satisfied = sum(
        1
        for record in records
        if record.status in (EvaluationRecordStatus.COMPLETED, EvaluationRecordStatus.NOT_APPLICABLE)
    )
    if satisfied == len(records):
        return EvaluationRunStatus.COMPLETED
    if satisfied:
        return EvaluationRunStatus.PARTIAL
    if terminal_failure is not None and terminal_failure.category is FailureCategory.CANCELLED:
        return EvaluationRunStatus.CANCELLED
    return EvaluationRunStatus.FAILED
