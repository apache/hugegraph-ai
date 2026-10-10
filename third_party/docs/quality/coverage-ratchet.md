# Coverage Ratchet

## Principles

- Start with local areas, not a full-repo threshold.
- New production logic requires tests.
- Bug fixes require regression tests.
- HugeGraph boundaries need Layer B or Layer C evidence.
- Thresholds may start low but must not decrease.
- External provider, vector DB, and UI credential paths stay outside default PR ratchets.

## Initial Ratchet Areas

- `pyhugegraph`
- `hugegraph_llm.operators.hugegraph_op`
- `hugegraph_llm.operators.llm_op`
- `hugegraph_llm.api`
- `hugegraph_llm.api.models`

## Baseline

Current combined baseline:

| Scope | Covered lines | Statements | Missing lines | Coverage |
|---|---:|---:|---:|---:|
| `pyhugegraph` + `hugegraph_llm` unit/contract | 3115 | 7975 | 4860 | 39% |

The original combined command hits a pytest import-path collision because both workspace packages define a `tests.conftest` module. Use `--import-mode=importlib` for combined workspace baselines until the test package layout is normalized.

## CI Gates

The default unit/contract jobs enforce module-level floors from the initial local baseline runs:

| Workflow | Scope | Gate |
|---|---|---:|
| `.github/workflows/hugegraph-python-client.yml` | `pyhugegraph` unit/contract | `--cov-fail-under=45` |
| `.github/workflows/hugegraph-llm.yml` | `hugegraph_llm` unit/contract | `--cov-fail-under=34` |

These gates are intentionally baseline-level floors. Raise them only after the corresponding local ratchet areas gain meaningful tests.

## Local Commands

```bash
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --cov=pyhugegraph --cov-report=term
uv run pytest hugegraph-llm/src/tests/operators/hugegraph_op -m "unit or contract" --cov=hugegraph_llm.operators.hugegraph_op --cov-report=term
uv run pytest hugegraph-llm/src/tests/operators/llm_op -m "unit or contract" --cov=hugegraph_llm.operators.llm_op --cov-report=term
uv run pytest hugegraph-llm/src/tests/api -m "unit or contract" --cov=hugegraph_llm.api --cov-report=term
```

Combined workspace baseline command:

```bash
uv run pytest --import-mode=importlib hugegraph-python-client/src/tests hugegraph-llm/src/tests \
  -m "unit or contract" \
  --cov=pyhugegraph \
  --cov=hugegraph_llm \
  --cov-report=term \
  --cov-report=json:combined-baseline.json
```

## Ratchet Rules

- Do not lower an existing local threshold for a touched ratchet area.
- For production bug fixes, add or update a regression test in the nearest unit, contract, integration, or smoke layer.
- For HugeGraph service-boundary changes, include a selected Layer B or Layer C command with `HUGEGRAPH_REQUIRED=true`.
- For new external-provider behavior, keep deterministic contract tests in default gates and reserve live-provider coverage for Layer D.
