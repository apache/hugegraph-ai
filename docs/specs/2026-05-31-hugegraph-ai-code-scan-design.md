# HugeGraph AI Code Logic Scan Design

Date: 2026-05-31
Target repo: `apache/hugegraph-ai`
Target modules: `hugegraph-llm`, `hugegraph-python-client`
Execution plan: `docs/plans/2026-05-31-hugegraph-ai-code-scan.md`

## Executive Summary

This scan is a read-first code audit for the two core modules. It is not a refactor campaign and not a test-quality implementation pass.

The goal is to inspect all production and test code in `hugegraph-llm` and `hugegraph-python-client`, record logic/design/maintainability/performance risks by layer, and produce a prioritized issue ledger from P0 to P5. Behavior-changing fixes are explicitly out of scope during the scan: they must be recorded with evidence and left for a later fix plan. Only non-behavioral style, typo, or comment issues may be fixed in place.

The scan uses high parallelism because the two modules have separable risk surfaces:

- `hugegraph-python-client` owns HTTP routing, auth, response envelopes, schema/graph/gremlin APIs, and data structure adapters.
- `hugegraph-llm` owns API contracts, runtime config, GraphRAG/KG/Text2Gremlin flows, nodes/operators, LLM/vector provider wrappers, and UI/demo glue.
- Cross-module compatibility is audited as its own lane: `hugegraph-llm` callers must remain consistent with the client contract.

## Non-negotiable Invariants

1. Do not change logic or design behavior while scanning. Record the issue, affected paths, evidence, impact, and recommended fix direction.
2. Style-only, typo-only, stale-comment-only, and formatting-local fixes may be edited in place if they cannot change runtime behavior.
3. If a core function lacks effective tests, or tests mock away the behavior under review, add a nearby `FIXME:` comment in the relevant test or production-adjacent test location.
4. Do not expand scope into `hugegraph-ml`, `vermeer-python-client`, generated artifacts, caches, logs, build outputs, or unrelated workflows.
5. Do not mix scan findings with the existing quality-program implementation ledger. Use `.workflow/code-scan/` only as optional local scratch during execution; keep durable review artifacts under `docs/`.
6. Every issue must have enough evidence for a maintainer to reproduce the reasoning without trusting the reviewer.
7. Commit after a completed setup slice and after each coherent large scan slice.

## Priority Model

| Priority | Meaning | Examples |
|---|---|---|
| P0 | Confirmed correctness, data loss, security, or crash risk on common/default paths. | Wrong REST route, auth leak, destructive graph mutation without guard, unavoidable runtime exception. |
| P1 | High-confidence logic/design flaw that can return wrong results, hide failures, or break a core workflow. | Swallowed HugeGraph/LLM errors, schema mismatch, bad Text2Gremlin extraction, non-deterministic graph import semantics. |
| P2 | Important maintainability or contract issue likely to cause regressions or integration pain. | Duplicated boundary logic, unclear API response contract, weak error mapping, hard-coded config that bypasses central config. |
| P3 | Performance, scalability, resilience, or edge-case risk with plausible production impact. | Unbounded memory use, repeated network calls, O(n^2) path over user data, missing timeout/retry boundary. |
| P4 | Test-quality gap, missing meaningful coverage, weak assertions, ineffective mocks, or fragile test setup. | Test only asserts a mock call, no regression test for parser boundary, silent external-service skip. |
| P5 | Minor style, naming, comment, documentation, or small elegance issue. | Typo, misleading comment, local readability cleanup. |

Priority is impact-first. A test gap can be P1/P2 if it hides a known high-risk path, but ordinary missing coverage is P4.

## Scan Boundaries

### In Scope

```text
hugegraph-python-client/src/pyhugegraph/
hugegraph-python-client/src/tests/
hugegraph-llm/src/hugegraph_llm/
hugegraph-llm/src/tests/
hugegraph-llm/pyproject.toml
hugegraph-python-client/pyproject.toml
root pyproject/workflows only when they affect these two modules
```

### Out of Scope

```text
hugegraph-ml/
vermeer-python-client/
dist/, egg-info, .venv, .pytest_cache, .ruff_cache, logs, generated coverage artifacts
demo visual redesign, dependency upgrade campaigns, broad formatting rewrites
```

## Layered Audit Map

