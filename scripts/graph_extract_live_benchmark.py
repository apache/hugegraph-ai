# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Live-LLM benchmark for the schema-based graph extraction strategies.

Runs the baseline and enhanced extraction pipelines against a real LLM
(DeepSeek Chat via LiteLLM) using a fixed multi-chunk corpus, and reports
quality (F1 vs. ground truth), latency (wall-clock), LLM call count,
prompt/completion tokens, and an approximate USD cost per run.

This script is deliberately kept OUT of the pytest test tree — it costs
real money and requires network + DEEPSEEK_API_KEY. It is only invoked
manually to produce the "Live LLM Benchmark" section of the effect
report.

Usage:

    # DEEPSEEK_API_KEY must be set (loaded from .env.local by default).
    python scripts/graph_extract_live_benchmark.py

Output:

    * Human-readable table to stdout.
    * Full run record (per-strategy metrics + LLM I/O) to
      ``.workflow/deepseek_live_run.json`` for archival.

Cost estimates use DeepSeek Chat pricing as published at
https://api-docs.deepseek.com/quick_start/pricing at the time of the
run. Rates are hard-coded below; update if pricing changes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Ensure the local hugegraph-llm package is importable when invoked from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "hugegraph-llm" / "src"))

from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract  # noqa: E402
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced import (  # noqa: E402
    GraphExtractionEvaluator,
    GraphSchemaIndex,
)

# DeepSeek Chat pricing as of 2026-07 (per 1M tokens, cache-miss standard rate).
# Update if pricing shifts. Source: https://api-docs.deepseek.com/quick_start/pricing
DEEPSEEK_INPUT_USD_PER_M = 0.27
DEEPSEEK_OUTPUT_USD_PER_M = 1.10
DEEPSEEK_MODEL_LITELLM = "deepseek/deepseek-chat"


