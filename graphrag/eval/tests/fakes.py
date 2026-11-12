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

"""Strict test doubles for the Evaluation boundary."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from hugegraph_llm_eval.contracts.digests import ContentDigest
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluationSubject,
    EvaluatorDescriptor,
    Measurement,
)
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeProvenance,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderUsage,
)
from hugegraph_llm_eval.contracts.domain.operation import PortName
from hugegraph_llm_eval.contracts.identity import EvaluatorRef, SchemaRef
from hugegraph_llm_eval.evaluation.judges.base import (
    JudgeDescriptor,
    JudgeOptions,
    JudgeRequest,
    JudgeResult,
)

NOW = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
INPUT_SCHEMA = SchemaRef(namespace="test", name="artifact_input", version=1)
OUTPUT_SCHEMA = SchemaRef(namespace="test", name="record", version=1)


@dataclass
class ScriptedJudge:
    """ScriptedJudge."""

    outputs: tuple[BaseModel, ...]

    def __post_init__(self) -> None:
        """__post_init__."""
        self.descriptor = JudgeDescriptor.create(provider="test", model="judge", configuration={"temperature": 0})
        self._outputs = deque(self.outputs)
        self.requests: list[JudgeRequest[Any]] = []

    def judge(self, request: JudgeRequest[Any], options: JudgeOptions) -> JudgeResult[Any]:
        """judge."""
        del options
        self.requests.append(request)
        usage = ProviderUsage(
            provider="test",
            model="judge",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cost_usd=0.001,
        )
        provenance = JudgeProvenance(
            provider="test",
            model="judge",
            configuration_digest=self.descriptor.configuration_digest,
            prompt=request.prompt,
            rubric=request.rubric,
            attempts=(
                ProviderAttempt(
                    attempt_index=1,
                    provider="test",
                    model="judge",
                    status=ProviderAttemptStatus.COMPLETED,
                    latency_ms=3,
                    usage=usage,
                ),
            ),
            response_id=f"response-{len(self.requests)}",
        )
        return JudgeResult(output=self._outputs.popleft(), provenance=provenance, usage=usage)


def artifact() -> ArtifactRef:
    """artifact."""
    return ArtifactRef.from_json(
        {"value": 1},
        schema_namespace="test",
        schema_name="candidate",
        created_at=NOW,
    )


def evaluation_input() -> EvaluationInput:
    """evaluation_input."""
    return EvaluationInput.create(
        schema_ref=INPUT_SCHEMA,
        subjects=(EvaluationSubject(port=PortName(value="candidate"), artifact=artifact()),),
    )


class FakeEvaluator:
    """FakeEvaluator."""

    input_type = EvaluationInput

    def __init__(
        self,
        name: str,
        outcome: Callable[[EvaluationInput, EvaluationContext], EvaluationRecordDraft] | None = None,
        *,
        implementation: str = "a",
    ) -> None:
        """__init__."""
        self.descriptor = EvaluatorDescriptor(
            evaluator=EvaluatorRef(namespace="test", name=name, revision="v1"),
            implementation_digest=ContentDigest(value="sha256:" + implementation * 64),
            input_schema=INPUT_SCHEMA,
            output_schema=OUTPUT_SCHEMA,
        )
        self.calls = 0
        self.contexts: list[EvaluationContext] = []
        self._outcome = outcome or self._completed

    @property
    def invocation_key(self) -> str:
        return self.descriptor.evaluator.name

    def evaluate(
        self,
        evaluation_input: EvaluationInput,
        context: EvaluationContext,
    ) -> EvaluationRecordDraft:
        """evaluate."""
        self.calls += 1
        self.contexts.append(context)
        return self._outcome(evaluation_input, context)

    def _completed(
        self,
        _evaluation_input: EvaluationInput,
        _context: EvaluationContext,
    ) -> EvaluationRecordDraft:
        """_completed."""
        return EvaluationRecordDraft(
            invocation_key=self.descriptor.evaluator.name,
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.COMPLETED,
            measurements=(Measurement(name="quality", value=1.0, unit="ratio"),),
            reason="evaluation completed",
            attempts=1,
            latency_ms=1,
            created_at=NOW,
        )
