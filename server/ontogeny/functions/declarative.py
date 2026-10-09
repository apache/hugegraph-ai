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
"""Declarative functions: a prompt-shaped body the platform executes itself.

A code function is a file in the package; a declarative one has no file at all.
Its body is a short pipeline of the three things a "smart little function"
actually does — read objects, ask a model, call an endpoint — written in the DSL
where it can be edited from the console, diffed, and pinned by content version.

**The whole point is that it borrows the sandbox's guarantees.** Every step runs
in-process, through exactly the paths a code function reaches over RPC:

* ``read`` goes through the query engine and returns the same assembled rows a
  code function's ``ontogeny.query`` gets, including properties that carry a ``marking``.

  That last part is deliberate, and it is the platform's rule for BOTH runtimes:
  a function body is *trusted, reviewed, capability-scoped server-side logic*,
  not a reader. The system example depends on it — ``maintenance-planning``
  reads ``equipment.site`` (marked ``internal``) so that the row-level
  authorization attribute is taken from the authoritative record instead of from
  the caller ("绝不能由调用方传入"). Masking is a READER-surface control (REST,
  MCP, graph preview); ``read-objects`` is the function-surface control. Applying
  masks here would not harden the platform, it would break that pattern — and
  silently, as a policy denial three steps later.
* ``llm`` goes through the platform gateway with the capability's ``max-calls``
  budget, exactly like ``ontogeny.llm``;
* ``http`` is the platform making the request, not the function: an allowlist is
  required, secrets stay in ``${VAR}`` references resolved at call time, and the
  response is capped.

What declarative functions intentionally do NOT have: loops, branches, or the
ability to write. Writes belong to Actions, where rules and policy already
govern them.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from ..errors import SandboxError

log = logging.getLogger("ontogeny.functions.declarative")

#: ``${name}`` / ``${name.field}`` / ``${name[*].field}``. Deliberately not the
#: property-expression language: this is string interpolation over step results,
#: and pretending otherwise invites writing logic in a template.
_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)((?:\.\w+|\[\*\])*)\}")

#: Response bodies from an http step are capped: a function must not be able to
#: pull an arbitrary amount of the internet into a result payload.
_MAX_RESPONSE_BYTES = 256 * 1024


def _walk(value: Any, path: str) -> Any:
    """Resolve ``.field`` / ``[*]`` segments against a step result or parameter."""
    cur = value
    for seg in [s for s in path.split(".") if s]:
        if seg == "[*]":
            if not isinstance(cur, list):
                raise SandboxError(f"cannot expand ${{...[*]}} on {type(cur).__name__}")
            continue
        if isinstance(cur, list):
            # a list of rows: project the field from every row
            cur = [row.get(seg) if isinstance(row, dict) else None for row in cur]
        elif isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            raise SandboxError(f"cannot look up {seg!r} on {type(cur).__name__}")
    return cur


def _render_text(value: Any) -> str:
    """How a value reads inside a prompt.

    A list of rows becomes one line per row — the shape a model needs to reason
    about records — rather than a JSON dump it has to parse first.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        if not value:
            return "(none)"
        if all(isinstance(r, dict) for r in value):
            return "\n".join(
                "- " + ", ".join(f"{k}={v}" for k, v in r.items() if v is not None)
                for r in value
            )
        return "\n".join(f"- {_render_text(v)}" for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items() if v is not None)
    return str(value)


def _llm_budget(cfg: dict | None) -> int:
    """How many model calls a declaration permits.

    ``max-calls: 0`` means ZERO, not "unset": the declaration is authoritative,
    and a falsy-zero bug here would grant MORE calls than declared (10), which is
    the one direction a budget must never fail in.
    """
    if not cfg or cfg.get("max-calls") is None:
        return 10
    return max(0, int(cfg["max-calls"]))