SCHEMA: dict[str, Any] = {
    "propertykeys": [
        {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "year", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
    ],
    "vertexlabels": [
        {
            "id": 1,
            "name": "Person",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["name"],
            "properties": ["name", "age"],
            "nullable_keys": ["age"],
        },
        {
            "id": 2,
            "name": "Movie",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["title"],
            "properties": ["title", "year"],
            "nullable_keys": ["year"],
        },
    ],
    "edgelabels": [
        {
            "name": "ACTED_IN",
            "source_label": "Person",
            "target_label": "Movie",
            "properties": ["role"],
        },
    ],
}


# Three-chunk corpus with cross-chunk entity references — the exact class
# of input where enhanced is expected to win in production.
CORPUS: list[str] = [
    (
        "Tom Hanks is an American actor. He starred in Forrest Gump, "
        "which was released in 1994. The film won six Academy Awards."
    ),
    (
        "Tom Hanks also acted in Cast Away, which came out in 2000. "
        "In it, he played Chuck Noland, a FedEx executive who survives a "
        "plane crash and becomes stranded on a deserted island."
    ),
    (
        "He additionally voiced Woody in the Toy Story franchise. "
        "Toy Story premiered in 1995 and revolutionized computer animation."
    ),
]


# Ground truth: what a schema-conformant extraction of the corpus above
# should produce. Canonical ids follow the {vertex_label.id}:{pk} rule.
GROUND_TRUTH: dict[str, list[dict[str, Any]]] = {
    "vertices": [
        {"label": "Person", "type": "vertex", "id": "1:Tom Hanks", "properties": {"name": "Tom Hanks"}},
        {
            "label": "Movie",
            "type": "vertex",
            "id": "2:Forrest Gump",
            "properties": {"title": "Forrest Gump", "year": 1994},
        },
        {"label": "Movie", "type": "vertex", "id": "2:Cast Away", "properties": {"title": "Cast Away", "year": 2000}},
        {"label": "Movie", "type": "vertex", "id": "2:Toy Story", "properties": {"title": "Toy Story", "year": 1995}},
    ],
    "edges": [
        {
            "label": "ACTED_IN",
            "type": "edge",
            "outV": "1:Tom Hanks",
            "inV": "2:Forrest Gump",
            "outVLabel": "Person",
            "inVLabel": "Movie",
            "properties": {},
        },
        {
            "label": "ACTED_IN",
            "type": "edge",
            "outV": "1:Tom Hanks",
            "inV": "2:Cast Away",
            "outVLabel": "Person",
            "inVLabel": "Movie",
            "properties": {"role": "Chuck Noland"},
        },
        {
            "label": "ACTED_IN",
            "type": "edge",
            "outV": "1:Tom Hanks",
            "inV": "2:Toy Story",
            "outVLabel": "Person",
            "inVLabel": "Movie",
            "properties": {"role": "Woody"},
        },
    ],
}


EXTRACT_PROMPT_HEADER = """You are extracting a property graph from text.

Output ONLY a JSON object with two keys: "vertices" and "edges".
Every vertex has: label, type: "vertex", id, properties (object).
Every edge has: label, type: "edge", outV, inV, outVLabel, inVLabel, properties (object).

Do not include any text outside the JSON.
"""


@dataclass
class LLMCallRecord:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float


@dataclass
class StrategyRunMetrics:
    strategy: str
    predicted: dict[str, Any]
    total_latency_ms: float
    call_count: int
    prompt_tokens_total: int
    completion_tokens_total: int
    tokens_total: int
    cost_usd_estimate: float
    calls: list[dict[str, Any]] = field(default_factory=list)


class TrackedDeepSeekLLM:
    """LLM adapter that captures per-call token usage + wall-clock latency."""

    def __init__(self, api_key: str, model: str = DEEPSEEK_MODEL_LITELLM) -> None:
        from litellm import completion  # imported lazily so the module imports without litellm on non-live paths

        self._completion = completion
        self._api_key = api_key
        self._model = model
        self.calls: list[LLMCallRecord] = []

    def generate(self, prompt: str | None = None, messages: list[dict[str, Any]] | None = None, **_) -> str:
        if messages is None:
            assert prompt is not None
            messages = [{"role": "user", "content": prompt}]
        start = time.perf_counter()
        response = self._completion(
            model=self._model,
            messages=messages,
            api_key=self._api_key,
            temperature=0.0,
            max_tokens=2048,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        usage = response.usage
        self.calls.append(
            LLMCallRecord(
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                latency_ms=elapsed_ms,
            )
        )
        return response.choices[0].message.content


@dataclass
class SingleRunResult:
    """One (corpus, strategy, run-index) trial with metrics + evaluation."""

    corpus_name: str
    strategy: str
    run_index: int
    predicted: dict[str, Any]
    total_latency_ms: float
    call_count: int
    prompt_tokens_total: int
    completion_tokens_total: int
    tokens_total: int
    cost_usd_estimate: float
    calls: list[dict[str, Any]] = field(default_factory=list)
    overall_f1: float = 0.0
    vertex_f1: float = 0.0
    edge_f1: float = 0.0
    property_match_rate: float = 0.0
    evaluation: dict[str, Any] | None = None


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens * DEEPSEEK_INPUT_USD_PER_M / 1_000_000.0
        + completion_tokens * DEEPSEEK_OUTPUT_USD_PER_M / 1_000_000.0
    )


def _run_strategy_on_corpus(
    strategy: str,
    api_key: str,
    schema: dict[str, Any],
    chunks: list[str],
    expected: dict[str, Any],
    corpus_name: str,
    run_index: int,
    evaluator: GraphExtractionEvaluator,
) -> SingleRunResult:
    """Runs one strategy against one corpus once; returns a SingleRunResult
    with LLM metrics and evaluation baked in.
    """
    llm = TrackedDeepSeekLLM(api_key=api_key)
    extractor = PropertyGraphExtract(
        llm=llm,
        example_prompt=EXTRACT_PROMPT_HEADER,
        extract_strategy=strategy,
    )
    context = {"schema": schema, "chunks": list(chunks)}
    start = time.perf_counter()
    result = extractor.run(context)
    total_latency_ms = (time.perf_counter() - start) * 1000.0

    prompt_tokens_total = sum(c.prompt_tokens for c in llm.calls)
    completion_tokens_total = sum(c.completion_tokens for c in llm.calls)
    tokens_total = sum(c.total_tokens for c in llm.calls)

    predicted = {"vertices": result.get("vertices", []), "edges": result.get("edges", [])}
    evaluation = evaluator.evaluate(predicted, expected)

    return SingleRunResult(
        corpus_name=corpus_name,
        strategy=strategy,
        run_index=run_index,
        predicted=predicted,
        total_latency_ms=total_latency_ms,
        call_count=int(result.get("call_count", 0) or len(llm.calls)),
        prompt_tokens_total=prompt_tokens_total,
        completion_tokens_total=completion_tokens_total,
        tokens_total=tokens_total,
        cost_usd_estimate=_estimate_cost(prompt_tokens_total, completion_tokens_total),
        calls=[asdict(c) for c in llm.calls],
        overall_f1=evaluation.overall_f1,
        vertex_f1=evaluation.vertex_metrics.f1,
        edge_f1=evaluation.edge_metrics.f1,
        property_match_rate=evaluation.property_metrics.property_exact_match_rate,
        evaluation=evaluation.to_dict(),
    )


def _agg_stats(values: list[float]) -> dict[str, float]:
    """mean/std/min/max over a list of floats. std is 0 for n<2 (documented)."""
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "n": 0}
    return {
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values) if len(values) >= 2 else 0.0,
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


