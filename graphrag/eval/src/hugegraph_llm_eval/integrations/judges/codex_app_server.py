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

"""Judge backed by ``codex app-server``, so evaluation can run on a ChatGPT/Codex subscription."""

import os
import queue
import shutil
import tempfile
import threading
import time
import weakref
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

from pydantic import JsonValue, ValidationError

from hugegraph_llm_eval.contracts.domain.judge import ProviderUsage
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.evaluation.judges.base import JudgeDescriptor, JudgeRequest, OutputT
from hugegraph_llm_eval.integrations.judges.attempts import (
    AttemptFailureError,
    AttemptLoopJudge,
    AttemptOutcome,
    failure,
)
from hugegraph_llm_eval.integrations.judges.cli_common import (
    cli_version,
    split_messages,
    strict_json_schema,
    token_count,
)
from hugegraph_llm_eval.integrations.judges.codex_connection import (
    AppServerConnection,
    AppServerProcess,
    ConnectionClosedError,
    RpcError,
    spawn_app_server,
)
from hugegraph_llm_eval.utils.clock import utc_now

PROVIDER = "codex-app-server"
_STARTUP_TIMEOUT_SECONDS = 60.0
_TRANSIENT_KINDS = frozenset({"serverOverloaded", "internalServerError", "flexUnavailable"})
_TRANSIENT_PREFIXES = ("httpConnectionFailed", "responseStream")
_DEFAULT_INSTRUCTIONS = "You are an evaluation judge. Do not use tools. Answer only with the requested JSON."
_TOOL_FEATURES = ("plugins", "apps", "computer_use", "browser_use", "shell_tool", "unified_exec", "multi_agent")
_DEFAULT_CONFIG: Mapping[str, JsonValue] = {
    "include_environment_context": False,
    "include_permissions_instructions": False,
    "include_apps_instructions": False,
    "project_doc_max_bytes": 0,
    "web_search": "disabled",
}
_SUBSCRIPTION_ENV_NAMES = frozenset(
    {
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
    }
)


class _ConnectionHolder:
    """Owns the shared connection; its ``close`` also serves as the finalizer."""

    def __init__(self) -> None:
        self.connection: AppServerConnection | None = None

    def close(self) -> None:
        connection, self.connection = self.connection, None
        if connection is not None:
            connection.close()


