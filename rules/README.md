# Optional workflow for complex changes

This directory provides a staged development workflow for changes that are difficult to reason about in one pass. Use it for cross-module features, public API contracts, migrations, security-sensitive behavior or requirements that need explicit design decisions. Do not create workflow documents for a small, well-understood local fix.

## Choose only the stages you need

| Stage | Read | Working output |
|---|---|---|
| Establish repository constraints | [basic.md](basic.md) | None; apply the relevant repository and module guidance |
| Clarify an ambiguous or high-risk requirement | [requirements.md](requirements.md) | `.workflow/<topic>/requirements.md` |
| Compare alternatives and define boundaries | [design.md](design.md) | `.workflow/<topic>/design.md` |
| Split the agreed scope into verifiable steps | [plan.md](plan.md) | `.workflow/<topic>/tasks.md` |
| Implement and verify the planned change | [execute.md](execute.md) | Code, tests and concise evidence in the pull request |

A stage document is a tool for resolving uncertainty, not a mandatory ceremony. Skip a stage when its questions are already answered by an issue, an existing design or a narrow code contract. `.workflow/` is ignored by Git: its files are local working notes and are not shared in a pull request. Record decisions and evidence needed by collaborators in a tracked document or issue.

## Core principles

1. **Research before redesign.** Locate the owning module, current callers, reusable interfaces, tests and compatibility constraints before proposing new abstractions.
2. **Keep one source of truth.** Requirements describe user-visible outcomes; design describes contracts and boundaries; tasks describe implementation order. Do not repeat the same narrative in every file.
3. **Prefer the smallest complete change.** Reuse existing clients and extension points, avoid unrelated cleanup and do not introduce framework layers without a demonstrated need.
4. **Make risk explicit.** Record compatibility, security, data, rollout and rollback implications when they materially affect the design.
5. **Verify behavior, not activity.** Evidence should show tests, observable results and unresolved limits. A chronological execution log is not required.
6. **Revisit decisions when evidence changes.** Update the smallest affected requirement or design section instead of appending contradictory notes.

## Working method

1. Read the root and nearest module `AGENTS.md`, the [repository documentation index](../docs/README.md), and the relevant source/tests.
2. Decide which uncertainty remains and open only the corresponding stage document.
3. Keep workflow files concise and task-oriented. Link stable source paths and configuration names; do not embed pull-request links, commit hashes, model recommendations or timestamps.
4. Agree on requirements and design before implementation when the change is collaborative, externally visible or difficult to reverse.
5. Execute in small reviewable steps, run the affected-module checks, and summarize final evidence and known boundaries in the pull request.

The files under [`prompts/`](prompts/) are optional templates. They do not override repository ownership, testing, security or documentation rules.
