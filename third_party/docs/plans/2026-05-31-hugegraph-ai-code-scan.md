# HugeGraph AI Code Logic Scan Plan

> **For reviewers:** split independent scan areas into parallel review lanes when possible. Steps use checkbox (`- [ ]`) syntax for tracking. Behavior-changing edits are forbidden during this plan; record those as findings instead.

**Goal:** Scan all code in `hugegraph-llm` and `hugegraph-python-client` for logic, design, maintainability, performance, and test-effectiveness problems, then produce a prioritized P0-P5 report.

**Architecture:** Use an optional restartable local `.workflow/code-scan/` scratch ledger while scanning, dispatch independent reviewer lanes, synthesize overlapping findings, add `FIXME:` comments only for ineffective core test coverage, and keep only durable docs/source fixes in the final PR.

**Tech Stack:** Python, uv workspace, pytest, ruff, pyhugegraph, hugegraph-llm, FastAPI, vector stores, LLM provider wrappers.

---

## Source Spec

Implement from:

- `docs/specs/2026-05-31-hugegraph-ai-code-scan-design.md`

Reference only for style and boundary management:

- `docs/specs/2026-05-31-hugegraph-ai-quality-program-design.md`
- `docs/plans/2026-05-31-hugegraph-ai-quality-program.md`
- `AGENTS.md`
- `hugegraph-llm/AGENTS.md`
- `rules/README.md`

## File Structure

Tracked scan artifacts:

```text
docs/specs/2026-05-31-hugegraph-ai-code-scan-design.md
docs/plans/2026-05-31-hugegraph-ai-code-scan.md
```

Optional local scratch artifacts used during execution; do not keep these in the final PR:

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

Allowed source/test edits:

- Style, typo, or comment corrections that cannot affect execution.
- `FIXME:` comments marking ineffective or missing core test coverage.

## Global Execution Rules

- [ ] Do not edit behavior-changing production logic.
- [ ] Record every logic/design/performance issue in the local scratch ledger or a durable follow-up document.
- [ ] Update local scratch state after each coherent scan slice if a scratch ledger is used.
- [ ] Update the matching checkpoint after each lane if a scratch ledger is used.
- [ ] Add `FIXME:` comments for missing/ineffective core tests where required by the spec.
- [ ] Commit after setup and after each coherent large sub-slice.

## T0: Setup and Scan Ledger

**Files:**
- Optional local scratch: `.workflow/code-scan/README.md`
- Optional local scratch: `.workflow/code-scan/code-scan-state.json`
- Optional local scratch: `.workflow/code-scan/checkpoints/00-setup.md`
- Optional local scratch: `.workflow/code-scan/reports/issues.md`
- Optional local scratch: `.workflow/code-scan/reports/module-map.md`
- Optional local scratch: `.workflow/code-scan/reports/test-quality-ledger.md`

- [ ] **Step T0.1: Read mandatory guidance**

Commands:

```bash
sed -n '1,240p' AGENTS.md
sed -n '1,240p' hugegraph-llm/AGENTS.md
sed -n '1,260p' rules/README.md
```

Expected result: root and module rules confirm the scan must stay scoped to `hugegraph-llm` and `hugegraph-python-client`, avoid lower-frequency modules, and preserve client/LLM contract boundaries.

- [ ] **Step T0.2: Read prior quality-program documents**

Commands:

```bash
sed -n '1,260p' docs/specs/2026-05-31-hugegraph-ai-quality-program-design.md
sed -n '1,320p' docs/plans/2026-05-31-hugegraph-ai-quality-program.md
```

Expected result: reuse document style, restartable ledger structure, strict boundary wording, and checkpoint discipline without adopting the test-refactor implementation details.

- [ ] **Step T0.3: Create code-scan ledger**

If a scratch ledger is useful, create `.workflow/code-scan/` artifacts and initialize state with current branch, SHA, scan lanes, and empty issue counters.

- [ ] **Step T0.4: Commit setup slice**

Commands:

```bash
git add docs/specs/2026-05-31-hugegraph-ai-code-scan-design.md docs/plans/2026-05-31-hugegraph-ai-code-scan.md
git commit -m "docs(code-scan): add core module audit plan" -m "- define scoped P0-P5 code logic scan design
- document optional local scratch boundaries
- capture lane-based execution checklist"
```

## T1: Parallel Client Scan

**Files:**
- Optional local update: `.workflow/code-scan/checkpoints/01-client-transport.md`
- Optional local update: `.workflow/code-scan/checkpoints/02-client-api-structure.md`
- Optional local update: `.workflow/code-scan/reports/issues.md`
- Optional local update: `.workflow/code-scan/reports/module-map.md`
- Possible FIXME comments: `hugegraph-python-client/src/tests/**/*.py`

- [ ] **Step T1.1: Scan transport/auth/routing**

Review:

