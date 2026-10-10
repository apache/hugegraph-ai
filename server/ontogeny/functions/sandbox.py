# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Function sandbox: subprocess isolation + capability-scoped query SDK.

The child never touches the database: every ``ontogeny.query`` travels over stdio
JSON-RPC to this parent, which enforces the declared capabilities
(``read-objects: [...]``) before executing read-only queries. Hard resource
limits (CPU / address space / file descriptors) are applied at spawn time on
POSIX; a wall-clock timeout kills runaway processes.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any

from ..errors import SandboxError
from ..stores.repo import ObjectRepository


def _limits() -> None:  # pragma: no cover -- preexec in the child process
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (512 << 20, 512 << 20))
        except (ValueError, OSError):
            pass  # macOS disallows RLIMIT_AS in some configurations
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except Exception:
        pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def function_source_path(compiled, function_resource) -> Path:
    """Where this function's code must live: ``<package_root>/functions/<file>``.

    Resolution only — it does NOT require the file to exist. Callers that need
    to run the function (the sandbox) check that themselves and can explain the
    failure; callers that need to *report* the situation (the console showing
    "what code runs here?") need the path even when it is missing, which is
    exactly the case a canvas-created function starts in.
    """
    file, _, func = function_resource.spec.entry.partition(":")
    if not func:
        raise SandboxError(f"entry must be 'file.py:function', got {function_resource.spec.entry!r}")
    return Path(compiled.package_root) / "functions" / file


def _llm_budget(cfg: dict | None) -> int:
    """How many model calls a declaration permits.

    ``max-calls: 0`` means ZERO, not "unset": the declaration is authoritative,
    and a falsy-zero bug here would grant MORE calls than declared (10), which is
    the one direction a budget must never fail in.
    """
    if not cfg or cfg.get("max-calls") is None:
        return 10
    return max(0, int(cfg["max-calls"]))


