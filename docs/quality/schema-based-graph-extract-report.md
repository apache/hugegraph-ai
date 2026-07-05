# Schema-based Graph Extraction — Effect Report

This report quantifies the quality gains delivered by the enhanced
schema-aware graph extraction strategy (Issue #74) against the pre-existing
baseline strategy.

## Executive Summary

Across a deterministic 10-scenario benchmark that stresses the failure modes
the enhanced strategy was designed to fix, enhanced improves overall F1 by
**+0.16** (from 0.84 to 1.00) while never regressing on any scenario.

| Metric | Baseline (avg) | Enhanced (avg) | Delta |
|---|---:|---:|---:|
| Overall F1 (vertices + edges) | 0.84 | 1.00 | **+0.16** |
| Property valid ratio | 1.00 | 1.00 | 0 |
| Property exact match rate | 0.90 | 1.00 | **+0.10** |

Every number here is reproducible: it comes straight from the offline
benchmark test :file:`test_property_graph_benchmark.py`, which drives both
strategies through the same deterministic `FakeLLM` responses and evaluates
each output against ground truth.

## Per-Scenario Results

| Scenario | Baseline F1 | Enhanced F1 | Baseline valid % | Enhanced valid % | Baseline match % | Enhanced match % |
|---|---:|---:|---:|---:|---:|---:|
| s01: simple well-formed | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| s02: extra property filtered | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| s03: type coercion (INT) | 1.00 | 1.00 | 1.00 | 1.00 | **0.50** | **1.00** |
| s04: missing primary key | **0.00** | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 |
| s05: duplicate vertex across chunks | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| s06: cross-chunk edge | **0.80** | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 |
| s07: alias mismatch (raw vs canonical) | **0.80** | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 |
| s08: invalid label | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| s09: malformed JSON | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| s10: coerce + cross-chunk combined | **0.80** | **1.00** | 1.00 | 1.00 | **0.50** | **1.00** |
| **Average** | **0.84** | **1.00** | 1.00 | 1.00 | **0.90** | **1.00** |

Bolded cells highlight where the two strategies diverge.

## Where Enhanced Wins, and Why

### s04 — Missing primary key (F1 0.00 → 1.00)

Baseline keeps a Person vertex whose LLM output has no `name` property, using
the LLM's raw id (`v1`) as the vertex id. Enhanced drops it via a
`MISSING_PRIMARY_KEY` structured warning. Ground truth is empty, so baseline
gets a false positive that tanks precision to 0.

### s06 — Cross-chunk edge (F1 0.80 → 1.00)

Chunk 1 defines `Person Tom Hanks (v1)`. Chunk 2 defines `Movie Forrest Gump`
and emits an `ACTED_IN` edge from `v1` to `v2`. Baseline processes chunks
independently, so chunk 2's edge cannot resolve `v1` and the edge is dropped.
Enhanced's `DocumentGraphAssembler` unions per-chunk alias tables before
resolving endpoints, so the edge survives.

### s07 — Alias mismatch (F1 0.80 → 1.00)

Chunk 1 emits `Person Tom Hanks (v1)`; chunk 2's edge references the same
entity by its canonical id `1:Tom Hanks`. Baseline cannot cross that alias
boundary and drops the edge. Enhanced's alias table records both forms and
resolves cleanly.

### s03 & s10 — Type coercion (property match 0.50 → 1.00)

The LLM emits an INT property as a string (`"age": "62"`). Baseline's
`filter_item` only checks schema key membership, not type, so the string
survives to the API response. Enhanced's `SchemaAwareNormalizer` calls
`coerce_property_value` and converts to int, matching ground truth exactly.

## Where the Two Strategies Match

Both strategies handle equally well:

* Well-formed single-chunk extraction (s01).
* Extra properties outside the schema (s02): baseline via `filter_item`,
  enhanced via the normalizer's property filter.
* Duplicate vertices across chunks (s05): set-based F1 dedupes for scoring,
  so both look perfect — enhanced still reports one fewer raw vertex, which
  reduces downstream commit load.
* Invalid labels (s08): both drop them, enhanced additionally emits a
  structured `UNKNOWN_VERTEX_LABEL` warning.
* Malformed JSON (s09): both return an empty graph. Enhanced additionally
  emits `JSON_DECODE_FAILED`.

## Metric Definitions

* **Precision** (`item_type`) = `|predicted ∩ expected| / |predicted_unique|`
  where the match key is `(label, id)` for vertices and
  `(label, outV, inV)` for edges. Empty predicted → precision defined as 1.0.
* **Recall** (`item_type`) = `|predicted ∩ expected| / |expected|`. Empty
  expected → recall defined as 1.0.
* **F1** = `2 * precision * recall / (precision + recall)`, or 0 when both
  are 0. Both empty → F1 = 1.0.
* **Overall F1** = combined vertex + edge precision/recall harmonic mean.
* **Property valid ratio** = fraction of predicted (label, key) pairs whose
  key is declared on that label in the schema. Empty predicted → 1.0.
* **Property exact match rate** = fraction of expected properties on TP items
  whose predicted (key, value) matches exactly (Python `==`). Empty expected
  on TP items → 1.0.

## Reproducing These Numbers

The benchmark is deterministic — it uses a `FakeLLM` with hard-coded
responses. To reproduce the table:

```bash
uv run --directory hugegraph-llm pytest \
  src/tests/operators/llm_op/test_property_graph_benchmark.py::test_benchmark_produces_comparison_table \
  -s
```

The `-s` flag surfaces the Markdown table printed by the test. The table
above is the verbatim output of that command.

## Scope and Caveats

* **Deterministic FakeLLM.** These numbers isolate the extraction pipeline
  from LLM variance. They do not measure the LLM's semantic extraction
  quality on real prose; they measure how well each strategy converts a
  fixed LLM output into a schema-conforming property graph.
* **Set-based F1.** Duplicate predictions are deduped for scoring, so
  baseline's cross-chunk duplication cost is not visible in F1. The raw vs
  unique counts are still reported per `ItemMetrics`; downstream systems that
  care about commit-load can read those numbers.
* **Ground truth uses canonical ids.** When a schema entry omits `id` (as
  inline user schemas often do), neither strategy can compute canonical ids.
  In that regime, the evaluator falls back to `(label, raw_id)` matching for
  both strategies, keeping the comparison fair.
