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

"""ClaudeCodeJudge against a scripted subprocess runner."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cli_support import CliVerdict, cli_request

from hugegraph_llm_eval import ClaudeCodeJudge
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.evaluation.judges.base import JudgeCallError, JudgeOptions

ONCE = JudgeOptions(max_attempts=1)


class FakeRunner:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[SimpleNamespace] = []

    def __call__(self, argv, *, prompt, env, cwd, timeout):
        self.calls.append(SimpleNamespace(argv=list(argv), prompt=prompt, env=dict(env), cwd=cwd, timeout=timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeAuthStatusRunner:
    def __init__(self, payload: dict | str | None = None, returncode: int = 0) -> None:
        self.payload = {"loggedIn": True, "authMethod": "claude.ai"} if payload is None else payload
        self.returncode = returncode
        self.calls: list[SimpleNamespace] = []

    def __call__(self, argv, *, env, cwd, timeout):
        self.calls.append(SimpleNamespace(argv=list(argv), env=dict(env), cwd=cwd, timeout=timeout))
        stdout = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return subprocess.CompletedProcess(args=[], returncode=self.returncode, stdout=stdout, stderr="")


def completed(payload: dict | str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def success(**overrides: object) -> dict:
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "structured_output": {"verdict": "yes", "note": None},
        "session_id": "session-1",
        "total_cost_usd": 0.12,
        "modelUsage": {"claude-resolved": {}},
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 30,
            "output_tokens": 5,
        },
    }
    return {**payload, **overrides}


def error(result: str, status: int | None = None) -> dict:
    return {"is_error": True, "subtype": "success", "result": result, "api_error_status": status}


def make_judge(runner: FakeRunner, **kwargs: Any) -> ClaudeCodeJudge:
    auth_status_runner = kwargs.pop("auth_status_runner", FakeAuthStatusRunner())
    return ClaudeCodeJudge(
        model="sonnet",
        version="2.1.0 (Claude Code)",
        runner=runner,
        auth_status_runner=auth_status_runner,
        **kwargs,
    )


def failed(judge: ClaudeCodeJudge, attempts: int = 1) -> JudgeCallError:
    with pytest.raises(JudgeCallError) as caught:
        judge.judge(cli_request(), JudgeOptions(max_attempts=attempts))
    return caught.value


def test_returns_validated_output_with_token_usage_and_no_cost() -> None:
    result = make_judge(FakeRunner(completed(success()))).judge(cli_request(), ONCE)

    assert result.output == CliVerdict(verdict="yes")
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.total_tokens) == (60, 5, 65)
    assert result.usage.cost_usd is None
    assert (result.provenance.response_id, result.provenance.response_model) == ("session-1", "claude-resolved")
    assert result.provenance.provider == "claude-code"


def test_command_line_disables_tools_and_settings_and_sends_the_prompt_on_stdin() -> None:
    runner = FakeRunner(completed(success()))

    judge = make_judge(runner, effort="low", max_turns=3)
    judge.judge(cli_request(), ONCE)

    call = runner.calls[0]
    argv = call.argv
    assert argv[:4] == ["claude", "-p", "--output-format", "json"]
    assert argv[argv.index("--tools") + 1] == ""
    assert "--setting-sources" not in argv
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--effort") + 1] == "low"
    assert argv[argv.index("--max-turns") + 1] == "3"
    assert argv[argv.index("--system-prompt") + 1] == "Judge strictly."
    assert json.loads(argv[argv.index("--json-schema") + 1])["properties"]["verdict"]["enum"] == ["yes", "no"]
    assert {"--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config"} <= set(argv)
    assert "--bare" not in argv
    assert call.prompt == "Is the claim supported? [scenario:ok]"
    assert Path(call.cwd).is_dir()


@pytest.mark.parametrize("flag", ["--tools", "--setting-sources", "--model", "--permission-mode", "--mcp-config"])
def test_extra_args_cannot_override_controlled_flags(flag: str) -> None:
    with pytest.raises(ValueError, match="cannot override controlled Claude CLI flags"):
        ClaudeCodeJudge(model="sonnet", version="x", extra_args=(flag, "unsafe"))


def test_optional_flags_are_omitted_when_unset() -> None:
    runner = FakeRunner(completed(success()))

    make_judge(runner).judge(cli_request(system=None), ONCE)

    assert not {"--setting-sources", "--effort", "--max-turns", "--system-prompt"} & set(runner.calls[0].argv)


def test_setting_sources_can_be_pinned_to_ignore_settings_files() -> None:
    runner = FakeRunner(completed(success()))

    make_judge(runner, setting_sources="").judge(cli_request(), ONCE)

    argv = runner.calls[0].argv
    assert argv[argv.index("--setting-sources") + 1] == ""


def test_oversized_system_prompt_moves_to_stdin() -> None:
    runner = FakeRunner(completed(success()))
    system = "S" * 150_000

    make_judge(runner).judge(cli_request(system=system), ONCE)

    assert "--system-prompt" not in runner.calls[0].argv
    assert runner.calls[0].prompt.startswith(system)


def test_provider_variables_are_scrubbed_but_subscription_credentials_survive(monkeypatch) -> None:
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
    ):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/claude")
    scrubbed, inherited = FakeRunner(completed(success())), FakeRunner(completed(success()))

    make_judge(scrubbed, scrub_provider_env=True).judge(cli_request(), ONCE)
    make_judge(inherited).judge(cli_request(), ONCE)

    env = scrubbed.calls[0].env
    assert not [name for name in env if name.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_"))]
    assert "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST" not in env
    assert (env["CLAUDE_CODE_OAUTH_TOKEN"], env["CLAUDE_CONFIG_DIR"]) == ("token", "/tmp/claude")
    assert inherited.calls[0].env["ANTHROPIC_BASE_URL"] == "x"


def test_subscription_auth_mode_verifies_account_and_scrubs_provider_env(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "api-key")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "subscription-token")
    runner = FakeRunner(completed(success()))
    status = FakeAuthStatusRunner()

    judge = make_judge(runner, auth_mode="subscription", auth_status_runner=status)
    judge.judge(cli_request(), ONCE)

    call = runner.calls[0]
    assert not [name for name in call.env if name.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_"))]
    assert call.env["CLAUDE_CODE_OAUTH_TOKEN"] == "subscription-token"
    assert call.argv[call.argv.index("--setting-sources") + 1] == ""
    assert "--bare" not in call.argv
    assert status.calls[0].argv == ["claude", "auth", "status"]
    assert judge.descriptor.configuration_digest != make_judge(FakeRunner()).descriptor.configuration_digest


@pytest.mark.parametrize("method", ["api_key", "api_key_helper", "third_party"])
def test_subscription_mode_rejects_non_subscription_auth(method: str) -> None:
    status = FakeAuthStatusRunner({"loggedIn": True, "authMethod": method})
    detail = failed(make_judge(FakeRunner(), auth_mode="subscription", auth_status_runner=status), attempts=3)

    assert detail.failure.code == "provider_account_not_subscription"
    assert detail.failure.retryable is False
    assert len(status.calls) == 1


def test_subscription_auth_status_is_cached() -> None:
    runner = FakeRunner(completed(success()), completed(success()))
    status = FakeAuthStatusRunner()
    judge = make_judge(runner, auth_mode="subscription", auth_status_runner=status)

    judge.judge(cli_request(), ONCE)
    judge.judge(cli_request(), ONCE)

    assert len(status.calls) == 1


def test_json_in_result_text_is_accepted_when_structured_output_is_absent() -> None:
    payload = success(structured_output=None, result='{"verdict":"no","note":"x"}')

    result = make_judge(FakeRunner(completed(payload))).judge(cli_request(), ONCE)

    assert result.output == CliVerdict(verdict="no", note="x")


def test_not_logged_in_is_permanent() -> None:
    runner = FakeRunner(completed(error("Not logged in · Please run /login"), returncode=1))

    detail = failed(make_judge(runner), attempts=3)

    assert (detail.failure.category, detail.failure.code) == (
        FailureCategory.PROVIDER_UNAVAILABLE,
        "provider_not_authenticated",
    )
    assert len(runner.calls) == 1


def test_usage_limit_is_permanent_but_plain_rate_limits_are_retried() -> None:
    limited = FakeRunner(completed(error("Claude usage limit reached, resets at 5pm", 429), returncode=1))
    assert failed(make_judge(limited), attempts=3).failure.code == "provider_usage_limit"
    assert len(limited.calls) == 1

    throttled = FakeRunner(completed(error("slow down", 429), returncode=1), completed(success()))
    result = make_judge(throttled).judge(cli_request(), JudgeOptions(max_attempts=2))
    assert [attempt.status.value for attempt in result.provenance.attempts] == ["failed", "completed"]


def test_server_errors_are_retried_and_client_errors_are_not() -> None:
    server = FakeRunner(completed(error("overloaded", 529), returncode=1), completed(success()))
    assert make_judge(server).judge(cli_request(), JudgeOptions(max_attempts=2)).output.verdict == "yes"

    rejected = FakeRunner(completed(error("bad request", 400), returncode=1))
    assert failed(make_judge(rejected), attempts=3).failure.code == "provider_request_rejected"
    assert len(rejected.calls) == 1


def test_schema_violation_is_retried_and_its_usage_is_kept() -> None:
    bad = success(structured_output={"verdict": "maybe"})
    runner = FakeRunner(completed(bad), completed(bad))

    detail = failed(make_judge(runner), attempts=2)

    assert detail.failure.code == "invalid_structured_output"
    assert [attempt.usage.input_tokens for attempt in detail.provenance.attempts if attempt.usage] == [60, 60]


def test_missing_structured_output_is_retryable() -> None:
    runner = FakeRunner(completed(success(structured_output=None, result="plain prose")), completed(success()))

    result = make_judge(runner).judge(cli_request(), JudgeOptions(max_attempts=2))

    assert result.provenance.attempts[0].failure is not None
    assert result.provenance.attempts[0].failure.code == "missing_structured_output"


def test_process_timeout_is_retryable_and_the_call_timeout_caps_each_run() -> None:
    runner = FakeRunner(subprocess.TimeoutExpired(["claude"], 5), completed(success()))

    result = make_judge(runner, call_timeout_seconds=5).judge(cli_request(), JudgeOptions(max_attempts=2))

    assert [call.timeout for call in runner.calls] == [5, 5]
    assert result.provenance.attempts[0].failure is not None
    assert result.provenance.attempts[0].failure.category is FailureCategory.TIMEOUT


def test_non_json_output_from_a_failed_process_is_permanent() -> None:
    runner = FakeRunner(completed("segfault", returncode=139))

    detail = failed(make_judge(runner), attempts=3)

    assert detail.failure.code == "provider_process_failed"
    assert len(runner.calls) == 1


def test_missing_executable_is_permanent() -> None:
    judge = ClaudeCodeJudge(model="sonnet", executable="/definitely/not/claude", version="x")
    detail = failed(judge, attempts=3)

    assert detail.failure.code == "executable_not_found"
    assert len(detail.provenance.attempts) == 1


def test_descriptor_records_the_cli_version_and_isolation_settings() -> None:
    base = make_judge(FakeRunner()).descriptor
    isolated = make_judge(FakeRunner(), scrub_provider_env=True, setting_sources="").descriptor
    upgraded = ClaudeCodeJudge(model="sonnet", version="9.9.9", runner=FakeRunner()).descriptor

    assert len({base.configuration_digest, isolated.configuration_digest, upgraded.configuration_digest}) == 3


def test_invalid_settings_are_rejected_up_front() -> None:
    with pytest.raises(ValueError, match="call_timeout_seconds"):
        ClaudeCodeJudge(model="sonnet", version="x", call_timeout_seconds=0)
    with pytest.raises(ValueError, match="max_turns"):
        ClaudeCodeJudge(model="sonnet", version="x", max_turns=0)
    with pytest.raises(ValueError, match="auth_mode"):
        ClaudeCodeJudge(model="sonnet", version="x", auth_mode="invalid")  # type: ignore[arg-type]
