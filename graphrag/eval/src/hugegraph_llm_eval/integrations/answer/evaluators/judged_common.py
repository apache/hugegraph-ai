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

"""Shared record lifecycle for multi-call judged answer metrics."""

from collections.abc import Callable
from datetime import datetime

from pydantic import JsonValue

from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationInput,
    EvaluationRecordDraft,
    Finding,
    Measurement,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.evaluation.judges.base import Judge
from hugegraph_llm_eval.evaluation.judges.batching import BatchingOptions
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.lifecycle import JudgedEvaluatorLifecycle
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.answer.materializers import (
    ANSWER_COMPARISON_INPUT_SCHEMA,
    AnswerArtifactMaterializer,
    AnswerMaterializationError,
)
from hugegraph_llm_eval.integrations.answer.schemas import AnswerComparisonInput
from hugegraph_llm_eval.prompt import answer_judge_prompt, answer_judge_prompt_digest


class JudgedAnswerEvaluator(JudgedEvaluatorLifecycle):
    def __init__(
        self,
        materializer: AnswerArtifactMaterializer,
        *,
        invocation_key: str,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        use_default_task_prompts: bool = False,
        batching: BatchingOptions | None = None,
    ) -> None:
        self._materializer = materializer
        self._use_default_task_prompts = use_default_task_prompts
        implementation: dict[str, JsonValue] = {
            "use_default_task_prompts": use_default_task_prompts,
            "claim_evidence_version": 1,
        }
        if use_default_task_prompts:
            implementation["default_prompt_digest"] = answer_judge_prompt_digest()
        super().__init__(
            namespace="answer",
            invocation_key=invocation_key,
            input_schema=ANSWER_COMPARISON_INPUT_SCHEMA,
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
            implementation=implementation,
            batching=batching,
        )

    def materialize(self, evaluation_input: EvaluationInput) -> AnswerComparisonInput | EvaluationRecordDraft:
        try:
            return self._materializer.comparison(evaluation_input)
        except AnswerMaterializationError as exc:
            return self.failure("answer_materialization_failed", str(exc), FailureCategory.INVALID_INPUT)

    def completed(
        self,
        measurements: tuple[Measurement, ...],
        findings: tuple[Finding, ...],
        reason: str,
        session: JudgeSession,
    ) -> EvaluationRecordDraft:
        return self.completed_record(measurements, findings, reason, session)

    def request_for_task(self, task: str, output_type, payload):
        """Build a request using the default Chinese few-shot prompt for an answer-judge task."""
        if not self._use_default_task_prompts:
            return self.request(output_type, payload)
        prompt = JudgeContent(
            component=ComponentRef(namespace="answer", name=f"{task}_prompt", revision="zh-v1"),
            text=answer_judge_prompt(task),
        )
        return self.request(output_type, payload, prompt=prompt)

    def not_applicable(self, reason: str, session: JudgeSession) -> EvaluationRecordDraft:
        return self.not_applicable_record(reason, session)


def reference_text(value: AnswerComparisonInput) -> str:
    return "\n\n".join(f"Reference {index + 1}: {text}" for index, text in enumerate(value.reference.answers))
