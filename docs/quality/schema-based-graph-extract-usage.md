# Schema-based Graph Extraction — Usage Guide

The enhanced graph extraction strategy is an **opt-in** upgrade to the
`/graph/extract` API and the `GraphExtractFlow` pipeline. This document
covers how to enable it, when it helps, and its known limitations.

## Quickstart

### HTTP API

Existing callers keep working unchanged (baseline is still the default):

```bash
curl -X POST http://localhost:8001/graph/extract \
  -H "Content-Type: application/json" \
  -d '{
    "texts": ["Tom Hanks starred in Forrest Gump."],
    "graph_schema": "movie_graph"
  }'
```

To enable the enhanced strategy, add `extract_strategy: "enhanced"`:

```bash
curl -X POST http://localhost:8001/graph/extract \
  -H "Content-Type: application/json" \
  -d '{
    "texts": ["Tom Hanks starred in Forrest Gump."],
    "graph_schema": "movie_graph",
    "extract_strategy": "enhanced",
    "include_meta": true
  }'
```

Enhanced-only fields in the response `meta` block:

| Field | Type | Description |
| --- | --- | --- |
| `extract_strategy` | `"enhanced"` | Echoes the strategy in effect. Absent under baseline. |
| `chunk_count` | int | Number of chunks the input was split into. |
| `call_count` | int | Number of LLM invocations (== chunk_count). |
| `token_usage` | str | Placeholder `"unavailable"` until the LLM adapter surfaces token metadata. |
| `structured_warnings` | list | Machine-readable warning records — see below. |
| `quality_metrics` | dict | Per-run quality aggregate — see below. |

Passing `include_debug: true` additionally surfaces `meta.debug_info`
with per-chunk raw LLM output (truncated to 2 KB) plus normalized item
counts. Use this in staging for prompt tuning; keep it off in production
to avoid response bloat.

### Python SDK

```python
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton

result = SchedulerSingleton.get_instance().schedule_flow(
    FlowName.GRAPH_EXTRACT,
    schema=my_schema,
    texts=["…"],
    example_prompt="…",
    extract_type="…",
    extract_strategy="enhanced",   # opt-in
    include_debug=False,           # optional, default False
)
```

The `result` string is a JSON payload compatible with the baseline
schema; enhanced-only fields appear as additional top-level keys.

## Structured Warnings

Each warning has this shape:

```json
{
  "code": "MISSING_PRIMARY_KEY",
  "item_type": "vertex",
  "reason": "vertex 'Person' has no value for primary key 'name'",
  "chunk_id": 0
}
```

Warning codes are grouped by their producer stage (parser, normalizer,
assembler, quality gate). Full list in
[`property_graph_extract_enhanced/warnings.py`](../../hugegraph-llm/src/hugegraph_llm/operators/llm_op/property_graph_extract_enhanced/warnings.py).

Common codes:

* `MISSING_PRIMARY_KEY` — vertex is dropped because a PK value is missing.
* `PROPERTY_COERCED` — a property value was converted to its schema type
  (e.g. `"62"` → `62`). Non-fatal.
* `UNKNOWN_VERTEX_LABEL` / `UNKNOWN_EDGE_LABEL` — item dropped for using a
  label not in the schema.
* `ENDPOINT_INCOMPATIBLE` — edge direction violates the schema
  `source_label` / `target_label`.
* `PENDING_ENDPOINT_UNRESOLVED` — edge references a vertex that no chunk
  ever defined.
* `JSON_DECODE_FAILED` — the LLM's chunk output could not be parsed.

## Quality Metrics

Each enhanced run reports a `quality_metrics` block with 11 fields
including `parse_success_rate`, `endpoint_repair_rate`,
`property_coerce_rate`, `dropped_item_count`, and
`warning_code_distribution`. Full field list in
[`property_graph_extract_enhanced/quality_gate.py`](../../hugegraph-llm/src/hugegraph_llm/operators/llm_op/property_graph_extract_enhanced/quality_gate.py).

Use these as live signals in staging: a sudden spike in
`property_coerce_rate` usually means the prompt drifted and started
emitting stringified numerics; a spike in `endpoint_repair_rate` means
chunking may be too aggressive.

## Applicable Scenarios

The enhanced strategy helps most when **any** of these hold:

