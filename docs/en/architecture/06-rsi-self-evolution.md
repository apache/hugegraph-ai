# 06 · RSI Self-Evolution: Recursion Inside Governance（evolve/ · telemetry/ · EvalSuite · EvolutionPolicy）

> Part of [Part I · Architecture](../README.md#part-i--architecture)

**[中文](../../architecture/06-rsi-self-evolution.md)** | English

What recurses is the **model layer** (ontology + action); the platform constitution is never touched by the loop. Mutation is outsourced to the LLM, **selection never is** — the dividing line from unbounded RSI.
There is no mysticism in the loop: every beat is deterministic code plus a persisted artifact. **Signals** come from rule-based scanners over telemetry (`ontogeny_evolve_signal`); **mutations** come only from the whitelist (`ontogeny_evolve_proposal`, rationale mandatory); **evaluation** is entirely deterministically evaluable (no LLM-judge); **promotion** runs the T0–T3 tiers against an ISO-week budget (`ontogeny_evolve_budget`). Every beat's products are database rows and a Git diff — auditable, replayable, revertible.

## The RSI loop · six beats (each persisted, each independently replayable)

1. **Signal aggregation**: `ontogeny evolve signals` (= `POST /evolve/aggregate`) — detectors scan a 168h window: empty-result rate, unmapped filter fields, hot queries, slow queries P95, action-rule rejection rate, agent tool errors, approval rejection rate, quarantine bad rows → `ontogeny_evolve_signal` (all 8 detectors in the panorama below)
2. **Attribution**: `POST /evolve/diagnose` — diagnoser.py translates signals into gap hypotheses (with evidence counts, marking-aware); informational signals are only presented to humans/the LLM, **never mutated on automatically**
3. **Proposal**: the heuristic proposer (zero LLM, the default path) or the LLM proposer (Ollama structured `{mutations, rationale}`) → `ontogeny_evolve_proposal`; **parse failures or missing rationale are dropped at the entrance**
4. **Evaluation**: `POST /evolve/proposals/{id}/eval` — EvalRunner runs all EvalSuites on a **candidate-package copy** (production untouched); the report and the pass flag are written back to the proposal row
5. **Tiered promotion**: `ontogeny evolve promote {id}` — the promoter reads the tier from EvolutionPolicy → checks the weekly budget → checks the constitution → T0 applies & publishes / T1·T2 open a review branch / T3 → `awaiting_human`
6. **Activation & rollback**: promotion = `registry.publish` + `reload()` hot-swapping the compiled snapshot (new schema live immediately); rollback = `git checkout` the previous package dir and publish — **the file system is the version, Git is the undo key**

## The three stages in view

### ①② Observe → attribute（telemetry/ · diagnoser.py）

| | |
|---|---|
| Signals | 8 detectors (panorama below): empty-query rate · **unmapped filter fields** · hot queries · slow queries P95 · action-rule rejection rate · agent tool errors · approval rejection rate · quarantine bad rows |
| Thresholds | per detector: empty rate ≥10% · unmapped field ≥5 times · hot ≥3 times · P95 ≥2s · rule rejections ≥30%·5 samples · agent errors ≥3 times · approval rejections ≥30%·5 samples (all over a 168h window, noise-proof) |
| Attribution | deterministic detectors → gap hypotheses (with evidence counts); **marking-aware**: signals on masked fields never leave the ontology as inferences |

### ③ Mutate → DSL diff（proposer.py）

| | |
|---|---|
| Heuristic | deterministic: gap type → mutation (add-optional-property / enum-widen); the whole loop runs with zero LLM |
| LLM | Ollama structured output `{mutations, rationale}`; the prompt allows only two mutation shapes; **parse failures or missing rationale are always dropped** — an unexplained proposal never reaches evaluation |

### ④ Deterministic evaluation（evalrunner.py · EvalSuite）

| | |
|---|---|
| L1 | validate / lint (structure + constitutional red lines, inside the promoter) |
| **L2** | query regression (**columns checked against the declared schema**; empty results are not red) + **action time-travel replay**: historical revisions re-executed counterfactually under the new rules, compared with real human decisions |
| L3/L4 | shadow double-run · the LLM only explains and classifies, **never gates** — the LLM is not reproducible, so the script is the test subject |

## Signal panorama · the 8 detectors (as implemented in telemetry/service.py)

| Signal (kind) | Threshold (168h window) | Plain words · what it says | Channel |
|---|---|---|---|
| `empty_query_rate` | ≥10% | ≥10% of queries on a type return 0 rows — "everyone keeps querying it and finds nothing". Data may not be synced, or the model mismatches reality. | informational (display only) |
| `unmapped_filter_field` | same field ≥5 times | **the strongest evolution signal**: the filter field exists in the source database but is not modeled (a schema gap) — directly generates an "add optional property" proposal. | **auto proposal** (T0 whitelist) |
| `hot_query` | identical filters ≥3 times | the same query runs repeatedly **with results** — high-frequency real usage. A different direction: not "what broke" but **freezing key queries into eval cases** (eval-case-synth), so regression exams track real usage. | eval asset (case synthesis) |
| `slow_query_p95` | P95 ≥2000ms | a type's P95 latency over 2 seconds — "slower every time". Hints at indexes, materialized columns or projection acceleration; a performance signal, the model is not changed. | informational (display only) |
| `action_rule_reject` | ≥30% and ≥5 samples | an action keeps getting stopped by its business rules — "people keep trying, the rules keep saying no". Rules out of touch with reality: too strict, or the process should change. **Rules are human intent and are never auto-changed.** | informational (display only) |
| `quarantine_rate` | recorded on occurrence | values the source sends that the ontology doesn't know — most typically **enum widening**. The source adds "URGENT" absent from the enum → the row is quarantined (TYPE_MISMATCH, batch not blocked). If the value looks like a legal enum member → an "enum-widen" proposal is generated. | **auto proposal** (T0 whitelist) |
| `agent_tool_error` | same tool ≥3 times | an agent keeps calling a tool that keeps failing — the tool or its input contract is broken. | informational (display only) |
| `approval_reject_rate` | ≥30% and ≥5 samples | **a governance-surface signal**: humans keep refusing an agent plugin's write approvals — "the AI keeps asking, the human keeps saying no". Either the plugin's permissions are too wide or it should take another action. **Presented to humans only; policy is never auto-changed.** | informational (display only) |

Three design invariants: ① **thresholds are tunable** — every trigger line can be overridden by the domain's EvolutionPolicy.observability (different domains, different sensitivities); ② **de-duplicated** — identical (kind + evidence fingerprint) within a window records once, rolling windows don't spam; ③ **informational ≠ evolvable** — many errors don't mean the model should change; only **structural gaps** (missing fields, bad rows) enter the auto-proposal channel, the rest are presented to humans.

## T0–T3 tiered promotion（EvolutionPolicy · evolution.yaml，human-editable only）

| Tier | Whitelisted mutations | Gate | Action |
|---|---|---|---|
| **T0 auto-merge** | `add-optional-property` · `enum-widen` · `index-tune` | eval all green + weekly budget (example package **8/week**, per namespace) | validate → apply → publish → **hot swap**, fully unattended |
| **T1 human PR** | everything safe outside the whitelist | validate | the machine lands a validated branch dir `pkg.proposal-{id}` (mutations without a mechanical applier are edited by a human in the branch); a human merges & publishes |
| **T2 canary** | `rule-change` · `effect-change` · `function-change` | eval green + clean shadow diff + **explicit approval** | same branch flow as T1; after going live a shadow double-run compares, traffic switches only without regressions |
| **T3 human-only** | `policy-loosen` · `marking-change` · `ownership-change` · `eval-passbar-change` · `destructive-migration` | a machine proposal touching these raises `ConstitutionViolationError` | the proposal goes to `awaiting_human` with the reason audited — **the automated path does not exist**, it is not merely blocked |

**Graduation (tier upgrades)**: ten consecutive clean promotions of the same mutation class + human approval to move T1→T0 — and the upgrade itself is a T3 operation. The T0 budget is a database row per ISO week; overrun raises `BudgetExceededError`: **better to let the loop pause a beat than let it run a little faster.**

## A worked example: one field from "the dashboard is red" to "modeled automatically"

Scenario: a shop-floor analytics dashboard keeps filtering purchase orders by `cost_center`. The column really exists in the source table `mes.purchase_orders` but was missed during modeling — the query API throws `NotFoundError` for unmapped filter fields, and the dashboard stays red. Nobody files a ticket; the loop finds it itself.

```json
// Beat 1 · signal — detector #2 of ontogeny evolve signals (fires at ≥5)
{"id": 17, "kind": "unmapped_filter_field",
 "evidence": {"object_type": "purchase-order", "field": "cost_center", "count": 23}}   // → ontogeny_evolve_signal
```

```json
// Beats 2–3 · attribute + propose — POST /evolve/diagnose (heuristic proposer, zero LLM)
{"id": 42, "gap_kind": "add-optional-property", "origin": "heuristic", "status": "proposed",
 "diff": [{"mutation": "add-optional-property", "object": "purchase-order",
           "prop": "cost_center", "type": "string", "column": "cost_center"}],
 "rationale": "filter field 'cost_center' used 23x on 'purchase-order' but is not modeled; add as optional property"}
// the rationale carries the evidence count; without it the proposal is dropped
```

```json
// Beat 4 · evaluate — POST /evolve/proposals/42/eval (on a candidate-package copy; production untouched)
{"passed": true, "suites": {"production-flow-suite": {"passed": true, "cases": [
    {"name": "open-sales-orders", "kind": "query", "ok": true, "latency_ms": 2.4, "rows": 17},
    {"name": "released-production-orders", "kind": "query", "ok": true, "latency_ms": 3.1, "rows": 8},
    {"kind": "replay", "action": "report-operation", "ok": true,
     "replays": 214, "outcome_matches": 214},                 // additive semantics; no no-double-close
    {"kind": "replay", "action": "close-maintenance-order", "ok": true,
     "replays": 57, "outcome_matches": 57, "after_state_rejections": 57}]},   // 57 "close an already-closed" all refused by the candidate rule
  "quality-suite": {"passed": true, "cases": "… 3 cases green …"}}}
// query regression compares column names against the DECLARED schema: cost_center is now a legal filter; empty results are not red (no hits is a legal business state)
// replay = time travel: 90 days of revisions re-executed counterfactually under the candidate rules — the new package rewrote neither history nor safety semantics
```

```json
// Beats 5–6 · promote + activate — ontogeny evolve promote 42
{"status": "promoted", "tier": "t0-auto-merge",
 "budget_used": 4, "budget_cap": 8,                      // the week's 4th T0; at cap → BudgetExceededError
 "content_hash": "b7f3c9…", "revert": "ontogeny publish pkg  # republish the previous git version"}
```

```diff
// the only diff the loop writes — purchase-order.yaml (auditable at a glance in git diff)
   properties:
     created_at:
       type: timestamp
       display: 创建时间
+      cost_center:
+        type: string
+        display: cost_center
+        required: false
   backing:
+    mapping:
+      cost_center: cost_center   # points at the same-named column in mes.purchase_orders
// after publish + reload() hot swap, the dashboard's next query hits — signal to effect, no human in the loop
```

**The governance boundary is equally concrete in the same example**: had the LLM proposer used the same signal to also propose "loosening the amount-cap rule of `approve-purchase-order`" (`rule-change` ∉ the T0 whitelist), the classifier assigns T2 — a review branch + shadow double-run, never auto-activated for convenience; a proposal touching the T3 surface (say, loosening Cedar) makes the promoter throw `ConstitutionViolationError` on the spot, and the proposal goes to `awaiting_human`. A homologous path: a new enum value from the source ERP (say `status=CLOSED`) is first quarantined by sync (TYPE_MISMATCH, batch unblocked), then the `quarantine_rate` signal → an `enum-widen` proposal → the same T0 promotion — exactly the join between "bad rows quarantine without blocking (bad-row rate = an RSI signal)" and the loop.

## The constitution (the surface the loop may never touch; machine proposals touching it drop to T3)

① the engine and evaluator themselves ② EvalSuite pass bars (cannot self-lower) ③ the Cedar loosening direction ④ markings & property ownership ⑤ tier definitions & budgets ⑥ the audit itself.
**Tier graduation**: ten consecutive clean promotions of a class + human approval for T1→T0 — and the upgrade itself is T3.
