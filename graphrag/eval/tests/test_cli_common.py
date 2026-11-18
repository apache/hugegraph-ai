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

"""Prompt splitting and strict-schema helpers shared by the CLI-backed Judges."""

import pytest
from cli_support import CliVerdict, cli_request
from pydantic import BaseModel, Field

from hugegraph_llm_eval.evaluation.judges.base import JudgeMessage, JudgeRequest
from hugegraph_llm_eval.integrations.answer.evaluators.claims import ClaimDecompositionOutput, NLIVerdictsOutput
from hugegraph_llm_eval.integrations.answer.evaluators.correctness import CorrectnessOutput
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import FaithfulnessJudgeOutput
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic import SemanticVerdictOutput
from hugegraph_llm_eval.integrations.judges.cli_common import cli_version, split_messages, strict_json_schema
from hugegraph_llm_eval.integrations.retrieval.evaluators.context_quality import (
    ContextPrecisionOutput,
    ContextRelevancyOutput,
)
from hugegraph_llm_eval.integrations.retrieval.evaluators.coverage import (
    ContextEntityRecallOutput,
    EvidenceRecallOutput,
    ReferenceEntitiesOutput,
)

RESPONSE_TYPES = [
    ClaimDecompositionOutput,
    NLIVerdictsOutput,
    CorrectnessOutput,
    ContextPrecisionOutput,
    ContextRelevancyOutput,
    ContextEntityRecallOutput,
    EvidenceRecallOutput,
    ReferenceEntitiesOutput,
    SemanticVerdictOutput,
    FaithfulnessJudgeOutput,
]


def assert_strict(node: object) -> None:
    if isinstance(node, list):
        for child in node:
            assert_strict(child)
    elif isinstance(node, dict):
        if "properties" in node:
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])
        for key in ("default", "title"):
            assert key not in node
        for key, child in node.items():
            assert_strict(list(child.values()) if key in ("properties", "$defs") else child)


@pytest.mark.parametrize("response_type", RESPONSE_TYPES, ids=lambda t: t.__name__)
def test_every_real_response_schema_becomes_strict(response_type: type[BaseModel]) -> None:
    schema = strict_json_schema(response_type)

    assert_strict(schema)
    assert schema == strict_json_schema(response_type)


def test_nested_models_and_optional_fields_are_made_required() -> None:
    class Inner(BaseModel):
        value: int = Field(default=3, ge=0)

    class Outer(BaseModel):
        inner: Inner = Field(description="child")
        default: str | None = None
        tags: list[Inner] = Field(default_factory=list, max_length=4)

    schema = strict_json_schema(Outer)

    assert schema["required"] == ["inner", "default", "tags"]
    assert schema["properties"]["inner"] == {"$ref": "#/$defs/Inner"}
    assert schema["$defs"]["Inner"]["required"] == ["value"]
    assert schema["$defs"]["Inner"]["additionalProperties"] is False
    assert schema["properties"]["tags"]["maxItems"] == 4
    assert schema["$defs"]["Inner"]["properties"]["value"]["minimum"] == 0
    assert "default" in schema["properties"]
    assert_strict(schema)


def test_single_user_message_is_the_prompt_and_system_text_is_separate() -> None:
    assert split_messages(cli_request("ok", system="Be strict.")) == (
        "Be strict.",
        "Is the claim supported? [scenario:ok]",
    )
    assert split_messages(cli_request("ok", system=None))[0] is None


def test_multi_turn_conversations_keep_their_roles() -> None:
    request = JudgeRequest(
        messages=(
            JudgeMessage(role="system", content="S1"),
            JudgeMessage(role="system", content="S2"),
            JudgeMessage(role="user", content="question"),
            JudgeMessage(role="assistant", content="draft"),
            JudgeMessage(role="user", content="final"),
        ),
        response_type=CliVerdict,
        prompt=cli_request().prompt,
        rubric=cli_request().rubric,
    )

    system, prompt = split_messages(request)

    assert system == "S1\n\nS2"
    assert prompt == "[user]\nquestion\n\n[assistant]\ndraft\n\n[user]\nfinal"


def test_system_only_request_uses_the_system_text_as_the_prompt() -> None:
    request = JudgeRequest(
        messages=(JudgeMessage(role="system", content="only"),),
        response_type=CliVerdict,
        prompt=cli_request().prompt,
        rubric=cli_request().rubric,
    )

    assert split_messages(request) == (None, "only")


def test_missing_executable_fails_fast_with_guidance() -> None:
    with pytest.raises(RuntimeError, match="cannot find"):
        cli_version("/definitely/not/installed/agent-cli")
