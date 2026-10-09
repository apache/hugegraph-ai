# 04 · Kinetic Layer: Actions & Functions（KINETIC · action/ · functions/ · policy/）

> Part of [Part I · Architecture](../README.md#part-i--architecture)

**[中文](../../architecture/04-actions-and-functions.md)** | English

**Actions change the world, functions compute answers** — Palantir's Ontology also makes these first-class citizens of the kinetic layer; Ontogeny inherits that faithfully and completes the function ecosystem to four capabilities (LLM access · derivation substrate · published APIs · streaming in design).

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
