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

"""Deterministic stand-in for a judge model, used by the offline examples."""

import json
from typing import Any

from hugegraph_llm_eval import JudgeDescriptor, JudgeOptions, JudgeRequest, JudgeResult
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeProvenance,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderUsage,
)

PROVIDER = "stand-in"
MODEL = "rule-based"


class StandInJudge:
    """Answer every judged metric with one fixed, schema-valid opinion."""

    def __init__(self) -> None:
        self.descriptor = JudgeDescriptor.create(
            provider=PROVIDER,
            model=MODEL,
            configuration={"temperature": 0},
        )

    def judge(self, request: JudgeRequest[Any], options: JudgeOptions) -> JudgeResult[Any]:
        del options
        payload = json.loads(request.messages[-1].content)
        output = request.response_type.model_validate(_answer(request.response_type.__name__, payload))
        usage = ProviderUsage(
            provider=PROVIDER,
            model=MODEL,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            cost_usd=0.0,
        )
        provenance = JudgeProvenance(
            provider=PROVIDER,
            model=MODEL,
            configuration_digest=self.descriptor.configuration_digest,
            prompt=request.prompt,
            rubric=request.rubric,
            attempts=(
                ProviderAttempt(
                    attempt_index=1,
                    provider=PROVIDER,
                    model=MODEL,
                    status=ProviderAttemptStatus.COMPLETED,
                    latency_ms=0,
                    usage=usage,
                ),
            ),
        )
        return JudgeResult(output=output, provenance=provenance, usage=usage)


def _answer(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if name == "ClaimDecompositionOutput":
        return {"claims": [payload["text"]]}
    if name == "NLIVerdictsOutput":
        return {
            "verdicts": [
                {"statement_index": item["statement_index"], "entailed": True, "reason": "stated by the context"}
                for item in payload["statements"]
            ]
        }
    if name == "CorrectnessOutput":
        return _correctness(payload)
    if name == "ContextPrecisionOutput":
        return {
            "verdicts": [
                {"context_index": item["context_index"], "relevant": True, "reason": "relevant to the question"}
                for item in payload["contexts"]
            ]
        }
    if name == "ContextRelevancyOutput":
        return {
            "verdicts": [
                {"context_index": item["context_index"], "score": 2, "reason": "answers the question"}
                for item in payload["contexts"]
            ]
        }
    if name == "ReferenceEntitiesOutput":
        return {"entities": ["auth tokens"]}
    if name == "ContextEntityRecallOutput":
        return {
            "has_reference_entities": True,
            "verdicts": [
                {"entity_index": item["entity_index"], "entity": item["text"], "covered": True, "reason": "present"}
                for item in payload["entities"]
            ],
        }
    if name == "EvidenceRecallOutput":
        return {
            "verdicts": [
                {"evidence_index": item["evidence_index"], "attributed": True, "reason": "supported by a context"}
                for item in payload["evidence"]
            ]
        }
    if name == "FaithfulnessJudgeOutput":
        return {
            "supported_vertex_indices": [
                item["item_index"] for item in payload["items"] if item["item_kind"] == "vertex"
            ],
            "supported_edge_indices": [item["item_index"] for item in payload["items"] if item["item_kind"] == "edge"],
        }
    if name == "SemanticVerdictOutput":
        return _semantic(payload)
    raise ValueError(f"stand-in judge does not know {name}")


def _correctness(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload["candidate"]
    reference = payload["reference"]
    paired = min(len(candidate), len(reference))
    return {
        "matches": [
            {
                "candidate_index": candidate[index]["statement_index"],
                "reference_index": reference[index]["statement_index"],
                "reason": "same claim",
            }
            for index in range(paired)
        ],
        "false_positives": [
            {"statement_index": item["statement_index"], "reason": "not in the reference"}
            for item in candidate[paired:]
        ],
        "false_negatives": [
            {"statement_index": item["statement_index"], "reason": "missing from the candidate"}
            for item in reference[paired:]
        ],
    }


def _semantic(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload["candidates"]
    verdicts = []
    for position, reference in enumerate(payload["references"]):
        candidate_index = candidates[position]["candidate_index"] if position < len(candidates) else None
        verdicts.append(
            {
                "reference_index": reference["reference_index"],
                "candidate_index": candidate_index,
                "match_score": 100.0 if candidate_index is not None else None,
                "match_issues": [] if candidate_index is not None else ["no_semantic_match"],
                "reason": "same item" if candidate_index is not None else "no equivalent item in this window",
            }
        )
    return {"verdicts": verdicts}
