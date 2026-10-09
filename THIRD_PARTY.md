# Third-party components

| Component | Source | Merged at | Sync policy |
|---|---|---|---|
| Apache HugeGraph AI (hugegraph-llm, hugegraph-mcp, hugegraph-ml, hugegraph-python-client, vermeer-python-client) | https://github.com/apache/hugegraph-ai | main@`9922568` ("fix(llm): preserve semantic embedding batch order"), merged via subtree into `third_party/` | **Never edit files under `third_party/` directly.** Upstream fixes arrive as subtree merges of an upstream ref; unavoidable local changes go through `third_party/patches/` and MUST be registered here. |

## Acceptance invariants (merge-plan §1.7)

- `git grep -rn "hugegraph_llm\|hugegraph_ml" server/ extensions/ tests/` → zero hits (no import coupling)
- `pyproject.toml` / `uv.lock` carry no dependency on third_party packages
- `third_party/` is excluded from ruff and from the default CI gate (a smoke job only checks presence + LICENSE)

## Curation record (M0)

Repo-machinery files that only function at a repository root were removed from
the vendored copy: `.asf.yaml`, `.github/`, `.gitattributes`, `.licenserc.yaml`,
`.pre-commit-config.yaml`. The upstream `.gitignore` was merged into the root
`.gitignore` (entries scoped under `third_party/`). Everything else — code,
LICENSE, NOTICE, README, workspace `pyproject.toml` — is kept byte-for-byte.