class CodexAppServerJudge(AttemptLoopJudge):
    """Runs Judge calls as ephemeral threads on one shared ``codex app-server`` process."""

    def __init__(
        self,
        *,
        model: str,
        effort: str | None = None,
        executable: str = "codex",
        config: Mapping[str, JsonValue] | None = None,
        auth_mode: Literal["inherit", "subscription"] = "inherit",
        disable_user_mcp_servers: bool = True,
        call_timeout_seconds: float = 600.0,
        version: str | None = None,
        clock: Callable[[], datetime] = utc_now,
        spawn: Callable[..., AppServerProcess] = spawn_app_server,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if call_timeout_seconds <= 0:
            msg = "call_timeout_seconds must be positive"
            raise ValueError(msg)
        if auth_mode not in ("inherit", "subscription"):
            msg = "auth_mode must be 'inherit' or 'subscription'"
            raise ValueError(msg)
        provided = dict(config or {})
        if "mcp_servers" in provided:
            raise ValueError("config.mcp_servers cannot be set for an evaluation judge")
        features = provided.pop("features", {})
        if provided:
            keys = ", ".join(sorted(provided))
            raise ValueError(f"unsupported raw Codex config keys: {keys}; use typed options")
        if not isinstance(features, Mapping) or not all(isinstance(name, str) for name in features):
            raise ValueError("config.features must be a string-keyed mapping")
        unknown_features = sorted(set(features) - set(_TOOL_FEATURES))
        if unknown_features:
            raise ValueError(f"unsupported Codex feature flags: {', '.join(unknown_features)}")
        unsafe_features = [name for name, enabled in features.items() if enabled is not False]
        if unsafe_features:
            raise ValueError(f"Codex judge cannot enable tool capabilities: {', '.join(sorted(unsafe_features))}")
        if not disable_user_mcp_servers:
            msg = "disable_user_mcp_servers cannot be false for an evaluation judge"
            raise ValueError(msg)
        merged: dict[str, JsonValue] = {
            **_DEFAULT_CONFIG,
            "features": {**dict.fromkeys(_TOOL_FEATURES, False), **features},
        }
        configuration: JsonValue = {
            "cli_version": version if version is not None else cli_version(executable),
            "effort": effort,
            "auth_mode": auth_mode,
            "route": "openai-chatgpt-account" if auth_mode == "subscription" else "inherited",
            "config": merged,
            "disable_user_mcp_servers": True,
            "sandbox": "read-only",
            "sampling": "provider-controlled",
        }
        super().__init__(
            descriptor=JudgeDescriptor.create(provider=PROVIDER, model=model, configuration=configuration),
            clock=clock,
            monotonic=monotonic,
            sleep=sleep,
        )
        self._executable = executable
        self._effort = effort
        self._config = merged
        self._auth_mode = auth_mode
        self._call_timeout = call_timeout_seconds
        self._spawn = spawn
        self._mcp_overrides: dict[str, JsonValue] = {}
        self._lock = threading.Lock()
        self._holder = _ConnectionHolder()
        self._workdir = tempfile.mkdtemp(prefix="hugegraph-llm-eval-codex-")
        self._isolated_codex_home = Path(self._workdir) / "codex-home"
        self._isolated_codex_home.mkdir(mode=0o700)
        weakref.finalize(self, shutil.rmtree, self._workdir, ignore_errors=True)
        weakref.finalize(self, self._holder.close)

    def close(self) -> None:
        with self._lock:
            self._holder.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _connection(self, timeout: float) -> AppServerConnection:
        with self._lock:
            connection = self._holder.connection
            if connection is None or not connection.alive:
                self._holder.close()
                connection = self._start(min(timeout, _STARTUP_TIMEOUT_SECONDS))
                self._holder.connection = connection
            return connection

    def _start(self, timeout: float) -> AppServerConnection:
        process = self._spawn([self._executable, "app-server"], cwd=self._workdir, env=self._environment())
        connection = AppServerConnection(process)
        try:
            connection.request("initialize", {"clientInfo": {"name": "hugegraph-llm-eval", "version": "1"}}, timeout)
            connection.notify("initialized")
            if self._auth_mode == "subscription":
                self._require_chatgpt_account(connection, timeout)
            self._mcp_overrides = self._verified_isolation_overrides(connection, timeout)
        except BaseException:
            connection.close()
            raise
        return connection

    def _require_chatgpt_account(self, connection: AppServerConnection, timeout: float) -> None:
        account = connection.request("account/read", {"refreshToken": False}, timeout).get("account")
        if not isinstance(account, dict):
            raise AttemptFailureError(
                failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_not_authenticated", False)
            )
        if account.get("type") != "chatgpt":
            raise AttemptFailureError(
                failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_account_not_chatgpt", False)
            )

    def _environment(self) -> dict[str, str]:
        """Use a private Codex home so user hooks and config cannot enter an eval run."""
        env = dict(os.environ)
        source_home = Path(env.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
        auth_file = source_home / "auth.json"
        if auth_file.is_file():
            target_auth = self._isolated_codex_home / "auth.json"
            shutil.copyfile(auth_file, target_auth)
            try:
                target_auth.chmod(0o600)
            except OSError:
                target_auth.unlink(missing_ok=True)
                raise
        if self._auth_mode == "subscription":
            env = {key: value for key, value in env.items() if key.upper() not in _SUBSCRIPTION_ENV_NAMES}
        env["CODEX_HOME"] = str(self._isolated_codex_home)
        return env

    def _verified_isolation_overrides(
        self,
        connection: AppServerConnection,
        timeout: float,
    ) -> dict[str, JsonValue]:
        try:
            result = connection.request("config/read", {"cwd": self._workdir, "includeLayers": False}, timeout)
        except RpcError as exc:
            raise RuntimeError("Cannot verify Codex provider and MCP isolation") from exc
        config = result.get("config")
        if not isinstance(config, dict):
            raise RuntimeError("Codex app-server returned no effective configuration; cannot verify isolation")
        servers = config.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise RuntimeError("Codex app-server returned an invalid MCP configuration")
        return {name: {"enabled": False} for name in servers}

    def _disabled_mcp_servers(self, connection: AppServerConnection, timeout: float) -> dict[str, JsonValue]:
        """Compatibility alias for the fail-closed isolation probe."""
        return self._verified_isolation_overrides(connection, timeout)

    def _attempt(self, request: JudgeRequest[OutputT], timeout: float | None) -> AttemptOutcome:
        limit = self._call_timeout if timeout is None else min(timeout, self._call_timeout)
        deadline = self._monotonic() + limit
        connection = self._connection(limit)
        system, prompt = split_messages(request)
        thread = connection.request("thread/start", self._thread_params(system), self._left(deadline))
        thread_id = _identifier(thread, "thread")
        events = connection.watch(thread_id)
        try:
            turn_params: dict[str, object] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "outputSchema": strict_json_schema(request.response_type),
            }
            if self._effort is not None:
                turn_params["effort"] = self._effort
            start_timeout = self._left(deadline)
            try:
                started = connection.request("turn/start", turn_params, start_timeout)
            except (TimeoutError, ConnectionClosedError) as exc:
                # The server may have accepted the request before the response
                # was lost. Retrying could start another billable turn.
                category = (
                    FailureCategory.TIMEOUT if isinstance(exc, TimeoutError) else FailureCategory.PROVIDER_UNAVAILABLE
                )
                detail = failure(category, "provider_start_outcome_unknown", False)
                raise AttemptFailureError(detail) from exc
            turn_id = _identifier(started, "turn")
            try:
                turn = self._await_turn(connection, events, thread_id, turn_id, deadline)
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    with suppress(Exception):
                        connection.fire("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                raise
            return self._outcome(request, turn, thread_id, thread.get("model"))
        finally:
            connection.unwatch(thread_id)
            connection.fire("thread/unsubscribe", {"threadId": thread_id})

    def _thread_params(self, system: str | None) -> dict[str, object]:
        config = {**self._config, "mcp_servers": self._mcp_overrides}
        params: dict[str, object] = {
            "model": self.descriptor.model,
            "ephemeral": True,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "cwd": self._workdir,
            "baseInstructions": system or _DEFAULT_INSTRUCTIONS,
            "config": config,
        }
        if self._auth_mode == "subscription":
            params["modelProvider"] = "openai"
            config["openai_base_url"] = None
        return params

    def _await_turn(
        self,
        connection: AppServerConnection,
        events: "queue.Queue[dict[str, object] | None]",
        thread_id: str,
        turn_id: str,
        deadline: float,
    ) -> "_Turn":
        turn = _Turn()
        while turn.finished is None:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                connection.fire("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                detail = failure(FailureCategory.TIMEOUT, "provider_timeout", True)
                raise AttemptFailureError(detail, usage=self._usage(turn.tokens))
            try:
                message = events.get(timeout=remaining)
            except queue.Empty:
                continue
            if message is None:
                detail = failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_connection_lost", True)
                raise AttemptFailureError(detail, usage=self._usage(turn.tokens))
            turn.apply(message, turn_id)
        return turn

    def _outcome(
        self,
        request: JudgeRequest[OutputT],
        turn: "_Turn",
        thread_id: str,
        model: object,
    ) -> AttemptOutcome:
        usage = self._usage(turn.tokens)
        finished = turn.finished or {}
        status = finished.get("status")
        if status == "interrupted":
            detail = failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_interrupted", True)
            raise AttemptFailureError(detail, usage=usage)
        if status != "completed":
            raise AttemptFailureError(_error_detail(finished.get("error") or turn.error), usage=usage)
        if not isinstance(turn.text, str):
            detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "missing_structured_output", True)
            raise AttemptFailureError(detail, usage=usage)
        try:
            output = request.response_type.model_validate_json(turn.text)
        except ValidationError as exc:
            detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "invalid_structured_output", True)
            raise AttemptFailureError(detail, usage=usage) from exc
        return AttemptOutcome(
            output=output,
            usage=usage,
            response_id=thread_id,
            response_model=model if isinstance(model, str) else None,
        )

    def _left(self, deadline: float) -> float:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise TimeoutError("call deadline reached")
        return remaining

    def _usage(self, tokens: object) -> ProviderUsage:
        if not isinstance(tokens, dict):
            return self._unreported_usage()
        return self._usage_from_tokens(token_count(tokens, "inputTokens"), token_count(tokens, "outputTokens"))

    def _classify(self, error: Exception) -> FailureDetail:
        if isinstance(error, TimeoutError):
            return failure(FailureCategory.TIMEOUT, "provider_timeout", True)
        if isinstance(error, ConnectionClosedError):
            return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_connection_lost", True)
        if isinstance(error, RpcError):
            return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_request_rejected", False)
        if isinstance(error, FileNotFoundError):
            return failure(FailureCategory.PROVIDER_UNAVAILABLE, "executable_not_found", False)
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_transport_error", False)


@dataclass(slots=True)
class _Turn:
    text: object = None
    tokens: object = None
    error: object = None
    finished: dict[str, object] | None = None

    def apply(self, message: dict[str, object], turn_id: str) -> None:
        raw = message.get("params")
        params = raw if isinstance(raw, dict) else {}
        if params.get("turnId", turn_id) != turn_id:
            return
        method = message.get("method")
        if method == "item/completed":
            item = params.get("item")
            if isinstance(item, dict) and item.get("type") == "agentMessage":
                self.text = item.get("text")
        elif method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage")
            self.tokens = usage.get("total") if isinstance(usage, dict) else None
        elif method == "error" and not params.get("willRetry"):
            self.error = params.get("error")
        elif method == "turn/completed":
            turn = params.get("turn")
            self.finished = turn if isinstance(turn, dict) else {}


def _identifier(result: Mapping[str, object], key: str) -> str:
    item = result.get(key)
    value = item.get("id") if isinstance(item, dict) else None
    if not isinstance(value, str):
        detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "malformed_provider_response", False)
        raise AttemptFailureError(detail)
    return value


