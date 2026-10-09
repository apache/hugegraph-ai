# 05 · Agent Governance（agent/broker.py · agent/engines/ · mcp_server.py · AgentPlugin）

> Part of [Part I · Architecture](../README.md#part-i--architecture)

**[中文](../../architecture/05-agent-governance.md)** | English

An agent is a **first-class resource declared in the DSL**: the plugin carries a frozen identity (the permission surface), a tool allowlist, an approval stance and a budget.
The MCP tool surface mounts at **`/mcp`** when the service starts (streamable HTTP · JSON mode). Every tool carries the reserved parameters `plugin` + `session_id` — sessionful calls funnel into **the broker.call_tool single gate** and execute inside the plugin identity, that session's budget and the tool catalog, leaving a trace; sessionless calls are **read-only** (writes return `WRITE_REQUIRES_SESSION`; the default `mcp-agent` shared identity is rejected wholesale by role-gated policies — **by design: without a declaration you can do nothing**).

**Driver authentication**: agent REST endpoints and /mcp record the logged-in driver (mandatory in production when dev_auth is off), so every trace step is attributable (step.driver = engine / user / anonymous).
**View filtering**: tools/list with the `X-Ontogeny-Plugin` header shows only that plugin's effective catalog (a pure view; enforcement still uses the broker's frozen catalog).

```yaml
# agents/sales-copilot.yaml
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata: { name: sales-copilot }
spec:
  principal:
    id: "agent:sales-copilot"
    Role: [sales_rep]        # ← the permission surface (I1)
    site: north
  transport: { kind: http }
  tools:
    allow: [ describe_ontology, search_sales_order,
             search_customer, traverse_graph,
             act_confirm_sales_order ]
  approval: { writes: confirm }   # writes go to approval
  budget: { steps: 30, wall_ms: 90000,
            writes_per_session: 3 }
```

**The journey of one agent write (agent/broker.py)**:

1. **open_session**: plugin + task → session (budget activated)
2. **call_tool**: tool-catalog check → identity switched to the plugin principal
3. **read tools**: read-only execution, one step record each
4. **write tools**: validate first (a free rehearsal) → approval gate → suspended pending approval, **not executed before approval**
5. **human decision**: someone holding the same action permission approves/refuses → only approval executes the five stages
6. **budget**: steps / wall_ms / writes — any overrun terminates the session; **no cross-plugin jumps** (escape prevention)

