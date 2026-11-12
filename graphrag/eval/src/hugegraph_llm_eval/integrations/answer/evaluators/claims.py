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

"""Typed claim decomposition and NLI steps shared by answer Evaluators."""

from pydantic import Field, model_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import EvidenceLink
from hugegraph_llm_eval.evaluation.judges.batching import BatchOutputError, payload_batches
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.answer.evaluators.judged_common import JudgedAnswerEvaluator
from hugegraph_llm_eval.utils.text_preview import text_preview


class ClaimDecompositionOutput(StrictModel):
    claims: tuple[str, ...]

    @model_validator(mode="after")
    def _non_empty_claims(self) -> "ClaimDecompositionOutput":
        if any(not claim.strip() for claim in self.claims):
            raise ValueError("decomposed claims must be non-empty")
        return self


class NLIVerdict(StrictModel):
    statement_index: int = Field(ge=0)
    entailed: bool
    reason: str = Field(min_length=1, max_length=4_000)


class NLIVerdictsOutput(StrictModel):
    verdicts: tuple[NLIVerdict, ...]

    @model_validator(mode="after")
    def _unique_indices(self) -> "NLIVerdictsOutput":
        indices = tuple(item.statement_index for item in self.verdicts)
        if len(indices) != len(set(indices)):
            raise ValueError("NLI verdict indices must be unique")
        return self


def decompose(
    evaluator: JudgedAnswerEvaluator,
    session: JudgeSession,
    call_key: str,
    question: str,
    text: str,
) -> tuple[str, ...]:
    return session.call(
        call_key,
        evaluator.request_for_task(
            "decompose",
            ClaimDecompositionOutput,
            {"task": "decompose_claims", "question": question, "text": text},
        ),
    ).claims


def verify(
    evaluator: JudgedAnswerEvaluator,
    session: JudgeSession,
    call_key: str,
    claims: tuple[str, ...],
    context: str,
) -> NLIVerdictsOutput:
    if not claims:
        return NLIVerdictsOutput(verdicts=())
    verdicts: list[NLIVerdict] = []
    batches = payload_batches(
        tuple(enumerate(claims)),
        lambda items: {
            "task": "verify_claims",
            "context": context,
            "statements": [{"statement_index": index, "text": claim} for index, claim in items],
        },
        evaluator._batching,
    )
    for ordinal, (items, payload) in enumerate(batches):
        key = call_key if ordinal == 0 else f"{call_key}_{ordinal}"
        output = session.call(key, evaluator.request_for_task("verify", NLIVerdictsOutput, payload))
        if {item.statement_index for item in output.verdicts} != {index for index, _ in items}:
            raise BatchOutputError("NLI judge must cover exactly the supplied claim indices in this batch")
        verdicts.extend(output.verdicts)
    return NLIVerdictsOutput(verdicts=tuple(verdicts))


def complete_verdicts(output: NLIVerdictsOutput, count: int) -> bool:
    indices = tuple(item.statement_index for item in output.verdicts)
    return set(indices) == set(range(count)) and len(indices) == count


def ordered_verdicts(output: NLIVerdictsOutput) -> tuple[NLIVerdict, ...]:
    return tuple(sorted(output.verdicts, key=lambda item: item.statement_index))


def claim_evidence(artifact: ArtifactRef, locator: str, claim: str) -> EvidenceLink:
    """Retain the judged claim because its generated index is not in the source artifact."""
    return EvidenceLink(artifact=artifact, locator=locator, description=text_preview(claim, 2_000))
