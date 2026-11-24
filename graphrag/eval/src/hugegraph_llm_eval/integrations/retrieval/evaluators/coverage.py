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

"""LLM-judged context entity recall and evidence attribution Evaluators."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from pydantic import Field, model_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvidenceLink,
    Finding,
    FindingSeverity,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.evaluation.judges.base import Judge, JudgeCallError
from hugegraph_llm_eval.evaluation.judges.batching import BatchingOptions, BatchInputError, payload_batches
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.retrieval.evaluators.judged_common import (
    JudgedRetrievalEvaluator,
    indexed,
    ratio,
    require_unique_indices,
    subject,
)
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer
from hugegraph_llm_eval.utils.text_preview import text_preview

_ENTITY_EXTRACTION_INSTRUCTION = (
    "Extract every distinct entity from reference_answer, without deciding whether it is covered. "
    'Return only {"entities": ["entity name"]}; preserve named entities, include unsupported ones, '
    "and do not invent entities. The caller will freeze this inventory before evaluating retrieval."
)
_ENTITY_COVERAGE_INSTRUCTION = (
    "The supplied entities are the fixed reference inventory. Return has_reference_entities and verdicts. "
    "For EVERY supplied entity_index return exactly one verdict with the same entity text, covered and reason. "
    "Do not add, remove, rename or renumber entities, including those not covered by any retrieved context."
)


class ReferenceEntitiesOutput(StrictModel):
    entities: tuple[Annotated[str, Field(min_length=1, max_length=4_000)], ...]

    @model_validator(mode="after")
    def _unique_entities(self) -> "ReferenceEntitiesOutput":
        if len(self.entities) != len(set(self.entities)):
            raise ValueError("reference entity inventory must be unique")
        return self


class ContextEntityVerdict(StrictModel):
    """LLM verdict for one answer entity against all retrieved contexts."""

    entity_index: int = Field(ge=0)
    entity: str = Field(min_length=1, max_length=4_000)
    covered: bool
    reason: str = Field(min_length=1, max_length=4_000)


class ContextEntityRecallOutput(StrictModel):
    """Semantic coverage judgements against a fixed reference entity inventory."""

    has_reference_entities: bool
    verdicts: tuple[ContextEntityVerdict, ...]

    @model_validator(mode="after")
    def _complete_entity_decision(self) -> "ContextEntityRecallOutput":
        require_unique_indices(tuple(item.entity_index for item in self.verdicts))
        if self.has_reference_entities != bool(self.verdicts):
            raise ValueError("entity verdicts must agree with has_reference_entities")
        return self


class EvidenceVerdict(StrictModel):
    evidence_index: int = Field(ge=0)
    attributed: bool
    reason: str = Field(min_length=1, max_length=4_000)


class EvidenceRecallOutput(StrictModel):
    verdicts: tuple[EvidenceVerdict, ...]

    @model_validator(mode="after")
    def _unique_indices(self) -> "EvidenceRecallOutput":
        require_unique_indices(tuple(item.evidence_index for item in self.verdicts))
        return self


class ContextEntityRecallEvaluator(JudgedRetrievalEvaluator):
    def __init__(
        self,
        materializer: RetrievalArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        batching: BatchingOptions | None = None,
    ) -> None:
        super().__init__(
            materializer,
            invocation_key="context_entity_recall_llm",
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
            batching=batching,
            implementation={
                "entity_protocol": "fixed-inventory-v1",
                "inventory_prompt": _ENTITY_EXTRACTION_INSTRUCTION,
                "coverage_prompt": _ENTITY_COVERAGE_INSTRUCTION,
            },
        )

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        value = self.materialize(evaluation_input)
        if isinstance(value, EvaluationRecordDraft):
            return value
        session = self.session(context)
        supplied = value.reference.entities is not None
        entities = value.reference.entities
        try:
            if entities is None:
                entities = self._reference_entities(value.reference.answer, session)
            if not entities:
                return self.not_applicable_record("reference entity inventory is empty; recall is undefined", session)
            verdicts: list[ContextEntityVerdict] = []
            batches = payload_batches(
                tuple(enumerate(entities)),
                lambda items: {
                    "question": value.query.question,
                    "entities": [{"entity_index": index, "text": text} for index, text in items],
                    "contexts": indexed(value.candidate.contexts, "context_index"),
                },
                self._batching,
            )
            for ordinal, (items, payload) in enumerate(batches):
                key = "judge_entity_coverage" if ordinal == 0 else f"judge_entity_coverage_{ordinal}"
                output = session.call(
                    key,
                    self.request(
                        ContextEntityRecallOutput,
                        payload,
                        prompt=self._entity_prompt("coverage", _ENTITY_COVERAGE_INSTRUCTION),
                    ),
                )
                expected = dict(items)
                if {item.entity_index for item in output.verdicts} != set(expected) or any(
                    expected.get(item.entity_index) != item.entity for item in output.verdicts
                ):
                    return self.failure(
                        "incomplete_context_entity_verdicts",
                        "entity coverage must preserve every supplied entity and its global index",
                        FailureCategory.INVALID_PROVIDER_OUTPUT,
                        calls=session.calls,
                    )
                verdicts.extend(output.verdicts)
        except JudgeCallError as exc:
            return self.judge_failure(exc, session)
        except BatchInputError as exc:
            return self.failure(
                "evaluation_payload_too_large",
                str(exc),
                FailureCategory.RESOURCE_EXHAUSTED,
                calls=session.calls,
            )
        ordered = sorted(verdicts, key=lambda item: item.entity_index)
        covered = sum(item.covered for item in ordered)
        artifact = subject(evaluation_input, "retrieval_reference")
        source = "supplied" if supplied else "model-extracted"
        return self.completed(
            ratio("context_entity_recall_llm", round(covered / len(entities), 4)),
            _entity_findings(ordered, artifact, supplied=supplied),
            f"retrieved contexts cover {covered} of {len(entities)} entities in the fixed {source} inventory",
            session,
        )

    def _reference_entities(self, answer: str, session: JudgeSession) -> tuple[str, ...]:
        if not answer.strip():
            return ()
        batches = payload_batches((answer,), lambda items: {"reference_answer": items[0]}, self._batching)
        _, payload = next(batches)
        output = session.call(
            "extract_reference_entities",
            self.request(
                ReferenceEntitiesOutput,
                payload,
                prompt=self._entity_prompt("inventory", _ENTITY_EXTRACTION_INSTRUCTION),
            ),
        )
        return output.entities

    def _entity_prompt(self, task: str, instruction: str) -> JudgeContent:
        return JudgeContent(
            component=ComponentRef(namespace="retrieval", name=f"entity_{task}", revision="v1"),
            text=f"{self._prompt.text}\n\n{instruction}",
        )


def _entity_findings(
    verdicts: list[ContextEntityVerdict],
    artifact: ArtifactRef,
    *,
    supplied: bool,
) -> tuple[Finding, ...]:
    """Render entity-coverage verdicts as item-level findings."""
    return tuple(
        Finding(
            code="context_entity_recall.covered" if verdict.covered else "context_entity_recall.missing",
            severity=FindingSeverity.INFO if verdict.covered else FindingSeverity.ERROR,
            message=text_preview(f"{verdict.entity}: {verdict.reason}", 4_000),
            evidence=(
                EvidenceLink(
                    artifact=artifact,
                    locator=(
                        f"entities[{verdict.entity_index}]" if supplied else f"answer.entity[{verdict.entity_index}]"
                    ),
                    description=text_preview(verdict.entity, 2_000),
                ),
            ),
        )
        for verdict in verdicts
    )


class EvidenceRecallEvaluator(JudgedRetrievalEvaluator):
    def __init__(
        self,
        materializer: RetrievalArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        batching: BatchingOptions | None = None,
    ) -> None:
        super().__init__(
            materializer,
            invocation_key="evidence_recall_llm",
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
            batching=batching,
        )

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        value = self.materialize(evaluation_input)
        if isinstance(value, EvaluationRecordDraft):
            return value
        session = self.session(context)
        evidence = value.reference.evidence
        artifact = subject(evaluation_input, "retrieval_reference")
        if not evidence:
            return self.completed(ratio("evidence_recall_llm", 1), (), "no reference evidence", session)
        if not value.candidate.contexts:
            findings = tuple(
                _finding(EvidenceVerdict(evidence_index=index, attributed=False, reason="no contexts"), artifact)
                for index in range(len(evidence))
            )
            return self.completed(ratio("evidence_recall_llm", 0), findings, "no retrieved contexts", session)
        verdicts: list[EvidenceVerdict] = []
        try:
            batches = payload_batches(
                tuple(enumerate(evidence)),
                lambda items: {
                    "question": value.query.question,
                    "contexts": list(value.candidate.contexts),
                    "evidence": [{"evidence_index": index, "text": text} for index, text in items],
                },
                self._batching,
            )
            for ordinal, (items, payload) in enumerate(batches):
                key = "verify_evidence" if ordinal == 0 else f"verify_evidence_{ordinal}"
                output = session.call(key, self.request(EvidenceRecallOutput, payload))
                if {item.evidence_index for item in output.verdicts} != {index for index, _ in items}:
                    return self.failure(
                        "incomplete_evidence_verdicts",
                        "evidence judge must cover exactly the supplied batch",
                        FailureCategory.INVALID_PROVIDER_OUTPUT,
                        calls=session.calls,
                    )
                verdicts.extend(output.verdicts)
        except JudgeCallError as exc:
            return self.judge_failure(exc, session)
        except BatchInputError as exc:
            return self.failure(
                "evaluation_payload_too_large",
                str(exc),
                FailureCategory.RESOURCE_EXHAUSTED,
                calls=session.calls,
            )
        ordered = sorted(verdicts, key=lambda item: item.evidence_index)
        attributed = sum(item.attributed for item in ordered)
        return self.completed(
            ratio("evidence_recall_llm", round(attributed / len(ordered), 4)),
            tuple(_finding(item, artifact) for item in ordered),
            f"retrieved contexts support {attributed} of {len(ordered)} reference evidence statements",
            session,
        )


def _finding(verdict: EvidenceVerdict, artifact: ArtifactRef) -> Finding:
    return Finding(
        code="evidence_recall.supported" if verdict.attributed else "evidence_recall.missing",
        severity=FindingSeverity.INFO if verdict.attributed else FindingSeverity.ERROR,
        message=verdict.reason,
        evidence=(EvidenceLink(artifact=artifact, locator=f"evidence[{verdict.evidence_index}]"),),
    )