def sandbox_env(server_dir: str) -> dict[str, str]:
    """Environment allowlist, not inheritance: the child used to receive the
    WHOLE process env (DB DSN, HUGEGRAPH credentials, LLM API keys). A
    sandboxed function is package code, but "resource fence, not security
    boundary" is a claim we only get to make if secrets are not handed over
    by default. Operators can widen the list explicitly via
    ``ONTOGENY_SANDBOX_ENV_PASSTHROUGH`` (comma-separated names)."""
    passthrough = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "HOME", "TMPDIR",
                   "SYSTEMROOT", "COMSPEC", "PYTHONIOENCODING", "PYTHONUTF8"}
    for var in os.environ.get("ONTOGENY_SANDBOX_ENV_PASSTHROUGH", "").split(","):
        if var.strip():
            passthrough.add(var.strip())
    env = {k: v for k, v in os.environ.items() if k in passthrough}
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (server_dir, env.get("PYTHONPATH", "")) if p
    )
    # never drop __pycache__ into the user's ontology package (it is a git
    # working tree: bytecode would show up as untracked noise and would
    # change the package's content hash for anything that digests the tree)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class FunctionSandbox:
    def __init__(self, compiled, repo: ObjectRepository, *, timeout_s: float = 10.0,
                 llm=None, llm_call_timeout_s: float = 60.0) -> None:
        self.compiled = compiled
        self.repo = repo
        self.timeout_s = timeout_s
        self.llm = llm  # platform LLM gateway (ontogeny.llm.ChatClient contract); None = not configured
        # Wall clock a single ``ontogeny.llm`` round trip may take. The base budget
        # above is deliberately tight -- it bounds local work on object rows --
        # but a model round trip is not local work: a 27B model over the network
        # routinely answers in 10s+, so a function that declares the capability
        # would ALWAYS be killed by a 10s wall clock before its model reply came
        # back. See ``_budget`` for how the two combine.
        self.llm_call_timeout_s = llm_call_timeout_s

    def _budget(self, function_resource) -> float:
        """Wall clock allowed for one invocation of this function.

        The declared capability buys the time it needs, in proportion to its own
        declared call budget: a function that may make N model calls gets the
        local budget plus N call timeouts. Everything is still bounded -- the
        extra time is never open-ended, and a function that declares no ``llm``
        keeps the original tight limit.
        """
        cfg = self._llm_capability(function_resource)
        if cfg is None:
            return self.timeout_s
        calls = _llm_budget(cfg)
        return self.timeout_s + max(1, calls) * self.llm_call_timeout_s

    def _read_objects_capability(self, function_resource) -> set[str]:
        allowed: set[str] = set()
        for cap in function_resource.spec.capabilities:
            data = cap.model_dump(exclude_none=True)
            if "read-objects" in data:
                allowed.update(data["read-objects"])
        return allowed

    def _llm_capability(self, function_resource) -> dict | None:
        """Declared llm capability config: True -> {} / {model, max-calls, ...}."""
        for cap in function_resource.spec.capabilities:
            data = cap.model_dump(exclude_none=True)
            if "llm" in data:
                cfg = data["llm"]
                return cfg if isinstance(cfg, dict) else {}
        return None

    def _entry_path(self, function_resource) -> Path:
        file, _, func = function_resource.spec.entry.partition(":")
        if not func:
            raise SandboxError(f"entry must be 'file.py:function', got {function_resource.spec.entry!r}")
        root = Path(self.compiled.package_root)
        path = function_source_path(self.compiled, function_resource)
        if not path.is_file():
            if not root.is_dir() or not (root / "ontology.yaml").is_file():
                raise SandboxError(
                    f"cannot locate function source {file!r}: the ontology snapshot was "
                    f"loaded from the registry and has no package directory on disk. "
                    f"Set ONTOGENY_PACKAGE_ROOT to the checked-out ontology package "
                    f"(currently {self.compiled.package_root!r}).",
                    details={"entry": function_resource.spec.entry, "package_root": str(root)},
                )
            raise SandboxError(f"function source not found: {path}")
        return path

    async def run(self, session, function_resource, params: dict[str, Any]) -> Any:
        return await self._spawn(session, function_resource,
                                 {"type": "invoke", "params": _jsonable(params)})

    async def run_source(self, session, function_resource, source: str,
                         params: dict[str, Any]) -> Any:
        """One invocation of text straight from the editor, persisting nothing.

        The console's "Test run" needs an answer for code that may never be
        saved, so the buffer is written to a throwaway file OUTSIDE the package
        (a stray file in ``functions/`` would change the package's content hash
        and show up as git noise) and the child loads that instead. Everything
        else — entry name, capabilities, budget — is still the declared
        function's, so a test run proves exactly what a save would run.
        """
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ontogeny-fn-test-") as tmp:
            path = Path(tmp) / "buffer.py"
            path.write_text(source, encoding="utf-8")
            return await self._spawn(session, function_resource,
                                     {"type": "invoke", "params": _jsonable(params)},
                                     path=path)

    async def map_rows(self, session, function_resource, rows: list[dict[str, Any]],
                       params: dict[str, Any] | None = None, *, object_param: str = "obj") -> list[Any]:
        """Batch mode for the derivation worker: ONE subprocess evaluates the
        function per row (the loop runs inside the child), values returned in
        row order. Same capability enforcement as run()."""
        return await self._spawn(session, function_resource, {
            "type": "map", "rows": _jsonable(rows), "params": _jsonable(params or {}),
            "object_param": object_param,
        })

    async def _spawn(self, session, function_resource, init_message: dict[str, Any],
                     *, path: Path | None = None) -> Any:
        entry = function_resource.spec.entry
        path = path or self._entry_path(function_resource)
        _, func = entry.split(":", 1)
        allowed = self._read_objects_capability(function_resource)

        server_dir = str(Path(__file__).resolve().parent.parent.parent)
        env = sandbox_env(server_dir)

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "ontogeny.functions.child", str(path), func,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            preexec_fn=_limits if os.name == "posix" else None,
        )
        assert proc.stdin and proc.stdout

        llm_cfg = self._llm_capability(function_resource)
        llm_budget = _llm_budget(llm_cfg)
        llm_used = 0

        async def child_main() -> Any:
            proc.stdin.write((json.dumps(init_message) + "\n").encode())
            await proc.stdin.drain()
            nonlocal llm_used
            while True:
                line = await proc.stdout.readline()
                if not line:
                    raise SandboxError("sandbox exited before returning a result")
                msg = json.loads(line)
                if msg.get("type") == "rpc":
                    method = msg.get("method")
                    if method == "llm":
                        if llm_used >= llm_budget:
                            raise SandboxError(
                                f"llm call budget exhausted ({llm_budget}) for {function_resource.spec.entry!r}"
                            )
                        llm_used += 1
                        result = await self._handle_llm_rpc(msg, llm_cfg)
                    else:
                        result = await self._handle_rpc(session, msg, allowed)
                    proc.stdin.write((json.dumps({"id": msg["id"], **result}) + "\n").encode())
                    await proc.stdin.drain()
                elif msg.get("type") in ("result", "values"):
                    return msg.get("value", msg.get("values"))
                elif msg.get("type") == "error":
                    raise SandboxError(f"sandboxed function failed: {msg.get('error')}")

        budget = self._budget(function_resource)
        try:
            return await asyncio.wait_for(child_main(), timeout=budget)
        except asyncio.TimeoutError as exc:
            raise SandboxError(f"function {entry!r} exceeded {budget:g}s wall clock") from exc
        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

    async def _handle_llm_rpc(self, msg: dict, cfg: dict | None) -> dict:
        """LLM calls ride the platform gateway: budgeted, audited via telemetry,
        and the child process itself never touches the network."""
        import logging

        if cfg is None:
            return {"error": "capability denied: this function does not declare the llm capability"}
        if self.llm is None:
            return {"error": "platform LLM is not configured (set ONTOGENY_LLM_BASE_URL)"}
        params = msg.get("params") or {}
        prompt, messages, system = params.get("prompt"), params.get("messages"), params.get("system")
        model_override = cfg.get("model")
        try:
            if model_override and model_override != getattr(self.llm, "model", None):
                # honour a declared model override through the adapter's scoped
                # client (same gateway + budget, different model name)
                scoped = self.llm.scoped(str(model_override))
                out = await scoped.chat(
                    ([{"role": "system", "content": system}] if system else [])
                    + (messages or [{"role": "user", "content": prompt or ""}])
                )
            else:
                out = await self.llm.chat(
                    ([{"role": "system", "content": system}] if system else [])
                    + (messages or [{"role": "user", "content": prompt or ""}])
                )
        except Exception as exc:  # noqa: BLE001 -- provider errors become sandbox errors
            logging.getLogger("ontogeny.sandbox").warning("llm rpc failed: %s", exc)
            return {"error": f"llm call failed: {exc}"}
        return {"result": {"content": out.get("content"), "thinking": out.get("thinking")}}

    async def _handle_rpc(self, session, msg: dict, allowed: set[str]) -> dict:
        if msg.get("method") != "query":
            return {"error": f"unknown method {msg.get('method')!r}"}
        params = msg.get("params") or {}
        object_type = str(params.get("object_type"))
        if object_type not in allowed:
            return {"error": f"capability denied: read-objects does not include {object_type!r}"}
        if object_type not in self.compiled.objects:
            return {"error": f"unknown object type {object_type!r}"}
        rows, _total = await self.repo.query(
            session, object_type, filt=params.get("filter"),
            limit=int(params.get("limit") or 100),
        )
        # hand functions the same object shape the API returns: derived
        # properties computed, so business logic never reads a silent None
        from ..engine.service import assemble_row

        return {"result": _jsonable([assemble_row(self.compiled, object_type, r) for r in rows])}