```text
┌─────────────────────────────────────────────────────────────────┐
│ Cross-module Contract Lane                                       │
│ hugegraph-llm callers  ⇄  pyhugegraph client API/response shapes │
└─────────────────────────────────────────────────────────────────┘
       ▲                                           ▲
       │                                           │
┌──────┴─────────────────────────┐       ┌─────────┴────────────────────┐
│ hugegraph-python-client         │       │ hugegraph-llm                 │
│ A. transport/auth/routing       │       │ A. API/models/config          │
│ B. graph/schema/gremlin APIs    │       │ B. flows/scheduler/state      │
│ C. data structures/responses    │       │ C. nodes/operators            │
│ D. tests/fixtures               │       │ D. indices/models/providers   │
│                                 │       │ E. demo glue/tests            │
└─────────────────────────────────┘       └──────────────────────────────┘
```

## Parallel Review Lanes

| Lane | Owner Focus | Primary Paths | Output |
|---|---|---|---|
| L1 | Client transport, auth, routing, request safety | `pyhugegraph/client.py`, `utils/`, `api/auth.py`, `api/common.py` | client transport issues |
| L2 | Client graph/schema/gremlin APIs and structure adapters | `pyhugegraph/api/`, `pyhugegraph/structure/` | client API/contract issues |
| L3 | LLM API, models, config, prompt contract | `hugegraph_llm/api/`, `config/`, `resources/`, tests | public contract issues |
| L4 | LLM graph boundary, flows, nodes, operators | `flows/`, `nodes/hugegraph_node/`, `operators/hugegraph_op/`, `operators/llm_op/` | core workflow issues |
| L5 | LLM indices, model wrappers, performance/resilience | `indices/`, `models/`, `utils/` | provider/vector/perf issues |
| L6 | Test effectiveness and fake/mock quality | both `src/tests/` trees | P4 ledger plus `FIXME:` edits |
| L7 | Cross-module compatibility synthesis | LLM callers plus client response contracts | deduplicated final priorities |

Execution notes, checkpoints, and intermediate ledgers may be written under `.workflow/code-scan/` while scanning, but they are intentionally optional local scratch artifacts and should not be retained in the final PR.

The coordinator owns scope, durable documents, final synthesis, and verification for every edit or commit.

## Issue Record Schema

Each issue in the local scratch ledger must use this shape:

```markdown
### CS-000: Short title

- Priority: P0-P5
- Module: `hugegraph-llm` | `hugegraph-python-client` | cross-module
- Layer: API | config | flow | node | operator | client-api | transport | structure | test-quality | performance
- Paths: `path.py:line`, `path_test.py:line`
- Status: open | fixed-style-only | deferred | duplicate
- Evidence: concrete code behavior and why it matters
- Impact: user-visible or maintainer-visible consequence
- Recommendation: fix direction without implementing behavior changes
- Test note: existing coverage status or missing effective coverage
```

## FIXME Marking Rule

Add `FIXME:` comments only for meaningful test-quality gaps around core behavior. The comment must name the missing behavior, not just say "add tests".

Good:

```python
# FIXME: add a contract test that exercises malformed Gremlin responses from
# pyhugegraph instead of only asserting the mocked client method is called.
```

Bad:

```python
# FIXME: add more tests
```

## Optional Local Checkpoint Ledger

The scan may write these restartable scratch artifacts:

```text
.workflow/code-scan/
  README.md
  code-scan-state.json
  checkpoints/
    00-setup.md
    01-client-transport.md
    02-client-api-structure.md
    03-llm-api-config.md
    04-llm-flow-operator.md
    05-llm-index-model.md
    06-test-quality.md
    07-synthesis.md
  reports/
    issues.md
    module-map.md
    test-quality-ledger.md
    final-code-scan-report.md
```

These files are execution-local and should be ignored or removed from version control before the final PR.

## Definition of Done

1. Every relevant checklist item in `docs/plans/2026-05-31-hugegraph-ai-code-scan.md` is checked for the scan run.
2. All seven scan lanes have checkpoint notes in local scratch, a PR summary, or a durable follow-up document.
3. The issue ledger contains prioritized P0-P5 findings with evidence and deduplication.
4. Required `FIXME:` comments for ineffective/missing core tests are present.
5. Style-only fixes, if any, are verified with formatting/lint checks or narrower syntax checks.
6. The final report or PR summary covers issue distribution, highest-risk fixes to schedule next, and verification commands run.
