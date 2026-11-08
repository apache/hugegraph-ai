# 00 · Kind Taxonomy

> Part of [Part I · Architecture](../README.md#part-i--architecture) · Sources: `core/kinds.py` · the `kinds` field of `GET /meta/ontology`

**English** | [中文](../../zh/architecture/00-kind-taxonomy.md)

This page is the **single authority for how many kinds exist and how they are grouped**. Every other doc, the console's architecture board and `GET /meta/ontology` quote this table; if they disagree, this page and `core/kinds.py` win.

## The one-line answer

**11 DSL resources = 9 platform resources + 2 manifest resources.**

- A **platform resource** is a platform building block: compiled into the runtime, validated by its own block, and owning its own lifecycle and review responsibility.
- A **manifest resource** travels with the package (`Store`, `Ontology`) but is **not** a building block — so it is not a platform resource.

## The nine platform resources

| Group | kind | Layer | Change rate | Reviewer | What merging it away would lose |
|---|---|---|---|---|---|
| **Core** | `ObjectType` | semantic | high | data / domain | where business nouns are declared |
| **Core** | `LinkType` | semantic | high | data / domain | relations and multi-hop traversal |
| **Core** | `Action` | kinetic | medium | process / domain | **the only write gate** — audit and policy lose their single anchor |
| **Core** | `PolicySet` | governance | low | security | default-deny and row-level authorization |
| **Extension** | `Function` | kinetic | medium | platform | read-only compute and the "computes but never writes" sandbox boundary |
| **Extension** | `AgentPlugin` | agent | medium | AI governance | agents would run as the caller → implicit privilege escalation |
| **Extension** | `EvalSuite` | evolution | medium | eval / domain | promotion loses its deterministic selection function |
| **Adapter** | `Projection` | derived | low | graph / platform | only the publish-time "markings never enter the graph" check; the graph is an optional accelerator anyway |
| **Baseline** | `EvolutionPolicy` | evolution | very low, human-only | architecture council | the physical landing point of the RSI T3 protection |

> Governance spine: `Action` (the only write gate), `EvalSuite` (the selection box), and `EvolutionPolicy` (the `HUMAN` badge — human-only).

## The two manifest resources (not platform resources)

| kind | Layer | Responsibility | Why it is not a platform resource |
|---|---|---|---|
| `Store` | data plane | storage binding: `type` · `connection: ${DSN}` · `access` | it says *where data lives*, not what the model means or who may write |
| `Ontology` | manifest | package manifest: name / display / version / imports | package metadata; it is not compiled into the runtime snapshot |

## Why nine — not four, not fifteen

Three tests, all required:

1. **Orthogonality** — the concept cannot be expressed by another kind. `Function` cannot fold into `Action` (it must read, compute, and **never write**); `EvolutionPolicy` cannot fold into `EvalSuite` (the exam and the exam rules have different lifecycles, reviewers and blast radii).
2. **Independent lifecycle** — change rate, reviewer and rollback differ. Putting "the Object that changes weekly" and "the governance baseline that never changes" in one file merges the sign-off authority with it.
3. **Governance mapping** — it is a decision surface that a human must sign. RSI's T0–T3 classification depends on *which kind/field* changed; blur the kind boundary and the tier cannot be derived automatically.

The count itself is **not** the criterion. Kubernetes ships 70+ built-in kinds and works, because it layers them (core / CRD) and provides defaults; dbt has six node types because each has different execution semantics. The real anti-pattern is one universal config that holds every meaning — the validator cannot check it statically, audit cannot attribute a change, and RSI cannot tier it.

## Admission rules (a new kind must answer)

1. Why can the existing kinds plus extension fields not express this?
2. Who reviews it, at what cadence, with what blast radius?
3. Does it need its own validation block, compiled artifact or runtime path?
4. Which group — `core` / `extension` / `adapter` / `baseline` — and why?
5. If the answers do not hold, use an **extension namespace**, not the core.

The change surface for adding a kind should be exactly: `core/kinds.py` + the frozen test table + this page. Needing five edits means the abstraction has not converged.

## The minimal viable package

The taxonomy has a surface of 11 and an **entry threshold of 2**:

```yaml
# ontology.yaml + stores/main.yaml + objects/product.yaml
# 1 Store + 1 ObjectType = a loadable, validatable, queryable ontology
```

`Action` / `PolicySet` / `Function` / `AgentPlugin` / `Projection` / `EvalSuite` / `EvolutionPolicy` may all be absent. Nobody needs nine platform resources to model their first object.

## Code and contract

| Location | Role |
|---|---|
| [`core/kinds.py`](../../../server/ontogeny/core/kinds.py) | `KINDS` / `BY_KIND` / `DIR_KINDS` / `PLATFORM_KINDS` — the only registry |
| [`core/models.py`](../../../server/ontogeny/core/models.py) | the eleven Pydantic models; import-time assertion that registry and models agree |
| `GET /meta/ontology` → `kinds` | the published table (`kind` / `group` / `layer` / `core` / `platform`) |
| [`ArchBoard.tsx`](../../../web/src/pages/dashboard/ArchBoard.tsx) | the board renders chips from `kinds`; it owns drawing, not the list |
| [`tests/test_kind_registry.py`](../../../tests/test_kind_registry.py) | freezes `(kind, group)`; adding or removing a kind is an explicit edit |
