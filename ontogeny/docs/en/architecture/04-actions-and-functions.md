# 04 · Kinetic Layer: Actions & Functions（KINETIC · action/ · functions/ · policy/）

> Part of [Part I · Architecture](../README.md#part-i--architecture)

**[中文](../../zh/architecture/04-actions-and-functions.md)** | English

**Actions change the world, functions compute answers** — both are first-class citizens of the kinetic layer, and the function ecosystem covers four capabilities (LLM access · derivation substrate · published APIs · streaming in design).

## 4.1 The four capabilities of the function ecosystem

### llm · call the model inside a function (budget-capped · zero network from the subprocess)

| | |
|---|---|
| Declare | `capabilities: [{llm: {model, max-calls}}]` |
| Call | `ontogeny.llm(prompt, system=…)` → stdio RPC → the platform gateway (provider swappable) |
| Guards | undeclared → refused at the boundary; over budget → `SandboxError`; unconfigured → points at ONTOGENY_LLM_BASE_URL |

### derived · the derivation substrate (materialized · cross-object · triggers)

| | |
|---|---|
| Declare | property `derived: {kind: function, entry, object_param, triggers}` |
| Execute | derivation worker consumes the outbox → one subprocess for the batch → one transaction writes the column |
| Example | `equipment.open_mo_count` counts open maintenance orders across objects |

### publish · publish a Function API (version-anchored · drift = 409)

| | |
|---|---|
| Declare | `publish: {enabled: true}` |
| Version | first 12 hex chars of the function source's sha256; `GET /functions/{n}/versions` |
| Anchor | invoke with `version`: mismatch → 409 (perceive logic drift instead of silent change) |

### stream · streaming calls (in design)

| | |
|---|---|
| Shape | functions declaring the llm capability expose SSE token-by-token output |
| Boundary | streaming data pipelines are out of platform scope |

**Sandbox boundary (shared by all capabilities)**: an isolated subprocess + rlimits + wall-clock kill + PYTHONDONTWRITEBYTECODE; cross-boundary RPC is adjudicated by the parent process against the declared capabilities; returned objects are API-shaped (**fixed: derived properties used to be invisible inside the sandbox, driving inventory computations to zero**).

For declarative HTTP step URLs and header values, only bare `UPPER_SNAKE` deployment references such as `${API_BASE}` are resolved from the environment. Lowercase parameters (`${order_id}`) and prior-step references (`${lookup.order_id}`) remain templates, even if similarly named environment variables exist. Deployment references resolve first, then call templates; the final URL must pass the HTTP allowlist, and parameter or step-result values cannot inject another `${...}` reference into either URL or headers.

HTTP responses are streamed with a 256 KiB limit on decoded body bytes. Exceeding the limit closes the response and fails the function; the runtime does not download the complete oversized body or return a truncated result.

Python sandbox output JSON frames, including batch results, are bounded at 256 KiB including framing; oversized output raises `SandboxError` and the child is cleaned up. This supports normal results above asyncio's default 64 KiB line limit. Large inputs and query replies can still be processed into small results. SDK query sorting is applied before its limit.

## 4.2 Functional actions: effect plans (the Function proposes, the Action disposes)

```yaml
# actions/raise-maintenance-order.yaml (excerpt)
spec:
  target: maintenance-order
  execution: { kind: function, entry: maintenance_plan.py:plan_maintenance_order }
  rules: [ { expr: "parameters.symptom != ''", message: 故障现象必填 } ]
  policy: maintenance-policies
# The function looks up the plant from the equipment record inside the sandbox
# (an authorization attribute must never come from the client) and returns an effect plan:
```

```json
[{ "kind": "create-object", "properties": {
     "mo_id": {"$expr": "newId('MO')"},       // $expr = engine-evaluated
     "equipment_id": "EQ-01",                  // everything else = data
     "site": "north", "status": "OPEN",
     "opened_at": {"$expr": "now()"} }}]
// The engine executes atomically within the same transaction — transaction/audit/policy always stay with the engine.
```

**Why expressions and data are distinguished**: values in declarative effects are expressions (statically checkable), while function plans carry runtime data — without the distinction `"EQ-01"` would be parsed as `EQ - 01`.

Before applying a function plan, the runtime runs the same semantic checks as static effects (including property ownership and link references), handles join-table links from either endpoint, and emits an outbox change event for every created object.

Action idempotency keys are scoped to `(action, principal, key)`; an empty key means unset. PostgreSQL serializes same-scope requests before replay lookup. Upgrade replaces the former global unique index without deleting audit revisions.
