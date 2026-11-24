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

"""Configuration-driven Judge construction and provenance identity."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hugegraph_llm_eval import (
    ClaudeCodeJudgeConfig,
    CodexJudgeConfig,
    OpenAIJudgeConfig,
    create_judge,
    managed_judge,
    parse_judge_config,
)
from hugegraph_llm_eval.integrations.judges import factory
from hugegraph_llm_eval.integrations.judges.openai_client import openai_judge


class _Completions:
    def parse(self, **kwargs: object) -> object:
        raise AssertionError("not called")


class _Client:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_Completions())


def test_discriminated_config_makes_api_and_account_switching_explicit() -> None:
    api = parse_judge_config(
        {"backend": "openai", "model": "gpt-eval", "api_key": "secret", "base_url": "https://api.example/v1"}
    )
    claude = parse_judge_config({"backend": "claude-code", "model": "sonnet", "auth_mode": "subscription"})
    codex = parse_judge_config({"backend": "codex", "model": "gpt-codex", "auth_mode": "subscription"})

    assert isinstance(api, OpenAIJudgeConfig)
    assert isinstance(claude, ClaudeCodeJudgeConfig)
    assert isinstance(codex, CodexJudgeConfig)
    assert "secret" not in repr(api)


def test_config_is_closed_and_requires_a_known_backend() -> None:
    with pytest.raises(ValidationError):
        parse_judge_config({"backend": "unknown", "model": "x"})
    with pytest.raises(ValidationError):
        parse_judge_config({"backend": "codex", "model": "x", "config": {"web_search": "enabled"}})


def test_create_judge_dispatches_openai_without_exposing_the_secret(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = SimpleNamespace(descriptor="openai")

    def build(**kwargs: object):
        captured.update(kwargs)
        return sentinel

    from hugegraph_llm_eval.integrations.judges import openai_client

    monkeypatch.setattr(openai_client, "openai_judge", build)
    result = create_judge({"backend": "openai", "model": "judge", "api_key": "top-secret"})

    assert result is sentinel
    assert captured["api_key"] == "top-secret"
    parsed = parse_judge_config({"backend": "openai", "model": "judge", "api_key": "top-secret"})
    assert "top-secret" not in repr(parsed)


def test_create_judge_dispatches_account_backends(monkeypatch) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def claude(**kwargs: object):
        captured.append(("claude", kwargs))
        return SimpleNamespace(descriptor="claude")

    def codex(**kwargs: object):
        captured.append(("codex", kwargs))
        return SimpleNamespace(descriptor="codex")

    from hugegraph_llm_eval.integrations.judges import claude_code, codex_app_server

    monkeypatch.setattr(claude_code, "ClaudeCodeJudge", claude)
    monkeypatch.setattr(codex_app_server, "CodexAppServerJudge", codex)

    create_judge({"backend": "claude-code", "model": "sonnet", "auth_mode": "subscription"})
    create_judge({"backend": "codex", "model": "gpt-codex", "auth_mode": "subscription"})

    assert captured[0][0] == "claude"
    assert captured[0][1]["auth_mode"] == "subscription"
    assert captured[1][0] == "codex"
    assert captured[1][1]["auth_mode"] == "subscription"


def test_managed_judge_closes_stateful_transports(monkeypatch) -> None:
    closed: list[bool] = []
    sentinel = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(factory, "create_judge", lambda config: sentinel)

    with managed_judge({"backend": "codex", "model": "gpt-codex"}) as judge:
        assert judge is sentinel

    assert closed == [True]


def test_openai_descriptor_separates_gateways_and_never_hashes_credentials_as_identity() -> None:
    first = openai_judge(
        model="judge",
        client=_Client(),
        endpoint_id="gateway-a",
    )
    second = openai_judge(
        model="judge",
        client=_Client(),
        endpoint_id="gateway-b",
    )

    assert first.descriptor.configuration_digest != second.descriptor.configuration_digest


def test_openai_factory_rejects_ignored_client_credentials() -> None:
    with pytest.raises(ValueError, match="caller-supplied OpenAI client"):
        openai_judge(model="judge", client=_Client(), api_key="ignored")
    with pytest.raises(ValueError, match="caller-supplied OpenAI client"):
        openai_judge(model="judge", client=_Client(), base_url="https://ignored.example")


def test_codex_subscription_scrubs_every_known_api_override(monkeypatch) -> None:
    from hugegraph_llm_eval import CodexAppServerJudge

    names = (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "OPENAI_ORGANIZATION",
        "OPENAI_PROJECT",
        "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN",
        "OPENAI_FEDERATION_RULE_ID",
        "OPENAI_IDENTITY_TOKEN_FILE",
        "OPENAI_WORKLOAD_IDENTITY_CONTEXT",
    )
    for name in names:
        monkeypatch.setenv(name, "override")
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex-account")

    judge = CodexAppServerJudge(model="judge", version="x", auth_mode="subscription")
    try:
        environment = judge._environment()
    finally:
        judge.close()

    assert not set(names) & environment.keys()
    assert environment["CODEX_HOME"] != "/tmp/codex-account"
    assert environment["CODEX_HOME"].endswith("/codex-home")


def test_codex_rejects_raw_routing_and_mcp_opt_out() -> None:
    from hugegraph_llm_eval import CodexAppServerJudge

    with pytest.raises(ValueError, match="unsupported raw Codex config keys"):
        CodexAppServerJudge(model="judge", version="x", config={"model_provider": "ollama"})
    with pytest.raises(ValueError, match="cannot be false"):
        CodexAppServerJudge(model="judge", version="x", disable_user_mcp_servers=False)


def test_codex_subscription_pins_openai_route_even_with_ambient_custom_config() -> None:
    from hugegraph_llm_eval import CodexAppServerJudge

    class Connection:
        def request(self, method: str, params: object, timeout: float) -> dict[str, object]:
            assert method == "config/read"
            return {"config": {"model_provider": "ollama", "openai_base_url": "https://proxy", "mcp_servers": {}}}

    judge = CodexAppServerJudge(model="judge", version="x", auth_mode="subscription")
    try:
        assert judge._verified_isolation_overrides(Connection(), 1.0) == {}  # type: ignore[arg-type]
        thread = judge._thread_params(None)
    finally:
        judge.close()

    assert thread["modelProvider"] == "openai"
    assert thread["config"]["openai_base_url"] is None  # type: ignore[index]
