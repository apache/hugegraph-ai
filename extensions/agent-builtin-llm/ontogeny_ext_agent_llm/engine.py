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
"""Builtin LLM engine (engine.kind = builtin-llm): the paradigm's reference
implementation of AgentEngine.

A deliberately small loop — plan → tool → observe → … → final:

1. build a prompt: task + effective tool catalog (JSON schema) + transcript
2. llm.chat → extract strict JSON: {"tool": name, "args": {...}} or {"final": str}
3. unparseable → re-ask with the error (max 2 retries), then give up cleanly
4. executor.call_tool(...) — the ONLY execution door; every gate lives in the
   broker behind it
5. stop on final / pending_approval (blocked_on_approval) / budget outcome /
   steps exhausted; every step lands in ontogeny_agent_step via the broker (I4)

The executor is the transport detail (agent-paradigm §3): by default the
engine drives over MCP — the SAME protocol and tool surface external agents
use, on an in-memory session — so the MCP path is exercised in production
and in tests, never a privileged shortcut. When the optional ``mcp`` extra
is absent the engine degrades to in-process broker calls (identical gates,
same envelopes; only the transport differs). ``last_transport`` records
which one drove, for observability and tests.

Session vs run: a `final` answer (or an LLM failure) ends the RUN, not the
SESSION -- the session returns to `open` with the round's result recorded, so
the next instruction drives it again. A session only terminates when its
budget threshold fires (budget_exhausted) or a human finishes it explicitly
(POST /finish); both can be re-opened by driving again (start_run).

The LLM only ever chooses tools; facts come exclusively from tool results.
No memory, no RAG, no multi-agent — by design (agent-paradigm.md §0).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from ontogeny.llm import LLMError, extract_json

log = logging.getLogger("ontogeny.agent.engine")

_MAX_RESULT_CHARS = 2000
_MAX_REPAIRS = 2
_MAX_TRANSCRIPT_CHARS = 60_000

_SYSTEM_PROMPT = """You drive an operational-ontology agent session. Each turn you answer \
with STRICT JSON only — no prose, no code fences — choosing ONE action:

  {"thought": "<why>", "tool": "<tool name>", "args": {...}}   to call a tool, or
  {"thought": "<why>", "final": "<conclusion for the human>"}

Rules:
- "thought" is REQUIRED and is shown to the human: one or two short sentences of \
your actual reasoning — what you know so far, what is still missing, and why this \
choice. Write it in the language of the task. Do not merely restate the tool call.
- Only tools from the provided catalog; args must match the tool's input_schema.
- Facts come exclusively from tool results. If the tools did not answer the task, \
say so in "final" instead of inventing an answer.
- Writes may pause for human approval (outcome pending_approval); when you see one, \
usually report it in "final" unless the task clearly requires more steps.
- Prefer finishing with a concise, factual "final" over redundant calls."""


class ChatClient(Protocol):
    """Structural type: satisfied by OllamaChat and by test stubs."""

    async def chat(self, messages: list[dict[str, str]], **kw: Any) -> dict[str, Any]: ...


class ToolExecutor(Protocol):
    """The transport seam: how the engine's tool calls reach the broker.

    ``mcp`` speaks the MCP protocol (dogfooding the external surface);
    ``broker`` is the in-process fallback when the mcp extra is absent.
    """

    kind: str

    async def call_tool(self, session_id: int, tool: str, args: dict[str, Any],
                        *, thought: str = "") -> dict[str, Any]: ...


class McpExecutor:
    """Drives the session's tools over MCP (in-memory client session)."""

    kind = "mcp"

    def __init__(self, client) -> None:
        self.client = client

    async def call_tool(self, session_id: int, tool: str, args: dict[str, Any],
                        *, thought: str = "") -> dict[str, Any]:
        out = await self.client.call_tool(tool, {**args, "session_id": session_id,
                                                 "thought": thought})
        return out


class BrokerExecutor:
    """In-process fallback: the broker door without the MCP transport."""

    kind = "broker"

    def __init__(self, broker) -> None:
        self.broker = broker

    async def call_tool(self, session_id: int, tool: str, args: dict[str, Any],
                        *, thought: str = "") -> dict[str, Any]:
        return await self.broker.call_tool(session_id, tool, args,
                                           engine=True, thought=thought)


@dataclass
class EngineResult:
    status: str                 # the RUN's outcome: finished | blocked_on_approval | budget_exhausted
    result: dict[str, Any]