* **Multi-chunk documents.** The strategy's `DocumentGraphAssembler`
  merges vertices across chunks and repairs cross-chunk edge endpoints —
  the biggest F1 win in the benchmark comes from here.
* **Strict schema with canonical id requirements.** If HugeGraph's
  `PRIMARY_KEY` id strategy is in use, enhanced ensures every emitted
  vertex has a valid canonical id and drops PK-missing candidates before
  they reach the commit stage.
* **Typed properties beyond TEXT.** INT/LONG/FLOAT/BOOLEAN/DATE columns
  benefit from enhanced's best-effort coercion. Baseline's `filter_item`
  is key-only and does not repair types.
* **Prompts under drift.** Structured warnings + quality metrics give
  operators a signal to detect when a previously-good prompt starts
  regressing.

Baseline remains a fine default when:

* Every schema property is TEXT.
* Documents fit in a single chunk.
* No canonical id is needed downstream (e.g., `id_strategy = "AUTOMATIC"`).
* You want to minimize LLM prompt tokens (see limitation below).

## Known Limitations

* **Prompt-token overhead.** The enhanced strategy appends a
  `constraint_block` listing every schema label to the LLM prompt on
  every chunk (~500-800 extra tokens for a small schema, more for large
  ones). This is real cost on paid APIs. For a 100-chunk document this
  is 50k-80k extra tokens; at DeepSeek Chat pricing (2026-07 rates) that
  is single-digit cents but non-zero.

* **Coercion is best-effort, not lossless.** `"1994"` → `1994` (INT) is
  safe. `"1.5"` → `1` (INT) drops information — enhanced emits
  `PROPERTY_COERCED` with the reason string. Review warnings before
  concluding the graph is clean.

* **No cross-request state.** The alias table is scoped to a single
  request. Two entities with the same schema-canonical id extracted from
  different `/graph/extract` calls still land as two records — this is
  the storage layer's job, not the extractor's.

* **Set-based F1.** The offline evaluator scores against deduplicated
  predictions. Baseline's raw-count duplication cost does not surface in
  F1; if you care about commit load, read the raw counts from the
  benchmark's per-scenario `predicted_count_raw`.

* **No streaming.** Enhanced processes all chunks synchronously and
  produces the assembled graph at the end. For very large documents,
  consider chunking upstream and calling `/graph/extract` per batch.

* **No knowledge-base entity resolution.** Enhanced can resolve aliases
  *within* a single request (e.g. `"He"` → `"Tom Hanks"` when both
  appear in different chunks) via its `DocumentGraphAssembler`. It
  cannot resolve *out-of-corpus* aliases: if the LLM extracts
  `"Thomas Jeffrey Hanks"` from an article's opening line and the
  downstream canonical id is `"Tom Hanks"`, both records land as
  separate vertices. Solving this needs either LLM-side alignment
  (system prompt telling the model to emit shortest canonical names) or
  an external entity-resolution step (string similarity + gazetteer /
  Wikidata / customer-supplied alias table). Both are out of scope for
  Issue #74. See the effect report's live-benchmark failure analysis
  for concrete numbers.

## When enhanced does **not** help

The live benchmark on 8 public Wikipedia corpora showed enhanced
regressing F1 on 3 of the 8 corpora (baseline already strong; enhanced's
stricter deduplication merged near-duplicate film titles that were
actually different films). Consider running baseline first and switching
to enhanced only if `warnings` count is high or if quality is
consistently under target. A production deployment can gate this on
first-pass baseline warning counts.

## Migration Notes

None required. Existing baseline callers keep byte-compatible responses
as long as they do not send `extract_strategy` or `include_debug`.

If you are the first team to opt-in on a graph, run one enhanced request
with `include_meta=true` and inspect `meta.structured_warnings` /
`meta.quality_metrics` — the warning codes indicate any places where the
prompt is drifting from the schema, and you should tighten those before
switching all traffic.

## References

* [Effect Report](./schema-based-graph-extract-report.md) — quality and
  latency benchmark numbers.
* [Test Taxonomy](./test-taxonomy.md) — where the benchmark fits in the
  overall test pyramid.
* Source:
  [`hugegraph_llm/operators/llm_op/property_graph_extract_enhanced/`](../../hugegraph-llm/src/hugegraph_llm/operators/llm_op/property_graph_extract_enhanced/)
