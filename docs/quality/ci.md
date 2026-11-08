# CI selection and validation

The **HugeGraph AI CI** workflow owns push/PR selection and shared configuration.
Its preflight checks synchronized release metadata and runs the release-tooling
and selection-policy tests. The selected suites and changed paths are recorded
in the job summary. A failed diff or preflight fails CI rather than skipping tests.

| Change | Default runtime tests |
| --- | --- |
| Repository-level README/Markdown outside tested modules | No runtime environment, Docker or custom CodeQL |
| Module README/docs, including examples and data files | Owning module, preserving documentation/example contracts |
| Python client | Client plus downstream LLM and MCP |
| Standalone LLM SDK | SDK plus downstream LLM compatibility tests |
| Standalone LLM eval SDK | Eval |
| LLM | LLM |
| MCP | MCP |
| Root dependency/release configuration or shared CI setup | Client, SDK, Eval, LLM and MCP |
| Module CI workflow | That module and its downstream consumers |
| Docker configuration or LLM image build script | LLM |
| Archive exclusions (`.gitattributes`) | Client archive installation guard and downstream LLM/MCP |

Ruff runs once for Python/lint/shared configuration changes using `uvx`, without
installing application dependencies. License checks share the preflight runner.
Every `pyproject.toml` change selects quality checks, including module and
nested configurations that may change Ruff/type-check behavior.
Dependency review runs for dependency changes on same-repository PRs; its token
restrictions for fork PRs are unchanged. Deleted files and both sides of a rename
participate in selection.

SDK changes run the SDK distribution contracts and downstream LLM adapter tests,
without selecting unrelated client/MCP suites. The SDK workflow builds outside
the application workspace and verifies both wheel and sdist in clean environments
with only base dependencies. Offline examples and installed-wheel tests run
before optional provider extras are installed. Provider contracts then share
the primary-runtime SDK runner, avoiding a duplicate build and setup job.

Ordinary runs use the primary Python version defined in `tool.hugegraph.ci` in
the root `pyproject.toml`. Each application module reuses one dependency environment and one
HugeGraph service for its unit, integration and smoke phases. Existing coverage
thresholds remain enforced. Integration tests fail if the service is unavailable.
Server image digests and the `/versions` response are logged; `versions.core`
must match the prepared release version. Backend capability gates remain unchanged.
Following Server `latest` is an intentional development/test policy, so a future
master image changing its core version is expected to fail this guard. The
Compose `HUGEGRAPH_SERVER_IMAGE` override supports reproducible deployments with
a verified release tag or digest without pinning the CI image.

The primary-runtime client job also verifies the actual `git archive` source
distribution: ML and Docker remain excluded, all included workspace packages
build, and `uv sync --all-packages` plus `uv pip check` validate installation.
This archive check is separate from release metadata validation, which needs
the complete commit tree before distribution exclusions are applied.

GitHub-owned `setup-python` selects the interpreter; the root uv version is
installed with pip before project dependencies are managed with uv. This avoids
third-party setup actions blocked by ASF's action allowlist. GitHub `cache`
restores uv/pip downloads by component, Python runtime and relevant manifests;
uv caches are pruned before upload. LLM jobs also cache NLTK and tiktoken data.
Coverage uses `sys.monitoring` on the supported Python 3.12–3.14 runtimes. The
older C tracer makes Jieba's generated POS tables very slow to import on 3.12;
the coverage thresholds and measured application code are unchanged.
Ruff, dependency review and CodeQL each have a single job rather than a runtime
matrix. New PR heads cancel superseded PR runs because each PR diff covers its
whole branch. Push, scheduled and manual runs use unique run groups and are not
cancelled or replaced by later runs, preserving every incremental main-push diff.

The default toolchain is **uv + Ruff + ty**. The uv version is defined in
`tool.hugegraph.ci`; Ruff and ty use `>=` lower bounds in root development dependencies.
CI reads those lower bounds and uses the same ranges. Local pre-commit hooks run
Ruff through uv, without a fixed remote hook revision. The legacy formatting/lint script now uses uv/Ruff/ty
instead of Black/Pylint; `-b` and `-p` retain their format/lint selections.

ty runs on the primary-runtime client, SDK, LLM and MCP jobs by default, without
adding runners. MCP uses its standalone Python environment for import resolution.
Application type checks retain the existing advisory status: the current ty
baseline contains unresolved diagnostics, so a ty failure is visible but does
not fail `CI Result`. Ruff and tests remain blocking. Clearing that baseline and
making application type checks blocking is separate work.
Release/CI scripts have a clean ty baseline and are checked as a blocking step
in the existing quality runner, using their Python 3.12+ target.

## Full and optional checks

- Weekly on ASF main (Monday 06:00 Asia/Taipei), release-branch pushes, and manual
  **full** runs validate the client, LLM, MCP and SDK on Python 3.12–3.14,
  plus CodeQL. Python 3.11 and older are no longer supported by these modules. Docker integration runs
  once per module on the primary Python runtime.
- Use **Run workflow → mainline** for the primary-runtime checks on the selected
  branch, **full** for the complete matrix, **codeql** for security scanning, or
  **dependencies** with a base ref for dependency review.
- **Rerun CI** is manual and accepts a failed run ID. Automatic delayed retries
  were removed; a deterministic test failure no longer allocates retry runners.

Python source/stub and dependency-manifest changes select CodeQL, preserving
PR/main scanning on repositories without GitHub default setup. Weekly/full and
manual CodeQL runs are also supported. Module Markdown alone does not select
CodeQL, but still runs its owning module's contract tests. Non-Markdown files
under `docs/` use the same source/data rules as other files.

When CodeQL is selected, preflight reads the repository's workflow metadata with
`actions:read`. An active `dynamic/github-code-scanning/codeql` workflow means
GitHub default setup already owns scanning, so the custom CodeQL job is skipped.
This avoids both duplicate runners and GitHub's rejection of advanced SARIF
uploads while default setup is enabled. Without an active default scanner, the
selected custom workflow runs normally. Metadata-query failures fail preflight.
GitHub default scans keep their own triggers and check results, outside
`CI Result`; a manual `codeql` selection does not force a new default-setup scan.

## Required check migration

Use **CI Result** as the required branch-protection check for jobs owned by this
workflow. It fails for any failed/cancelled selected job or failed preflight and
accepts intentionally skipped suites. When GitHub default CodeQL setup is active,
keep its emitted code-scanning check separately required because that scan
deliberately remains outside `CI Result`. Without default setup, the selected
custom CodeQL job is aggregated into `CI Result`. Replace old per-module matrix
check names in repository rules when adopting this workflow; code changes here
do not update GitHub rules.

The regular test workflows are reusable and receive configuration from preflight.
They do not independently trigger duplicate runs. PR labeling and other repository
administration workflows retain their existing triggers.