def _error_kind(info: object) -> tuple[str | None, object]:
    if isinstance(info, str):
        return info, None
    if isinstance(info, dict) and len(info) == 1:
        kind, body = next(iter(info.items()))
        return kind, body.get("httpStatusCode") if isinstance(body, dict) else None
    return None, None


def _error_detail(error: object) -> FailureDetail:
    kind, status = _error_kind(error.get("codexErrorInfo") if isinstance(error, dict) else None)
    if kind == "usageLimitExceeded":
        return failure(FailureCategory.PROVIDER_RATE_LIMIT, "provider_usage_limit", False)
    if kind == "rateLimitExceeded" or status == 429:
        return failure(FailureCategory.PROVIDER_RATE_LIMIT, "provider_rate_limit", True)
    if kind == "unauthorized" or status in (401, 403):
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_not_authenticated", False)
    if kind == "contextWindowExceeded":
        return failure(FailureCategory.RESOURCE_EXHAUSTED, "context_window_exceeded", False)
    transient = kind in _TRANSIENT_KINDS or (kind is not None and kind.startswith(_TRANSIENT_PREFIXES))
    if transient or (isinstance(status, int) and status >= 500):
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_unavailable", True)
    message = str(error.get("message", "")) if isinstance(error, dict) else ""
    if "invalid_json_schema" in message:
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_request_rejected", False)
    return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_error", False)
