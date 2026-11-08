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

"""CodexAppServerJudge against a scripted app-server child process."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from cli_support import CliVerdict, cli_request

from hugegraph_llm_eval import CodexAppServerJudge
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.evaluation.judges.base import JudgeCallError, JudgeOptions
from hugegraph_llm_eval.integrations.judges.codex_connection import spawn_app_server

SERVER = Path(__file__).with_name("fake_codex_server.py")
ONCE = JudgeOptions(max_attempts=1)


def make_judge(tmp_path: Path, **kwargs: Any) -> CodexAppServerJudge:
    log = tmp_path / "server.jsonl"

    def spawn(argv, *, cwd, env):
        assert list(argv)[1:] == ["app-server"]
        return spawn_app_server([sys.executable, "-I", str(SERVER)], cwd=cwd, env={**env, "FAKE_CODEX_LOG": str(log)})

    return CodexAppServerJudge(model="fake-model", version="codex-cli 0.0.0", spawn=spawn, **kwargs)


def requests(tmp_path: Path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "server.jsonl").read_text().splitlines()]


def params_of(tmp_path: Path, method: str) -> dict:
    return next(entry["params"] for entry in requests(tmp_path) if entry["method"] == method)


def failed_judge(judge: CodexAppServerJudge, marker: str, attempts: int = 1) -> JudgeCallError:
    with pytest.raises(JudgeCallError) as caught:
        judge.judge(cli_request(marker), JudgeOptions(max_attempts=attempts))
    return caught.value


def test_returns_validated_output_with_token_usage(tmp_path: Path) -> None:
    with make_judge(tmp_path) as judge:
        result = judge.judge(cli_request(), ONCE)

    assert result.output == CliVerdict(verdict="yes")
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.total_tokens) == (100, 7, 107)
    assert result.usage.cost_usd is None
    assert result.provenance.provider == "codex-app-server"
    assert result.provenance.response_model == "fake-model-resolved"


def test_thread_is_ephemeral_read_only_and_tool_free(tmp_path: Path) -> None:
    with make_judge(tmp_path, effort="low") as judge:
        judge.judge(cli_request(), ONCE)

    thread = params_of(tmp_path, "thread/start")
    assert (thread["model"], thread["ephemeral"], thread["approvalPolicy"]) == ("fake-model", True, "never")
    assert (thread["sandbox"], thread["baseInstructions"]) == ("read-only", "Judge strictly.")
    assert thread["config"]["features"]["shell_tool"] is False
    assert thread["config"]["mcp_servers"] == {"user_mcp": {"enabled": False}}
    turn = params_of(tmp_path, "turn/start")
    assert turn["effort"] == "low"
    assert turn["outputSchema"]["additionalProperties"] is False
    assert turn["outputSchema"]["required"] == ["verdict", "note"]
    assert "[scenario:ok]" in turn["input"][0]["text"]
    assert "thread/unsubscribe" in [entry["method"] for entry in requests(tmp_path)]


def test_default_instructions_replace_a_missing_system_message(tmp_path: Path) -> None:
    with make_judge(tmp_path) as judge:
        judge.judge(cli_request(system=None), ONCE)

    assert "evaluation judge" in params_of(tmp_path, "thread/start")["baseInstructions"]


def test_usage_limit_is_permanent_and_keeps_billed_usage(tmp_path: Path) -> None:
    with make_judge(tmp_path) as judge:
        error = failed_judge(judge, "usage-limit", attempts=3)

    assert (error.failure.category, error.failure.code) == (FailureCategory.PROVIDER_RATE_LIMIT, "provider_usage_limit")
    assert len(error.provenance.attempts) == 1
    assert error.provenance.attempts[0].usage is not None
    assert error.provenance.attempts[0].usage.input_tokens == 100


def test_authentication_failure_is_permanent(tmp_path: Path) -> None:
    with make_judge(tmp_path) as judge:
        error = failed_judge(judge, "unauthorized", attempts=3)

    assert error.failure.code == "provider_not_authenticated"
    assert len(error.provenance.attempts) == 1


def test_overloaded_turn_is_retried(tmp_path: Path) -> None:
    with make_judge(tmp_path) as judge:
        result = judge.judge(cli_request("overloaded-once"), JudgeOptions(max_attempts=2))

    attempts = result.provenance.attempts
    assert [attempt.status.value for attempt in attempts] == ["failed", "completed"]
    assert attempts[0].failure is not None
    assert attempts[0].failure.code == "provider_unavailable"


def test_unparseable_answer_is_retryable_and_billed(tmp_path: Path) -> None:
    with make_judge(tmp_path) as judge:
        error = failed_judge(judge, "bad-json", attempts=2)

    assert error.failure.code == "invalid_structured_output"
    assert [attempt.usage is not None for attempt in error.provenance.attempts] == [True, True]


def test_server_crash_is_retried_on_a_fresh_process(tmp_path: Path) -> None:
    with make_judge(tmp_path) as judge:
        result = judge.judge(cli_request("crash-once"), JudgeOptions(max_attempts=2))

    assert len(result.provenance.attempts) == 2
    starts = [entry["pid"] for entry in requests(tmp_path) if entry["method"] == "initialize"]
    assert len(set(starts)) == 2


def test_hung_turn_is_interrupted_at_the_call_timeout(tmp_path: Path) -> None:
    with make_judge(tmp_path, call_timeout_seconds=0.5) as judge:
        error = failed_judge(judge, "hang")

    assert (error.failure.category, error.failure.code) == (FailureCategory.TIMEOUT, "provider_timeout")
    assert "turn/interrupt" in [entry["method"] for entry in requests(tmp_path)]


def test_concurrent_calls_share_one_server_process(tmp_path: Path) -> None:
    with make_judge(tmp_path) as judge, ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: judge.judge(cli_request(), ONCE), range(8)))

    assert all(result.output.verdict == "yes" for result in results)
    assert len({result.provenance.response_id for result in results}) == 8
    assert len([entry for entry in requests(tmp_path) if entry["method"] == "initialize"]) == 1


def test_close_stops_the_server_and_a_later_call_starts_a_new_one(tmp_path: Path) -> None:
    judge = make_judge(tmp_path)
    judge.judge(cli_request(), ONCE)
    judge.close()
    judge.judge(cli_request(), ONCE)
    judge.close()

    assert len({entry["pid"] for entry in requests(tmp_path)}) == 2


def test_missing_executable_is_reported_as_permanent(tmp_path: Path) -> None:
    judge = CodexAppServerJudge(model="m", executable=str(tmp_path / "no-such-codex"), version="x")

    error = failed_judge(judge, "ok", attempts=3)

    assert error.failure.code == "executable_not_found"
    assert len(error.provenance.attempts) == 1


def test_custom_features_preserve_safe_defaults_and_reject_tool_enablement(tmp_path: Path) -> None:
    judge = make_judge(tmp_path, config={"features": {"multi_agent": False}})
    features = judge._config["features"]
    assert features["shell_tool"] is False
    assert features["browser_use"] is False
    assert features["plugins"] is False
    with pytest.raises(ValueError, match="cannot enable tool capabilities"):
        make_judge(tmp_path, config={"features": {"shell_tool": True}})


def test_custom_mcp_servers_are_rejected_when_isolation_is_enabled(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"config\.mcp_servers"):
        make_judge(tmp_path, config={"mcp_servers": {"external": {"command": "unsafe"}}})


def test_empty_user_mcp_config_is_explicitly_disabled(tmp_path: Path) -> None:
    judge = make_judge(tmp_path)
    judge._mcp_overrides = {}
    assert judge._thread_params(None)["config"]["mcp_servers"] == {}


def test_mcp_isolation_fails_closed_when_config_cannot_be_read(tmp_path: Path) -> None:
    from hugegraph_llm_eval.integrations.judges.codex_connection import RpcError

    class BrokenConnection:
        def request(self, method, params, timeout):
            raise RpcError("config unavailable")

    judge = make_judge(tmp_path)
    with pytest.raises(RuntimeError, match=r"(?i)cannot verify"):
        judge._disabled_mcp_servers(BrokenConnection(), 1.0)


def test_subscription_auth_mode_removes_ambient_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.invalid/v1")
    captured: dict[str, str] = {}
    log = tmp_path / "server.jsonl"

    def spawn(argv, *, cwd, env):
        captured.update(env)
        return spawn_app_server([sys.executable, "-I", str(SERVER)], cwd=cwd, env={**env, "FAKE_CODEX_LOG": str(log)})

    with CodexAppServerJudge(model="fake-model", version="x", auth_mode="subscription", spawn=spawn) as judge:
        judge.judge(cli_request(), ONCE)

    assert "OPENAI_API_KEY" not in captured
    assert "OPENAI_BASE_URL" not in captured


@pytest.mark.parametrize(
    ("account", "code"),
    (("none", "provider_not_authenticated"), ("apiKey", "provider_account_not_chatgpt")),
)
def test_subscription_mode_rejects_a_non_chatgpt_account(monkeypatch, tmp_path: Path, account: str, code: str) -> None:
    monkeypatch.setenv("FAKE_CODEX_ACCOUNT", account)
    with make_judge(tmp_path, auth_mode="subscription") as judge:
        error = failed_judge(judge, "ok", attempts=3)

    assert error.failure.code == code
    assert error.failure.retryable is False
    assert len(error.provenance.attempts) == 1


def test_inherit_mode_accepts_any_account_without_reading_it(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_CODEX_ACCOUNT", "apiKey")
    with make_judge(tmp_path) as judge:
        judge.judge(cli_request(), ONCE)

    assert "account/read" not in {entry["method"] for entry in requests(tmp_path)}


def test_descriptor_changes_with_cli_version_and_effort(tmp_path: Path) -> None:
    base = make_judge(tmp_path).descriptor
    other_effort = make_judge(tmp_path, effort="high").descriptor
    other_version = CodexAppServerJudge(model="fake-model", version="codex-cli 9.9.9").descriptor

    account_mode = CodexAppServerJudge(
        model="fake-model", version="codex-cli 0.0.0", auth_mode="subscription"
    ).descriptor
    assert (
        len(
            {
                base.configuration_digest,
                other_effort.configuration_digest,
                other_version.configuration_digest,
                account_mode.configuration_digest,
            }
        )
        == 4
    )


def test_user_hooks_and_config_are_not_inherited_into_codex_home(monkeypatch, tmp_path: Path) -> None:
    source_home = tmp_path / "user-codex"
    source_home.mkdir()
    (source_home / "auth.json").write_text('{"tokens":"test-auth"}')
    (source_home / "hooks.json").write_text('{"hooks":{"PreToolUse":[]}}')
    (source_home / "config.toml").write_text('model_provider = "custom"')
    monkeypatch.setenv("CODEX_HOME", str(source_home))

    judge = CodexAppServerJudge(model="fake-model", version="codex-cli 0.0.0")
    try:
        child_env = judge._environment()
        isolated_home = Path(child_env["CODEX_HOME"])
        assert isolated_home != source_home
        assert (isolated_home / "auth.json").read_text() == '{"tokens":"test-auth"}'
        assert not (isolated_home / "hooks.json").exists()
        assert not (isolated_home / "config.toml").exists()
        assert (isolated_home / "auth.json").stat().st_mode & 0o777 == 0o600
    finally:
        judge.close()


def test_subscription_environment_uses_isolated_codex_home_and_scrubs_api_keys(monkeypatch, tmp_path: Path) -> None:
    source_home = tmp_path / "subscription-codex"
    source_home.mkdir()
    (source_home / "auth.json").write_text('{"tokens":"test-auth"}')
    (source_home / "hooks.json").write_text('{"hooks":{"PreToolUse":[]}}')
    monkeypatch.setenv("CODEX_HOME", str(source_home))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")

    judge = CodexAppServerJudge(model="fake-model", version="codex-cli 0.0.0", auth_mode="subscription")
    try:
        child_env = judge._environment()
        assert "OPENAI_API_KEY" not in child_env
        assert Path(child_env["CODEX_HOME"]) != source_home
        assert (Path(child_env["CODEX_HOME"]) / "auth.json").is_file()
        assert not (Path(child_env["CODEX_HOME"]) / "hooks.json").exists()
    finally:
        judge.close()