class BuiltinLlmEngine:
    def __init__(self, sc, llm: ChatClient | None,
                 *, executor: ToolExecutor | None = None) -> None:
        """``sc`` is the ServiceContext (broker for session bookkeeping, and
        the MCP surface when the extra is installed). Tests may pin an
        ``executor``; without one the engine prefers MCP and falls back."""
        self.sc = sc
        self.broker = sc.agents
        self.llm = llm
        self._pinned = executor
        self.last_transport: str | None = None

    async def _open_executor(self, stack) -> ToolExecutor:
        """Prefer the MCP transport; degrade to in-process broker calls when
        the optional extra is absent (governance identical, transport not)."""
        if self._pinned is not None:
            return self._pinned
        try:
            from ontogeny.mcp_server import in_process_mcp_session

            client = await stack.enter_async_context(in_process_mcp_session(self.sc))
            return McpExecutor(client)
        except Exception:  # noqa: BLE001 -- missing extra: degrade, don't die
            log.warning("builtin-llm: mcp extra not available, engine falls back "
                        "to in-process broker calls (install 'ontogeny[mcp]')")
            return BrokerExecutor(self.broker)

    async def drive(self, session_id: int, *, resume: bool = False) -> EngineResult:
        """Drive without an LLM is a configuration error; the run endpoint
        surfaces it as 503 LLM_NOT_CONFIGURED (checked before start)."""
        if self.llm is None:
            raise RuntimeError("LLM_NOT_CONFIGURED")

        session = await self.broker.get_session(session_id)
        task = session.get("task") or "Complete the task."
        tools: dict[str, Any] = {
            name: {"name": t["name"], "kind": t["kind"], "target": t.get("target"),
                   "description": t["description"], "writes": t["writes"],
                   "input_schema": t.get("input_schema") or {}}
            for name, t in (session.get("tools") or {}).items()
        }
        from contextlib import AsyncExitStack

        async with AsyncExitStack() as stack:
            executor = await self._open_executor(stack)
            self.last_transport = executor.kind
            return await self._drive_loop(session_id, task, tools, executor)

    async def _drive_loop(self, session_id: int, task: str, tools: dict[str, Any],
                          executor: ToolExecutor) -> EngineResult:
        await self.broker.set_status(session_id, "running")

        repairs = 0
        # a dying engine must still release the session into a terminal state
        try:
            while True:
                fresh = await self.broker.get_session(session_id)
                budget = fresh["budget"]
                # steps == 0 means UNLIMITED (a session opened with explicit
                # "no budget"): the gate fires only when a positive cap exists
                if budget["steps"] and budget["steps_used"] >= budget["steps"]:
                    await self.broker.set_status(session_id, "budget_exhausted",
                                                 {"error": "step budget exhausted"})
                    return EngineResult("budget_exhausted", {"error": "step budget exhausted"})

                transcript = self._transcript(fresh.get("steps") or [])
                messages = self._prompt(task, tools, transcript)
                try:
                    decision = await self._decide(messages, tools)
                except LLMError as exc:
                    # an LLM failure ends the run, not the session: keep the
                    # session open with the error recorded, so the operator can
                    # re-drive it (or end it by hand) instead of losing it
                    await self.broker.set_status(
                        session_id, "open", {"error": f"llm: {exc.message}"})
                    return EngineResult("finished", {"error": f"llm: {exc.message}"})

                # the model's own reasoning for this turn; shown to the human in
                # the step timeline and fed back so the loop stays coherent
                thought = str(decision.get("thought") or "").strip()

                if "final" in decision:
                    final = str(decision["final"])
                    # a final answer ends THIS RUN, not the session: the session
                    # returns to `open` carrying the round's conclusion, ready
                    # for the next instruction. Only the budget threshold or an
                    # explicit human finish terminates a session.
                    await self.broker.set_status(
                        session_id, "open",
                        {"final": final, **({"thought": thought} if thought else {})})
                    return EngineResult("finished", {"final": final})

                tool = str(decision.get("tool") or "")
                args = decision.get("args") or {}
                out = await executor.call_tool(session_id, tool, args, thought=thought)
                outcome = str(out.get("outcome"))

                if outcome in ("AGENT_TOOL_NOT_ALLOWED", "NOT_FOUND", "MCP_TOOL_ERROR"):
                    repairs += 1
                    if repairs > _MAX_REPAIRS:
                        # give up on the RUN, keep the session drivable: the
                        # error is recorded and a human can re-steer or finish
                        await self.broker.set_status(
                            session_id, "open", {"error": f"engine gave up: {outcome}"})
                        return EngineResult("finished", {"error": f"engine gave up: {outcome}"})
                    continue  # the failed call is in the transcript; model self-corrects
                if outcome == "AGENT_BUDGET_EXCEEDED":
                    await self.broker.set_status(session_id, "budget_exhausted",
                                                 {"error": out.get("error")})
                    return EngineResult("budget_exhausted", {"error": out.get("error")})
                if outcome == "pending_approval":
                    await self.broker.set_status(
                        session_id, "blocked_on_approval",
                        {"blocked_on": out.get("approval_id"),
                         "message": "write is awaiting human approval; approve, then run again"})
                    return EngineResult("blocked_on_approval",
                                        {"approval_id": out.get("approval_id")})
                if outcome == "AGENT_SESSION_CLOSED":
                    return EngineResult("finished", {"error": out.get("error")})
                # ok / POLICY_DENIED / RULE_REJECTED / executed …: keep looping
        except Exception as exc:  # noqa: BLE001 -- crash ⇒ release the session
            # back to `open` with the crash recorded, never a stuck `running`
            await self.broker.set_status(
                session_id, "open",
                {"error": f"engine crashed: {type(exc).__name__}: {exc}"})
            return EngineResult("finished", {"error": f"engine crashed: {exc}"})

    # ------------------------------------------------------------------ parts

    async def _decide(self, messages: list[dict[str, str]],
                      tools: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.llm is not None
        if tools and getattr(self.llm, "supports_tool_calls", False):
            return await self._decide_via_tool_calls(messages, tools)
        out = await self.llm.chat(messages)
        try:
            decision = extract_json(out.get("content") or "")
        except LLMError:
            decision = None
        if not isinstance(decision, dict) or ("final" not in decision and "tool" not in decision):
            raise LLMError("model did not return a tool/final JSON decision")
        return decision

    async def _decide_via_tool_calls(self, messages: list[dict[str, str]],
                                     tools: dict[str, Any]) -> dict[str, Any]:
        """Native function-calling, when the provider adapter advertises it
        (``ChatClient.supports_tool_calls = True``). The JSON protocol stays
        the default and the fallback -- it works on any model, and the two
        produce the same decision dict."""
        schemas = [{
            "type": "function",
            "function": {
                "name": name,
                "description": t["description"],
                "parameters": t["input_schema"] or {"type": "object", "properties": {}},
            },
        } for name, t in tools.items()]
        out = await self.llm.chat(messages, tools=schemas)
        calls = out.get("tool_calls") or []
        if calls:
            first = calls[0]
            call = first.get("function", first)
            args = call.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except (TypeError, ValueError) as exc:
                    raise LLMError(f"model returned unparsable tool arguments: {exc}")
            return {"thought": str(out.get("content") or "")[:4000],
                    "tool": str(call.get("name") or ""), "args": args or {}}
        content = str(out.get("content") or "")
        try:
            decision = extract_json(content)
        except LLMError:
            decision = None
        if isinstance(decision, dict) and ("final" in decision or "tool" in decision):
            return decision
        if content.strip():
            return {"thought": "", "final": content}
        raise LLMError("model returned neither a tool call nor a final answer")

    def _prompt(self, task: str, tools: dict[str, Any],
                transcript: list[dict[str, Any]]) -> list[dict[str, str]]:
        catalog = {
            name: {"description": t["description"], "input_schema": t["input_schema"]}
            for name, t in tools.items()
        }
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "task": task,
                "tools": catalog,
                "transcript": self._bounded(transcript),
            }, ensure_ascii=False)},
        ]

    @staticmethod
    def _bounded(transcript: list[dict[str, Any]],
                 limit: int = _MAX_TRANSCRIPT_CHARS) -> list[dict[str, Any]]:
        """Keep the prompt inside a total character budget: long sessions
        slide a window over their own middle (the earliest steps are the
        most redundant -- the model already acted on them), with an explicit
        marker so the elision is visible, never silent."""
        def _size(steps: list[dict[str, Any]]) -> int:
            return len(json.dumps(steps, ensure_ascii=False, default=str))

        if _size(transcript) <= limit:
            return transcript
        kept = list(transcript)
        dropped = 0
        while kept and _size(kept) > limit:
            kept.pop(0)
            dropped += 1
        return [{"_elided": f"{dropped} earlier step(s) omitted to fit the "
                            "context window"}] + kept

    def _transcript(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for s in steps:
            out.append({
                "thought": s.get("thought") or None,
                "tool": s.get("tool"),
                "args": _truncated_json(s.get("args")),
                "outcome": s.get("outcome"),
                "result": _truncated_json(s.get("detail")),
            })
        return out


def _truncated_json(value: Any, limit: int = _MAX_RESULT_CHARS) -> Any:
    if value is None:
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)
    if len(text) <= limit:
        return value
    return {"_truncated": text[:limit]}
