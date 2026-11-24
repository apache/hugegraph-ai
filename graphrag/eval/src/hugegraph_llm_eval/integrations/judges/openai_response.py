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

"""Validate and classify OpenAI-compatible structured responses."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ValidationError

from hugegraph_llm_eval.contracts.domain.judge import ProviderUsage
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.evaluation.judges.base import JudgeRequest, OutputT
from hugegraph_llm_eval.integrations.judges.attempts import AttemptFailureError, AttemptOutcome, failure

if TYPE_CHECKING:
    pass


def _openai():
    try:
        import openai
    except ImportError as exc:
        msg = "the OpenAI judge transport requires the 'openai' extra: pip install hugegraph-llm-eval[openai]"
        raise ImportError(msg) from exc
    return openai


class OpenAIResponseUsage(Protocol):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class _ResponseMessage(Protocol):
    parsed: object | None
    refusal: str | None


class _ResponseChoice(Protocol):
    finish_reason: str | None
    message: _ResponseMessage


class OpenAIResponse(Protocol):
    id: str
    model: str
    choices: tuple[_ResponseChoice, ...]
    usage: OpenAIResponseUsage | None


def provider_outcome(
    request: JudgeRequest[OutputT],
    response: OpenAIResponse,
    usage_factory: Callable[[OpenAIResponseUsage | None], ProviderUsage],
) -> AttemptOutcome:
    usage = None
    try:
        usage = usage_factory(response.usage)
        if not response.choices:
            raise AttemptFailureError(failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "missing_choice", False))
        output = _structured_output(request, response.choices[0])
        return AttemptOutcome(
            output=output,
            usage=usage,
            response_id=response.id,
            response_model=response.model,
        )
    except AttemptFailureError as exc:
        raise AttemptFailureError(exc.failure, usage=usage) from exc
    except (AttributeError, IndexError, TypeError) as exc:
        detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "malformed_provider_response", False)
        raise AttemptFailureError(detail, usage=usage) from exc


def exception_usage(
    error: Exception,
    usage_factory: Callable[[OpenAIResponseUsage | None], ProviderUsage],
) -> ProviderUsage | None:
    """Retain billed usage even when a structured response was rejected."""
    if isinstance(error, AttemptFailureError):
        return error.usage
    if isinstance(error, _openai().LengthFinishReasonError):
        try:
            return usage_factory(error.completion.usage)
        except (AttributeError, TypeError, ValueError, AttemptFailureError):
            return None
    return None


def _structured_output(request: JudgeRequest[OutputT], choice: _ResponseChoice) -> BaseModel:
    if choice.finish_reason == "length":
        raise AttemptFailureError(failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "truncated_output", True))
    if choice.message.refusal:
        raise AttemptFailureError(failure(FailureCategory.PROVIDER_REFUSAL, "provider_refusal", False))
    if choice.message.parsed is None:
        raise AttemptFailureError(failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "missing_structured_output", True))
    try:
        return request.response_type.model_validate(choice.message.parsed)
    except ValidationError as exc:
        detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "invalid_structured_output", True)
        raise AttemptFailureError(detail) from exc


def classify_exception(error: Exception) -> FailureDetail:
    provider = _openai()
    if isinstance(error, provider.LengthFinishReasonError):
        return failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "truncated_output", True)
    if isinstance(error, ValidationError):
        return failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "invalid_structured_output", True)
    if isinstance(error, (provider.APITimeoutError, TimeoutError)):
        return failure(FailureCategory.TIMEOUT, "provider_timeout", True)
    if isinstance(error, provider.RateLimitError):
        return failure(FailureCategory.PROVIDER_RATE_LIMIT, "provider_rate_limit", True)
    if isinstance(error, (provider.APIConnectionError, provider.InternalServerError)):
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_unavailable", True)
    permanent = (
        provider.AuthenticationError,
        provider.BadRequestError,
        provider.NotFoundError,
        provider.PermissionDeniedError,
        provider.ConflictError,
        provider.UnprocessableEntityError,
    )
    if isinstance(error, permanent):
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_request_rejected", False)
    if isinstance(error, provider.APIStatusError):
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_http_error", error.status_code >= 500)
    return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_transport_error", False)