```text
hugegraph-python-client/src/pyhugegraph/client.py
hugegraph-python-client/src/pyhugegraph/utils/
hugegraph-python-client/src/pyhugegraph/api/auth.py
hugegraph-python-client/src/pyhugegraph/api/common.py
```

Focus: request construction, auth/session boundaries, URL routing, error propagation, timeout/retry behavior, exception semantics, and test coverage effectiveness.

- [ ] **Step T1.2: Scan graph/schema/gremlin APIs and structures**

Review:

```text
hugegraph-python-client/src/pyhugegraph/api/
hugegraph-python-client/src/pyhugegraph/structure/
hugegraph-python-client/src/tests/api/
```

Focus: API route correctness, response envelope parsing, schema/graph/gremlin semantics, mutation safety, data model drift, and weak test assertions.

- [ ] **Step T1.3: Synthesize client findings**

Deduplicate client issues, assign P0-P5, update both client checkpoints, and commit the client scan slice.

## T2: Parallel hugegraph-llm Scan

**Files:**
- Optional local update: `.workflow/code-scan/checkpoints/03-llm-api-config.md`
- Optional local update: `.workflow/code-scan/checkpoints/04-llm-flow-operator.md`
- Optional local update: `.workflow/code-scan/checkpoints/05-llm-index-model.md`
- Optional local update: `.workflow/code-scan/reports/issues.md`
- Optional local update: `.workflow/code-scan/reports/module-map.md`
- Possible FIXME comments: `hugegraph-llm/src/tests/**/*.py`

- [ ] **Step T2.1: Scan API/models/config/prompt layer**

Review:

```text
hugegraph-llm/src/hugegraph_llm/api/
hugegraph-llm/src/hugegraph_llm/config/
hugegraph-llm/src/hugegraph_llm/resources/
hugegraph-llm/src/tests/api/
hugegraph-llm/src/tests/config/
```

Focus: public request/response contracts, config precedence, prompt contract stability, error mapping, and test truthfulness.

- [ ] **Step T2.2: Scan flows/nodes/operators**

Review:

```text
hugegraph-llm/src/hugegraph_llm/flows/
hugegraph-llm/src/hugegraph_llm/nodes/
hugegraph-llm/src/hugegraph_llm/operators/
hugegraph-llm/src/hugegraph_llm/state/
hugegraph-llm/src/tests/operators/
hugegraph-llm/src/tests/integration/
```

Focus: GraphRAG/KG/Text2Gremlin boundaries, mutable state, error propagation, external service handling, duplicated logic, and pipeline tests that mock away behavior.

- [ ] **Step T2.3: Scan indices/models/utils/performance**

Review:

```text
hugegraph-llm/src/hugegraph_llm/indices/
hugegraph-llm/src/hugegraph_llm/models/
hugegraph-llm/src/hugegraph_llm/utils/
hugegraph-llm/src/tests/indices/
hugegraph-llm/src/tests/models/
```

Focus: provider wrapper semantics, vector store failure behavior, embedding/reranker assumptions, unbounded memory/network loops, and fallback correctness.

- [ ] **Step T2.4: Synthesize hugegraph-llm findings**

Deduplicate LLM issues, assign P0-P5, update all LLM checkpoints, and commit the LLM scan slice.

## T3: Cross-module Contract and Test-quality Synthesis

**Files:**
- Optional local update: `.workflow/code-scan/checkpoints/06-test-quality.md`
- Optional local update: `.workflow/code-scan/checkpoints/07-synthesis.md`
- Optional local update: `.workflow/code-scan/reports/issues.md`
- Optional local update: `.workflow/code-scan/reports/test-quality-ledger.md`
- Optional local update: `.workflow/code-scan/reports/final-code-scan-report.md`

- [ ] **Step T3.1: Cross-check pyhugegraph callers from hugegraph-llm**

Search and inspect all `pyhugegraph` imports/usages in `hugegraph-llm`, then verify caller assumptions against client response/data structures.

- [ ] **Step T3.2: Review all FIXME candidates**

Confirm each required `FIXME:` is present, specific, and tied to core behavior. Remove or rewrite vague comments.

- [ ] **Step T3.3: Produce final report**

Write a final report in the PR summary, a durable follow-up document, or the local scratch ledger with:

```text
Summary
Scope Covered
Issue Distribution by Priority
Top P0-P2 Findings
Test-quality and FIXME Summary
Cross-module Contract Risks
Style-only Fixes Applied
Verification Commands
Recommended Next Fix Plan
```

- [ ] **Step T3.4: Verify and final commit**

Run the narrowest available verification for touched files. At minimum:

```bash
git diff --check
git status --short
```

If Python files were edited for `FIXME:` or style-only changes, also run targeted ruff checks for those files.

Commit durable scan artifacts and any allowed non-behavioral edits. Do not commit local scratch outputs.
