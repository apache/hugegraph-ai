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

"""Provider-neutral Judge contract and OpenAI-compatible adapter behavior."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("openai", reason="install hugegraph-llm-eval[openai] to run provider contracts")
from fakes import NOW
from openai import LengthFinishReasonError
from pydantic import Field, ValidationError

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationRecordDraft,
    EvaluationRecordStatus,
)
from hugegraph_llm_eval.contracts.domain.judge import JudgeCallRecord, JudgeCallStatus
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.contracts.identity import ComponentRef, EvaluatorRef
from hugegraph_llm_eval.evaluation.judges.base import (
    JudgeCallError,
    JudgeContentRef,
    JudgeDescriptor,
    JudgeMessage,
    JudgeOptions,
    JudgeRequest,
)
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.judges.openai_compatible import (
    OpenAICompatibleJudge,
    OpenAICompatiblePricing,
    OpenAICompatibleSettings,
)
from hugegraph_llm_eval.integrations.judges.openai_response import classify_exception


class Verdict(StrictModel):
    """Verdict."""

    score: float = Field(ge=0, le=1)
    reason: str


class FakeCompletions:
    """FakeCompletions."""

    def __init__(self, *responses: object) -> None:
        """__init__."""
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        """parse."""
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_sdk_length_finish_error_is_typed_as_retryable_truncation() -> None:
    """test_sdk_length_finish_error_is_typed_as_retryable_truncation."""
    detail = classify_exception(LengthFinishReasonError(completion=_response()))  # type: ignore[arg-type]

    assert detail.category is FailureCategory.INVALID_PROVIDER_OUTPUT
    assert detail.code == "truncated_output"
    assert detail.retryable is True


def _identity(name: str, fill: str) -> JudgeContentRef:
    """_identity."""
    return JudgeContentRef(
        component=ComponentRef(namespace="graph", name=name, revision="v1"),
        content_digest="sha256:" + fill * 64,
    )


def _request() -> JudgeRequest[Verdict]:
    """_request."""
    return JudgeRequest(
        messages=(JudgeMessage(role="system", content="Return a grounded verdict."),),
        response_type=Verdict,
        prompt=_identity("faithfulness_prompt", "a"),
        rubric=_identity("faithfulness_rubric", "b"),
    )


def test_judge_content_reference_is_derived_from_exact_utf8_text() -> None:
    """test_judge_content_reference_is_derived_from_exact_utf8_text."""
    first = JudgeContent(
        component=ComponentRef(namespace="graph", name="prompt", revision="v1"),
        text="Judge only explicit source evidence.",
    )
    same = first.model_copy()
    changed = first.model_copy(update={"text": "Judge only cited source evidence."})

    assert same.reference == first.reference
    assert changed.reference.content_digest != first.reference.content_digest


def _response(*, response_id: str = "resp-1") -> object:
    """_response."""
    return SimpleNamespace(
        id=response_id,
        model="judge-model",
        choices=(
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(parsed=Verdict(score=0.9, reason="grounded"), refusal=None),
            ),
        ),
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120),
    )


def _judge(
    transport: FakeCompletions,
    *,
    sleeps: list[float] | None = None,
    settings: OpenAICompatibleSettings | None = None,
) -> OpenAICompatibleJudge:
    """_judge."""
    settings = settings or OpenAICompatibleSettings()
    pricing = OpenAICompatiblePricing(input_usd_per_million=2, output_usd_per_million=8)
    return OpenAICompatibleJudge(
        transport=transport,
        descriptor=JudgeDescriptor.create(
            provider="test-openai-compatible",
            model="judge-model",
            configuration={
                "generation": settings.model_dump(mode="json"),
                "pricing": {
                    "input_usd_per_million": pricing.input_usd_per_million,
                    "output_usd_per_million": pricing.output_usd_per_million,
                },
            },
        ),
        pricing=pricing,
        settings=settings,
        clock=lambda: NOW,
        monotonic=_monotonic_clock(),
        sleep=(sleeps.append if sleeps is not None else lambda _delay: None),
    )


def _monotonic_clock():
    """_monotonic_clock."""
    values = iter((0.0, 0.01, 0.02, 0.03, 0.04, 0.05))
    return lambda: next(values)


def test_openai_compatible_judge_returns_typed_output_and_complete_provenance() -> None:
    """test_openai_compatible_judge_returns_typed_output_and_complete_provenance."""
    transport = FakeCompletions(_response())
    judge = _judge(transport)

    result = judge.judge(
        _request(),
        JudgeOptions(max_attempts=1, deadline=NOW + timedelta(seconds=30)),
    )

    assert result.output == Verdict(score=0.9, reason="grounded")
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 20
    assert result.usage.cost_usd == pytest.approx(0.00036)
    assert result.provenance.provider == "test-openai-compatible"
    assert result.provenance.model == "judge-model"
    assert result.provenance.prompt == _identity("faithfulness_prompt", "a")
    assert result.provenance.rubric == _identity("faithfulness_rubric", "b")
    assert result.provenance.response_id == "resp-1"
    assert result.provenance.response_model == "judge-model"
    assert len(result.provenance.attempts) == 1
    assert transport.calls[0]["response_format"] is Verdict
    assert transport.calls[0]["timeout"] == pytest.approx(30)
    assert transport.calls[0]["temperature"] == 0
    assert transport.calls[0]["seed"] == 42
    assert transport.calls[0]["max_tokens"] == 131_072
    messages = transport.calls[0]["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    assert "Return only valid JSON matching this JSON Schema" in messages[0]["content"]
    assert '"score"' in messages[0]["content"]


def test_transient_error_retries_and_preserves_failed_attempt() -> None:
    """test_transient_error_retries_and_preserves_failed_attempt."""
    sleeps: list[float] = []
    transport = FakeCompletions(TimeoutError("gateway timeout"), _response(response_id="resp-2"))
    judge = _judge(transport, sleeps=sleeps)

    result = judge.judge(_request(), JudgeOptions(max_attempts=2, initial_backoff_seconds=0.5))

    assert len(result.provenance.attempts) == 2
    assert result.provenance.attempts[0].failure is not None
    assert result.provenance.attempts[0].failure.category is FailureCategory.TIMEOUT
    assert result.provenance.attempts[1].failure is None
    assert sleeps == [0.5]


def test_default_judge_options_retry_retryable_provider_failures_three_times() -> None:
    """test_default_judge_options_retry_retryable_provider_failures_three_times."""
    transport = FakeCompletions(TimeoutError("first"), TimeoutError("second"), TimeoutError("third"))
    judge = _judge(transport)

    with pytest.raises(JudgeCallError) as captured:
        judge.judge(_request(), JudgeOptions())

    assert captured.value.failure.category is FailureCategory.TIMEOUT
    assert len(captured.value.provenance.attempts) == 3
    assert len(transport.calls) == 3


def test_schema_instruction_can_be_disabled_and_changes_configuration_identity() -> None:
    """test_schema_instruction_can_be_disabled_and_changes_configuration_identity."""
    transport = FakeCompletions(_response())
    settings = OpenAICompatibleSettings(include_json_schema_instruction=False)
    judge = _judge(transport, settings=settings)

    judge.judge(_request(), JudgeOptions())

    assert transport.calls[0]["messages"] == [{"role": "system", "content": "Return a grounded verdict."}]
    assert judge.descriptor.configuration_digest != _judge(FakeCompletions(_response())).descriptor.configuration_digest


def test_exhausted_provider_error_exposes_attempts_and_never_returns_score() -> None:
    """test_exhausted_provider_error_exposes_attempts_and_never_returns_score."""
    transport = FakeCompletions(TimeoutError("first"), TimeoutError("second"))
    judge = _judge(transport)

    with pytest.raises(JudgeCallError) as captured:
        judge.judge(_request(), JudgeOptions(max_attempts=2))

    assert captured.value.failure.category is FailureCategory.TIMEOUT
    assert captured.value.failure.retryable is True
    assert len(captured.value.provenance.attempts) == 2


def test_refusal_is_permanent_and_not_retried() -> None:
    """test_refusal_is_permanent_and_not_retried."""
    refusal = _response()
    refusal.choices[0].message.refusal = "policy refusal"
    transport = FakeCompletions(refusal, _response())
    judge = _judge(transport)

    with pytest.raises(JudgeCallError) as captured:
        judge.judge(_request(), JudgeOptions(max_attempts=3))

    assert captured.value.failure.category is FailureCategory.PROVIDER_REFUSAL
    assert captured.value.failure.retryable is False
    assert len(transport.calls) == 1


def test_invalid_structured_output_is_typed_retryable_failure() -> None:
    """test_invalid_structured_output_is_typed_retryable_failure."""
    response = _response()
    response.choices[0].message.parsed = None
    transport = FakeCompletions(response)
    judge = _judge(transport)

    with pytest.raises(JudgeCallError) as captured:
        judge.judge(_request(), JudgeOptions(max_attempts=1))

    assert captured.value.failure.category is FailureCategory.INVALID_PROVIDER_OUTPUT
    assert captured.value.failure.code == "missing_structured_output"
    assert captured.value.failure.retryable is True


def test_sdk_structured_output_validation_error_is_invalid_provider_output() -> None:
    """test_sdk_structured_output_validation_error_is_invalid_provider_output."""
    with pytest.raises(ValidationError) as malformed:
        Verdict.model_validate_json("score=1")
    judge = _judge(FakeCompletions(malformed.value))

    with pytest.raises(JudgeCallError) as captured:
        judge.judge(_request(), JudgeOptions(max_attempts=1))

    assert captured.value.failure.category is FailureCategory.INVALID_PROVIDER_OUTPUT
    assert captured.value.failure.code == "invalid_structured_output"
    assert captured.value.failure.retryable is True


def test_malformed_provider_response_is_typed_invalid_output() -> None:
    """test_malformed_provider_response_is_typed_invalid_output."""
    judge = _judge(FakeCompletions(SimpleNamespace(id="broken")))

    with pytest.raises(JudgeCallError) as captured:
        judge.judge(_request(), JudgeOptions(max_attempts=2))

    assert captured.value.failure.category is FailureCategory.INVALID_PROVIDER_OUTPUT
    assert captured.value.failure.code == "malformed_provider_response"
    assert captured.value.failure.retryable is False


def test_inconsistent_provider_usage_is_typed_invalid_output() -> None:
    """test_inconsistent_provider_usage_is_typed_invalid_output."""
    response = _response()
    response.usage.total_tokens = 999
    judge = _judge(FakeCompletions(response))

    with pytest.raises(JudgeCallError) as captured:
        judge.judge(_request(), JudgeOptions(max_attempts=2))

    assert captured.value.failure.category is FailureCategory.INVALID_PROVIDER_OUTPUT
    assert captured.value.failure.code == "inconsistent_provider_usage"
    assert captured.value.failure.retryable is False


def test_missing_provider_usage_is_explicitly_unreported() -> None:
    """test_missing_provider_usage_is_explicitly_unreported."""
    response = _response()
    response.usage = None
    judge = _judge(FakeCompletions(response))

    result = judge.judge(_request(), JudgeOptions())

    assert result.usage.reported is False
    assert result.usage.total_tokens == 0
    assert result.usage.cost_usd is None


def test_unknown_pricing_preserves_tokens_without_inventing_cost() -> None:
    """test_unknown_pricing_preserves_tokens_without_inventing_cost."""
    settings = OpenAICompatibleSettings()
    pricing = OpenAICompatiblePricing(input_usd_per_million=None, output_usd_per_million=None)
    descriptor = JudgeDescriptor.create(
        provider="test-openai-compatible",
        model="judge-model",
        configuration={
            "generation": settings.model_dump(mode="json"),
            "pricing": {
                "input_usd_per_million": None,
                "output_usd_per_million": None,
            },
        },
    )
    judge = OpenAICompatibleJudge(
        transport=FakeCompletions(_response()),
        descriptor=descriptor,
        pricing=pricing,
        settings=settings,
        clock=lambda: NOW,
    )

    result = judge.judge(_request(), JudgeOptions())

    assert result.usage.reported is True
    assert result.usage.total_tokens == 120
    assert result.usage.cost_usd is None


def test_judge_provenance_round_trips_inside_evaluation_record() -> None:
    """test_judge_provenance_round_trips_inside_evaluation_record."""
    result = _judge(FakeCompletions(_response())).judge(_request(), JudgeOptions())
    calls = (
        JudgeCallRecord(
            call_index=1,
            call_key="decompose_claims",
            status=JudgeCallStatus.COMPLETED,
            provenance=result.provenance,
            usage=result.usage,
        ),
        JudgeCallRecord(
            call_index=2,
            call_key="verify_claims",
            status=JudgeCallStatus.COMPLETED,
            provenance=result.provenance,
            usage=result.usage,
        ),
    )
    draft = EvaluationRecordDraft(
        invocation_key="faithfulness",
        evaluator=EvaluatorRef(namespace="graph", name="faithfulness", revision="v1"),
        status=EvaluationRecordStatus.COMPLETED,
        reason="grounded",
        judge_calls=calls,
        attempts=1,
        latency_ms=10,
        created_at=NOW,
    )

    assert EvaluationRecordDraft.model_validate_json(draft.model_dump_json()) == draft


def test_evaluation_record_rejects_non_contiguous_judge_calls() -> None:
    """test_evaluation_record_rejects_non_contiguous_judge_calls."""
    result = _judge(FakeCompletions(_response())).judge(_request(), JudgeOptions())
    call = JudgeCallRecord(
        call_index=2,
        call_key="verify_claims",
        status=JudgeCallStatus.COMPLETED,
        provenance=result.provenance,
        usage=result.usage,
    )

    with pytest.raises(ValueError, match="contiguous"):
        EvaluationRecordDraft(
            invocation_key="faithfulness",
            evaluator=EvaluatorRef(namespace="graph", name="faithfulness", revision="v1"),
            status=EvaluationRecordStatus.COMPLETED,
            reason="grounded",
            judge_calls=(call,),
            attempts=1,
            latency_ms=10,
            created_at=NOW,
        )


def test_judge_session_preserves_multiple_call_provenance() -> None:
    """test_judge_session_preserves_multiple_call_provenance."""
    judge = _judge(FakeCompletions(_response(response_id="resp-1"), _response(response_id="resp-2")))
    session = JudgeSession(judge, JudgeOptions())

    first = session.call("decompose_claims", _request())
    second = session.call("verify_claims", _request())

    assert first.score == second.score == 0.9
    assert [call.call_index for call in session.calls] == [1, 2]
    assert [call.call_key for call in session.calls] == ["decompose_claims", "verify_claims"]
    assert [call.provenance.response_id for call in session.calls] == ["resp-1", "resp-2"]
    assert session.latency_ms == sum(
        attempt.latency_ms for call in session.calls for attempt in call.provenance.attempts
    )


def test_adapter_rejects_descriptor_configuration_drift() -> None:
    """test_adapter_rejects_descriptor_configuration_drift."""
    with pytest.raises(ValueError, match="configuration digest"):
        OpenAICompatibleJudge(
            transport=FakeCompletions(_response()),
            descriptor=JudgeDescriptor(
                provider="test-openai-compatible",
                model="judge-model",
                configuration_digest="sha256:" + "d" * 64,
            ),
            pricing=OpenAICompatiblePricing(input_usd_per_million=2, output_usd_per_million=8),
            settings=OpenAICompatibleSettings(),
            clock=lambda: NOW,
        )