class _Template:
    """Interpolation over a call's parameters and already-computed steps."""

    def __init__(self, params: dict[str, Any], steps: dict[str, Any]) -> None:
        self.params = params
        self.steps = steps

    def refs(self, text: str) -> list[str]:
        return [m.group(1) for m in _REF.finditer(text)]

    def resolve(self, ref: str, path: str) -> Any:
        if ref in self.steps:
            root = self.steps[ref]
        elif ref in self.params:
            root = self.params[ref]
        else:
            raise SandboxError(f"unknown reference ${{{ref}}}: not a parameter or an earlier step")
        return _walk(root, path)

    def render_text(self, text: str) -> str:
        def sub(m: "re.Match[str]") -> str:
            return _render_text(self.resolve(m.group(1), m.group(2)))

        return _REF.sub(sub, text)

    def render(self, value: Any) -> Any:
        """Recursively resolve a value. A string that is ONE bare reference keeps
        the referenced value's own type (so ``returns: ${rows}`` returns a list);
        a string with surrounding text is interpolated into a string."""
        if isinstance(value, str):
            bare = _REF.fullmatch(value)
            if bare:
                return self.resolve(bare.group(1), bare.group(2))
            return self.render_text(value)
        if isinstance(value, dict):
            return {k: self.render(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.render(v) for v in value]
        return value


class DeclarativeRuntime:
    """Executes ``runtime: declarative`` functions against the platform itself.

    Collaborators are the same objects the sandbox talks to over RPC, so the two
    runtimes cannot drift: `query` is the engine call the sandbox's ``query`` RPC
    lands on, `llm` is the gateway adapter ``ontogeny.llm`` is routed to.
    """

    def __init__(self, *, llm=None, repo=None, compiled=None,
                 http_allowlist=None, resolve_ref=None,
                 llm_call_timeout_s: float = 60.0,
                 timeout_s: float = 30.0, http: httpx.AsyncClient | None = None) -> None:
        # resolves ${VAR} in a capability's allow list / step urls (the same
        # scope DSL endpoint references use)
        self.resolve_ref = resolve_ref
        self.llm = llm
        self.repo = repo
        self.compiled = compiled
        # deployment-level allowlist: when set, an http step must satisfy BOTH it
        # and the capability's own list
        self.http_allowlist = tuple(http_allowlist or ())
        self.llm_call_timeout_s = llm_call_timeout_s
        self.timeout_s = timeout_s
        self._http = http

    async def client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=False)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ---------------------------------------------------------------- guards

    @staticmethod
    def _read_capability(fn) -> set[str]:
        allowed: set[str] = set()
        for cap in fn.spec.capabilities:
            data = cap.model_dump(exclude_none=True)
            if "read-objects" in data:
                allowed.update(data["read-objects"])
        return allowed

    @staticmethod
    def _llm_capability(fn) -> dict | None:
        for cap in fn.spec.capabilities:
            data = cap.model_dump(exclude_none=True)
            if "llm" in data:
                cfg = data["llm"]
                return cfg if isinstance(cfg, dict) else {}
        return None

    @staticmethod
    def _http_capability(fn) -> dict | None:
        for cap in fn.spec.capabilities:
            data = cap.model_dump(exclude_none=True)
            if "http" in data:
                cfg = data["http"]
                return cfg if isinstance(cfg, dict) else {}
        return None

    def _allowed_hosts(self, fn) -> list[str]:
        """Allowed hosts, with ``${VAR}`` entries resolved against the deployment.

        A host is environment-specific (staging and production never match), so a
        literal list would force a DSL edit per environment — exactly what the
        ``${VAR}`` convention exists to avoid. The operator owns the variable, so
        the allowlist stays the operator's decision; an unset variable is an
        error rather than a silently skipped entry.
        """
        cfg = self._http_capability(fn) or {}
        out: list[str] = []
        for entry in (cfg.get("allow") or []):
            text = str(entry)
            if "${" in text:
                if self.resolve_ref is None:
                    raise SandboxError(f"cannot resolve {text!r}: no environment scope configured")
                try:
                    text = self.resolve_ref(text)
                except KeyError as exc:
                    raise SandboxError(f"http allowlist entry {entry!r} is unresolved: {exc}") from exc
            out.append(text)
        return out

    @staticmethod
    def _host_allowed(host: str, allow: list[str]) -> bool:
        return any(host == a or host.endswith("." + a.lstrip(".")) for a in allow)

    async def _check_http_url(self, fn, url: str) -> None:
        cfg = self._http_capability(fn)
        if cfg is None:
            raise SandboxError("capability denied: this function does not declare the http capability")
        parsed = httpx.URL(url)
        if parsed.scheme not in ("http", "https"):
            raise SandboxError(f"http step must use http(s), got {parsed.scheme!r}")
        if parsed.userinfo:
            raise SandboxError("http step must not embed credentials in the URL; use ${VAR} headers")
        host = parsed.host or ""
        allow = self._allowed_hosts(fn)
        if not allow:
            raise SandboxError("capability denied: http capability declares no allowed hosts")
        if not self._host_allowed(host, allow):
            raise SandboxError(f"capability denied: {host!r} is not in the http allowlist {allow}")
        if self.http_allowlist and not self._host_allowed(host, list(self.http_allowlist)):
            raise SandboxError(f"http denied by deployment allowlist: {host!r}")

    # --------------------------------------------------------------- execute

    async def run(self, session, fn, params: dict[str, Any]) -> Any:
        from ..engine.service import assemble_row

        spec = fn.spec
        steps: dict[str, Any] = {}
        tpl = _Template(params, steps)
        read_ok = self._read_capability(fn)
        llm_cfg = self._llm_capability(fn)
        llm_calls = 0
        llm_budget = _llm_budget(llm_cfg)

        for step in spec.steps:
            if step.kind == "read":
                if step.object not in read_ok:
                    raise SandboxError(
                        f"capability denied: read-objects does not include {step.object!r}"
                    )
                if self.compiled is None or step.object not in self.compiled.objects:
                    raise SandboxError(f"unknown object type {step.object!r}")
                filt = tpl.render(step.filter) if step.filter else None
                rows, _total = await self.repo.query(
                    session, step.object, filt=filt, limit=int(step.limit or 100),
                )
                # the same assembly the sandbox's query RPC performs -- see the
                # module docstring on why a function sees real values
                steps[step.id] = [assemble_row(self.compiled, step.object, r) for r in rows]
            elif step.kind == "llm":
                if llm_cfg is None:
                    raise SandboxError("capability denied: this function does not declare the llm capability")
                if llm_calls >= llm_budget:
                    raise SandboxError(f"llm call budget exhausted ({llm_budget})")
                if self.llm is None:
                    raise SandboxError("platform LLM is not configured (set ONTOGENY_LLM_BASE_URL)")
                llm_calls += 1
                prompt = tpl.render_text(step.prompt or "")
                system = tpl.render_text(step.system) if step.system else None
                model_override = (llm_cfg or {}).get("model")
                client = self.llm
                if model_override and model_override != getattr(self.llm, "model", None):
                    client = self.llm.scoped(str(model_override))
                out = await client.chat(
                    ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": prompt}]
                )
                steps[step.id] = out.get("content")
            elif step.kind == "http":
                url = tpl.render_text(step.url or "")
                if "${" in url and self.resolve_ref is not None:
                    url = self.resolve_ref(url)
                await self._check_http_url(fn, url)
                method = (step.method or "GET").upper()
                body = tpl.render(step.body) if step.body is not None else None
                headers = {k: tpl.render_text(v) for k, v in (step.headers or {}).items()}
                c = await self.client()
                resp = await c.request(method, url, json=body, headers=headers)
                text = resp.text[:_MAX_RESPONSE_BYTES]
                try:
                    steps[step.id] = {"status": resp.status_code, "json": json.loads(text)}
                except json.JSONDecodeError:
                    steps[step.id] = {"status": resp.status_code, "text": text}
            else:
                raise SandboxError(f"unknown step kind {step.kind!r}")

        if spec.returns_step:
            if spec.returns_step not in steps:
                raise SandboxError(
                    f"returns_step {spec.returns_step!r} is not a step of this function"
                )
            return steps[spec.returns_step]
        # no step named: hand back everything, keyed by step id. A one-step
        # function still gets a dict here — predictable beats clever, because a
        # caller must not have to know how many steps a function happens to have.
        return steps