def _aggregate(runs: list[SingleRunResult]) -> dict[str, Any]:
    """Aggregate a set of runs into mean/std/min/max on the headline metrics."""
    return {
        "runs": len(runs),
        "overall_f1": _agg_stats([r.overall_f1 for r in runs]),
        "vertex_f1": _agg_stats([r.vertex_f1 for r in runs]),
        "edge_f1": _agg_stats([r.edge_f1 for r in runs]),
        "property_match_rate": _agg_stats([r.property_match_rate for r in runs]),
        "latency_ms": _agg_stats([r.total_latency_ms for r in runs]),
        "prompt_tokens_total": _agg_stats([float(r.prompt_tokens_total) for r in runs]),
        "completion_tokens_total": _agg_stats([float(r.completion_tokens_total) for r in runs]),
        "cost_usd_estimate": _agg_stats([r.cost_usd_estimate for r in runs]),
    }


def _load_env_local() -> None:
    """Loads .env.local into os.environ. Silently no-ops if the file is absent."""
    env_path = _REPO_ROOT / ".env.local"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _load_corpora(corpus_path: str | None) -> list[dict[str, Any]]:
    """Loads corpora from --corpus JSON or falls back to the legacy hard-coded one.

    Legacy fallback is preserved for two reasons: (1) it lets the script be
    smoke-tested with zero setup, and (2) it makes the change to add
    ``--corpus`` support strictly additive (no breaking behavior for anyone
    who previously ran the script without arguments).
    """
    if corpus_path is None:
        return [
            {
                "name": "legacy_tom_hanks_3chunk",
                "chunks": list(CORPUS),
                "ground_truth": GROUND_TRUTH,
                "source": "hand-authored (kept as sanity/smoke sample)",
            }
        ]
    data = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    corpora: list[dict[str, Any]] = []
    for c in data["corpora"]:
        corpora.append(
            {
                "name": c["name"],
                "chunks": c["chunks"],
                "ground_truth": c["ground_truth"],
                "source": {
                    "wikipedia_revision": c.get("wikipedia_revision"),
                    "wikipedia_url": c.get("wikipedia_url"),
                    "actor_qid": c.get("actor_qid"),
                    "verified_films": len(c.get("verified_films", [])),
                },
            }
        )
    return corpora


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        default=None,
        help=(
            "Path to a public corpus JSON built by "
            "scripts/build_public_actor_corpus.py. If omitted, the legacy "
            "hand-authored 3-chunk Tom Hanks corpus is used (smoke only)."
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help=(
            "Number of runs per (corpus, strategy) for variance estimation. "
            "Default 3. Set to 1 for a quick single-run smoke."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=("Where to archive the full run JSON. Defaults to .workflow/deepseek_live_run.json (kept out of git)."),
    )
    args = parser.parse_args()

    _load_env_local()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY is not set (checked .env.local + environment).")
        return 2

    corpora = _load_corpora(args.corpus)
    print(f"Loaded {len(corpora)} corpora (runs per strategy per corpus: {args.runs})")
    evaluator = GraphExtractionEvaluator(GraphSchemaIndex(SCHEMA))

    all_runs: list[SingleRunResult] = []
    for corpus in corpora:
        for strategy in ("baseline", "enhanced"):
            for run_i in range(args.runs):
                print(
                    f"  {corpus['name']} / {strategy} / run{run_i + 1}/{args.runs} ...",
                    flush=True,
                )
                r = _run_strategy_on_corpus(
                    strategy=strategy,
                    api_key=api_key,
                    schema=SCHEMA,
                    chunks=corpus["chunks"],
                    expected=corpus["ground_truth"],
                    corpus_name=corpus["name"],
                    run_index=run_i,
                    evaluator=evaluator,
                )
                all_runs.append(r)
                print(
                    f"    F1={r.overall_f1:.3f}  vF1={r.vertex_f1:.3f}  eF1={r.edge_f1:.3f}  "
                    f"latency={r.total_latency_ms / 1000:.2f}s  "
                    f"tokens={r.tokens_total}  cost=${r.cost_usd_estimate:.6f}"
                )

    # ----- per-(corpus, strategy) aggregation -----
    by_key: dict[tuple[str, str], list[SingleRunResult]] = {}
    for r in all_runs:
        by_key.setdefault((r.corpus_name, r.strategy), []).append(r)

    per_pair_agg: dict[str, dict[str, Any]] = {}
    for (corpus_name, strategy), runs in by_key.items():
        per_pair_agg[f"{corpus_name}|{strategy}"] = _aggregate(runs)

    # ----- per-strategy aggregation across all runs -----
    per_strategy: dict[str, dict[str, Any]] = {}
    for strategy in ("baseline", "enhanced"):
        strategy_runs = [r for r in all_runs if r.strategy == strategy]
        per_strategy[strategy] = _aggregate(strategy_runs)

    baseline_f1 = per_strategy["baseline"]["overall_f1"]["mean"]
    enhanced_f1 = per_strategy["enhanced"]["overall_f1"]["mean"]
    f1_absolute_delta = enhanced_f1 - baseline_f1
    f1_relative_pct = (f1_absolute_delta / baseline_f1 * 100.0) if baseline_f1 > 0 else float("nan")

    # ----- summary table -----
    print("\n=== Summary (mean +/- std across runs and corpora) ===")
    print(
        f"  baseline: F1={baseline_f1:.3f} +/- {per_strategy['baseline']['overall_f1']['std']:.3f}  "
        f"latency={per_strategy['baseline']['latency_ms']['mean'] / 1000:.2f}s  "
        f"cost=${per_strategy['baseline']['cost_usd_estimate']['mean']:.6f}"
    )
    print(
        f"  enhanced: F1={enhanced_f1:.3f} +/- {per_strategy['enhanced']['overall_f1']['std']:.3f}  "
        f"latency={per_strategy['enhanced']['latency_ms']['mean'] / 1000:.2f}s  "
        f"cost=${per_strategy['enhanced']['cost_usd_estimate']['mean']:.6f}"
    )
    if not math.isnan(f1_relative_pct):
        print(f"  delta F1: {f1_absolute_delta:+.3f} absolute ({f1_relative_pct:+.1f}% relative)")

    # ----- persist -----
    workflow_dir = _REPO_ROOT / ".workflow"
    workflow_dir.mkdir(exist_ok=True)
    out_path = Path(args.output) if args.output else workflow_dir / "deepseek_live_run.json"
    payload = {
        "model": DEEPSEEK_MODEL_LITELLM,
        "pricing": {
            "input_usd_per_m": DEEPSEEK_INPUT_USD_PER_M,
            "output_usd_per_m": DEEPSEEK_OUTPUT_USD_PER_M,
        },
        "corpus_source": args.corpus if args.corpus else "legacy hand-authored (--corpus flag not set)",
        "runs_per_strategy_per_corpus": args.runs,
        "schema": SCHEMA,
        "corpora": [
            {
                "name": c["name"],
                "chunks": c["chunks"],
                "ground_truth": c["ground_truth"],
                "source": c.get("source"),
            }
            for c in corpora
        ],
        "runs": [asdict(r) for r in all_runs],
        "per_corpus_strategy_aggregation": per_pair_agg,
        "per_strategy_aggregation": per_strategy,
        "delta": {
            "f1_absolute": f1_absolute_delta,
            "f1_relative_percent": f1_relative_pct,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull run archived to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
