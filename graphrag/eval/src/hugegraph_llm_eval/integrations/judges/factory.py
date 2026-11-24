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

"""Typed Judge configuration and lifecycle helpers for SDK callers."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Annotated, Literal

from pydantic import Field, SecretStr, TypeAdapter

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.evaluation.judges.base import Judge

type AuthMode = Literal["inherit", "subscription"]


class OpenAIJudgeConfig(StrictModel):
    """Configuration for an OpenAI-compatible API-backed Judge."""

    backend: Literal["openai"] = "openai"
    model: str = Field(min_length=1, max_length=255)
    api_key: SecretStr | None = None
    base_url: str | None = None
    provider: str = Field(default="openai", min_length=1, max_length=127)
    temperature: float = Field(default=0, ge=0, le=2)
    seed: int | None = 42
    max_tokens: int = Field(default=16_384, ge=1)
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)


class ClaudeCodeJudgeConfig(StrictModel):
    """Configuration for a Judge using the locally installed Claude Code CLI."""

    backend: Literal["claude-code"] = "claude-code"
    model: str = Field(min_length=1, max_length=255)
    auth_mode: AuthMode = "inherit"
    effort: str | None = None
    executable: str = Field(default="claude", min_length=1)
    max_turns: int | None = Field(default=None, ge=1)
    call_timeout_seconds: float = Field(default=600.0, gt=0)


class CodexJudgeConfig(StrictModel):
    """Configuration for a Judge using the locally installed Codex app-server."""

    backend: Literal["codex"] = "codex"
    model: str = Field(min_length=1, max_length=255)
    auth_mode: AuthMode = "inherit"
    effort: str | None = None
    executable: str = Field(default="codex", min_length=1)
    call_timeout_seconds: float = Field(default=600.0, gt=0)


type JudgeConfig = Annotated[
    OpenAIJudgeConfig | ClaudeCodeJudgeConfig | CodexJudgeConfig,
    Field(discriminator="backend"),
]
_CONFIG_ADAPTER = TypeAdapter(JudgeConfig)


def parse_judge_config(config: JudgeConfig | Mapping[str, object]) -> JudgeConfig:
    """Validate a model or mapping as one closed, discriminated Judge configuration."""
    if isinstance(config, (OpenAIJudgeConfig, ClaudeCodeJudgeConfig, CodexJudgeConfig)):
        return config
    return _CONFIG_ADAPTER.validate_python(config)


def create_judge(config: JudgeConfig | Mapping[str, object]) -> Judge:
    """Create a Judge while keeping provider selection entirely configuration-driven."""
    parsed = parse_judge_config(config)
    if isinstance(parsed, OpenAIJudgeConfig):
        from hugegraph_llm_eval.integrations.judges.openai_client import openai_judge

        api_key = parsed.api_key.get_secret_value() if parsed.api_key is not None else None
        return openai_judge(
            model=parsed.model,
            api_key=api_key,
            base_url=parsed.base_url,
            provider=parsed.provider,
            temperature=parsed.temperature,
            seed=parsed.seed,
            max_tokens=parsed.max_tokens,
            input_usd_per_million=parsed.input_usd_per_million,
            output_usd_per_million=parsed.output_usd_per_million,
        )
    if isinstance(parsed, ClaudeCodeJudgeConfig):
        from hugegraph_llm_eval.integrations.judges.claude_code import ClaudeCodeJudge

        return ClaudeCodeJudge(
            model=parsed.model,
            auth_mode=parsed.auth_mode,
            effort=parsed.effort,
            executable=parsed.executable,
            max_turns=parsed.max_turns,
            call_timeout_seconds=parsed.call_timeout_seconds,
        )
    from hugegraph_llm_eval.integrations.judges.codex_app_server import CodexAppServerJudge

    return CodexAppServerJudge(
        model=parsed.model,
        auth_mode=parsed.auth_mode,
        effort=parsed.effort,
        executable=parsed.executable,
        call_timeout_seconds=parsed.call_timeout_seconds,
    )


@contextmanager
def managed_judge(config: JudgeConfig | Mapping[str, object]) -> Generator[Judge, None, None]:
    """Create a Judge and close transports such as Codex app-server on exit."""
    judge = create_judge(config)
    try:
        yield judge
    finally:
        close = getattr(judge, "close", None)
        if callable(close):
            close()
