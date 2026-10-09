# 02 · Ontology Model & DSL（core/models.py · core/loader.py · core/validator.py）

> Part of [Part I · Architecture](../README.md#part-i--architecture)

**[中文](../../architecture/02-ontology-model-and-dsl.md)** | English

**11 resources**, all `apiVersion: ontogeny/v1` YAML — the directory is the package, Git is the source of truth; `${VAR}` references are injected at runtime, no secrets inside the package. The semantic layer (objects · links) pairs with the kinetic layer (actions · functions · policies), plus the derived layer (projections), the agent layer (plugins) and the evolution layer (eval suite / constitution).

## The 11 resources

| kind | Layer | Responsibility & key fields |
|---|---|---|
| `Store` | data plane | storage binding: `type` (postgres/sqlite/duckdb/csv/parquet/iceberg) · `connection: ${DSN}` · `access` (read-write is the precondition for actions writing back) |
| `ObjectType` | semantic | nouns: `primaryKey` · `properties` (type/required/**owner**/marking/**derived**) · `backing` (store + mode + source + mapping + **sync**) |
| `LinkType` | semantic | relations: `cardinality` (1:1 / 1:N / M:N) · join (**foreign-key** or **join-table**) |
| `Action` | kinetic | verbs: five stages (parameters → rules → policy → effects → audit); declarative or `execution: function` |
| `Function` | kinetic | logic: `runtime` (python/ts) · `entry` · `capabilities` (read-objects / llm) · `publish` (version-anchored) |
| `PolicySet` | governance | Cedar policy files (`source: *.cedar`); falls back to the package default policy when not declared |
| `Projection` | derived | graph projection: `include` (allowlisted properties + links, **markings never enter**) · deletion · indexes · `endpoint` |
| `AgentPlugin` | agent | agent as a resource: `principal` (frozen identity = permission surface) · `tools.allow` · `approval.writes` · `budget` (steps/wall_ms/writes) |
| `EvalSuite` | evolution | selection functions: queries (shape/latency/rows) + replays (action replay) + coverage (quarantine rate) — **all deterministically evaluable** |
| `EvolutionPolicy` | evolution | the constitution file: loop · observability · tiers T0–T3 (mutations + budget) · graduation — **human-editable only** |
| `Ontology` | manifest | package manifest: name/display/version/imports (package dependencies, the basis of a template market) |

## Example: the two kinds of derivation

```yaml
# Expression derivation (computed on read, no column)
qty_completed: { type: integer, owner: ontology }
qty_planned:   { type: integer, required: true }
completion_rate:
  type: "decimal(6,2)"
  derived: "(qty_completed / qty_planned) * 100"
```

```yaml
# Function derivation (cross-object, materialized into a column)
open_mo_count:
  type: integer
  display: 未关闭维修单数
  derived:
    kind: function
    entry: maintenance_state.py:open_mo_count
    object_param: obj
    triggers: [maintenance-order]   # cross-object trigger
```

**The dividing line**: expression derivations use only fields of the same row and compute on read; function derivations may `ontogeny.query` other objects or even call the LLM, so the derivation worker **materializes them into columns** (batch recompute after writes, eventually consistent).

## The expression language mini-expr (shared by rules / derivations / effects / assertions)

A hand-written Pratt parser (lexing → AST → tree evaluation, **eval() banned**), not Turing-complete; parse caching + static analysis (`analyze()` collects references for the validator to check).

| Category | Support |
|---|---|
| Operators | arithmetic · comparison · logic `and or not` · `in` · `has` · `??` null-coalescing |
| Roots | `target.*` · `parameters.*` · `principal`; derivation expressions allow **bare field-name sugar** |
| Functions | `now()` (injected clock, replayable) · `user()` · `newId('prefix')` (engine serials) |
| Time semantics | ts − ts → milliseconds; naive/aware mixing normalizes to UTC (a timezone bug that blanked derivations was fixed) |
| Literals | bare identifiers in effect values = enum literals (`status: CLOSED`) |

## Validators & lint (the publish gates)

**validate (blocks publishing, 20+ check codes)**: referential integrity · join key types · primary-key sanity · **actions writing source-owned properties = error** (ownership) · derivations banned from mapping · **markings banned from projections** · expression static analysis · function-derivation entry shape · EvalSuite references · constitution markings.

**lint (team conventions, exemptable)**: display/description required · kebab-case · derivation chain ≤2 · webhook actions must narrow audit.fields — conventions don't block publishing but do leave a trace.