**Engine selection (AgentEngineSpec)** (external · third-party LLMs / agent runtimes): `engine.kind` is one of three:
**builtin-llm** (the platform's built-in LLM tool loop — **implemented**, driven by Apache Ollama: plan → pick a tool → observe → … → final; the LLM only picks tools, facts come only from tool results, every step lands in `ontogeny_agent_step`) ·
**external-pull** (**default**: a third-party agent runtime drives the session over the session protocol — the external agent plugs in under the plugin identity; the platform only governs) ·
**external-push** (the platform delegates to an engine HTTP endpoint; fields reserved). **POST /agent/sessions/{id}/run** dispatches accordingly.

## The Agent API (/agent, 9 endpoints)

| Endpoint | Method | Description |
|---|---|---|
| `/agent/plugins` | GET | plugin catalog (identity/tools/budget/approvals) |
| `/agent/sessions` | POST/GET | open a session / list them (filter by plugin) |
| `/agent/sessions/{id}` | GET | session detail + step trace |
| `/agent/sessions/{id}/tools/{tool}` | POST | **single-gate** execution: write tools return pending-approval or a result |
| `/agent/sessions/{id}/run` | POST | **engine dispatch**: hand the session to the plugin's declared engine (builtin-llm loops in-process / external-push delegates remotely; external-pull returns instructions) |
| `/agent/sessions/{id}/finish` | POST | finish the session (result archived) |
| `/agent/approvals[/{id}/decision]` | GET/POST | the approval queue and decisions (the decider must hold the same action permission) |

The console's "Agent sessions" page visualizes plugins, session traces and the approval queue. **Agent-eval**: runs evaluations over plugin sessions (tool-selection correctness) to prevent behavioral regressions.

## 5.1 Three doors: the three ways to reach the ontology from outside

External consumers reach the ontology through three channels; **the permission gate is the same policy engine (adjudicating by identity), and the session is not a gate but a safety device for autonomous runs**: a one-off data fetch uses ①②; letting an agent run a complete task autonomously (multi-step, possibly writing, requiring a trace) needs ③ to wrap the run in budgets and approvals.

| Dimension | ① REST API (direct service) | ② MCP Server (the agent tool surface) | ③ Session protocol (governed agent runs) |
|---|---|---|---|
| Entry | `/api/v1/objects\|graph\|actions\|functions\|meta\|audit…` (79 operations, see [Reference 12.4](../usage/12-reference.md)) | `/mcp` (streamable HTTP · JSON/stateless): catalog tools `describe_ontology` · `search_{t}` · `traverse_graph` · `call_{f}` · `act_{a}` + session tools `agent_open_session · agent_get_session · agent_list_sessions · agent_finish_session` (generated from compiled artifacts, rebuilt after promote) | `POST /agent/sessions` opens → `…/tools/{tool}` (single gate) · `…/run` (engine dispatch) · `…/finish` |
| Identity | every call carries a principal (dev mode: the `X-Ontogeny-Principal` header) | with `plugin` → the plugin's delegated identity; default `mcp-agent` shared identity (**zero permissions, role-gated policies always refuse — by design**) | a **frozen** snapshot of the plugin principal taken at session open; later plugin edits never affect running sessions |
| Can read | object query / single read (masked) / relation navigation / aggregation; graph explore / traverse; ontology snapshots & lineage; the audit revision stream | ontology snapshot (`describe_ontology`), per-type search (filter DSL), multi-hop traverse (`traverse_graph`); narrowed by the plugin catalog | ②'s tool surface narrowed by the plugin allowlist; plus session detail + step trace (`GET /agent/sessions/{id}` or MCP `agent_get_session`) |
| Can act | the Action five stages + a free dry-run validate, sandboxed Function calls, admin ops (publish / sync / derive / projection rebuild) | `act_{a}` / `call_{f}`; with `session_id` this is exactly ③'s gate (broker.call_tool) | same as ② but always through **the broker.call_tool single gate**; write tools get a free validate first (rehearsals cost no steps) |
| Permission gate | all three pass **the same policy engine** (agents and humans share the policy plane — no second door); ②③ additionally intersect the tool catalog `catalog ∩ allow − deny` — **narrowing only, never widening** (invariant I1) — shared across the three columns |||
| Write approvals | no approval queue — rules + policy pass → execute, leaving `ontogeny_revision` | sessionful: same as ③ (confirm → approval / never → refuse / auto → allowlist); sessionless: always `WRITE_REQUIRES_SESSION` | per the plugin's `approval.writes`: **confirm** → queue for human approval (refusals refund the quota) · **never** → a read-only plugin is refused outright · **auto** → only `auto_actions` entries run free |
| Budget | none (caller discipline) | sessionful: steps / writes hard gates (overrun returns `AGENT_BUDGET_EXCEEDED`); sessionless: none | **steps / writes hard gates**, overrun returns a structured `AGENT_BUDGET_EXCEEDED` stop (`wall_ms` frozen with the session; since v1.2 enforced per run, reset at start_run) |
| Trace audit | `ontogeny_revision` (the action revision stream) | sessionful: a step-by-step `ontogeny_agent_step` (with `thought`) + `ontogeny_revision`; sessionless: only `ontogeny_revision` | a step-by-step `ontogeny_agent_step` (fully replayable in the UI, also an RSI signal source) + `ontogeny_revision` |
| Concurrency guard | none | sessionful: non-engine calls during running return `AGENT_SESSION_RUNNING` | non-engine calls during running return `AGENT_SESSION_RUNNING` (prevents human & LLM writing the same session concurrently) |
| Suited for | human UI / SDKs / scripts / service integration | MCP clients like Claude / ZCode / LangGraph: zero-code access, open a session to **run a complete task autonomously** (or a sessionless one-off read) | autonomous agent loops **running complete tasks** (multi-step · possibly writing · needing a full trace and a budget backstop) |

## 5.2 The engine paradigm: protocol as contract, engines pluggable (third-party integration)

**A session is a governed execution container; an engine is the executor driving it.** Any engine — third-party or built-in — drives the session through the same tool protocol and is therefore covered by the same governance. Four axioms:
① **engines never touch data directly** (the only capability surface = the tool catalog; no SQL, no bypass);
② **the plugin declares "who executes" (spec.engine); the platform declares "how it is governed"** (principal/tools/approval/budget are orthogonal to the engine);
③ **Run is the universal verb** (`POST /agent/sessions/{id}/run` hands the session to its declared engine);
④ **a complete trace (I4)**: every engine step must land in `ontogeny_agent_step`, fully replayable in the UI; side effects outside the trace are not allowed.

| Integration shape | Where the engine lives | Who drives the loop | Contract highlights |
|---|---|---|---|
| **A · external-pull** | a third-party process (any framework/language) | the third party | calls tools step by step over the session protocol; LangGraph / Claude and other MCP clients are this class; registered via `engine.kind: external-pull` in the plugin |
| **B · external-push** | a third-party HTTP endpoint | the platform | the platform POSTs `{session, task, tools, budget}` to the engine endpoint; the engine calls back over the tool protocol until final. (unimplemented: package validation emits an AGENT-ENGINE-UNIMPLEMENTED warning) |
| **C · builtin-llm** | in the platform process | the platform | the built-in LLM tool loop (the reference implementation): strict JSON, one tool per turn, reusing the `OllamaChat` adapter; the LLM endpoint comes from `ONTOGENY_LLM_BASE_URL` (runtime config; keys never in Git) |

```yaml
# engine declaration (new plugin spec fields)
spec:
  engine:
    kind: builtin-llm   # builtin-llm | external-pull | external-push
    # external-push also needs: endpoint: https://…/drive
  principal: { … }         # orthogonal to the engine
  tools:     { … }
  approval:  { … }
  budget:    { … }
```

```text
# lifecycle state machine (engine-agnostic)
open ──run──▶ running ──┬─▶ finished   (final | error)
                        ├─▶ blocked_on_approval   # a write is pending
                        └─▶ budget_exhausted
blocked ──(approved) run──▶ running   # resume = the human-in-the-loop checkpoint
```

**The engine contract (agent/engines/ · every engine implements the same interface)**:

1. **drive(session, resume)**: drives the session from its current state to a terminal state or a blocking point; may only execute via **broker.call_tool**
2. **the tool-result envelope**: {outcome, detail?, error?, approval_id?, revision_id?, budget} — the engine decides from this and reads no other interface
3. **external-call isolation**: during running, tool calls from non-engine parties return AGENT_SESSION_RUNNING (prevents human & LLM concurrent writes)
4. **the built-in has no privilege**: builtin-llm is merely drive()'s first reference implementation — same contract, same state machine, same gates as any third party
5. **compatibility rules**: the tool catalog is the engine's API surface — additive only; input_schema changes are breaking (go through package versioning); protocol fields are additive-only

**Minimal third-party integration (external-pull, ~15 lines, any HTTP runtime)**:

```python
sess = post(f"{BASE}/agent/sessions", {{"plugin": "my-agent", "task": task}})
while True:
    catalog = get(f"{BASE}/agent/sessions/{sess['id']}")["tools"]
    decision = my_llm_decide(task, catalog, transcript)      # any framework/model
    if "final" in decision:
        post(f"{BASE}/agent/sessions/{sess['id']}/finish", decision); break
    out = post(f"{BASE}/agent/sessions/{sess['id']}/tools/{decision['tool']}", decision["args"])
    if out["outcome"] in ("AGENT_BUDGET_EXCEEDED", "AGENT_SESSION_CLOSED"): break
```
