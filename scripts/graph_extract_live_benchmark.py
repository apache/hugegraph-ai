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

import json
import os
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


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens * DEEPSEEK_INPUT_USD_PER_M / 1_000_000.0
        + completion_tokens * DEEPSEEK_OUTPUT_USD_PER_M / 1_000_000.0
    )


def _run_strategy(strategy: str, api_key: str) -> StrategyRunMetrics:
    llm = TrackedDeepSeekLLM(api_key=api_key)
    extractor = PropertyGraphExtract(
        llm=llm,
        example_prompt=EXTRACT_PROMPT_HEADER,
        extract_strategy=strategy,
    )
    context = {"schema": SCHEMA, "chunks": list(CORPUS)}
    start = time.perf_counter()
    result = extractor.run(context)
    total_latency_ms = (time.perf_counter() - start) * 1000.0

    prompt_tokens_total = sum(c.prompt_tokens for c in llm.calls)
    completion_tokens_total = sum(c.completion_tokens for c in llm.calls)
    tokens_total = sum(c.total_tokens for c in llm.calls)

    return StrategyRunMetrics(
        strategy=strategy,
        predicted={"vertices": result.get("vertices", []), "edges": result.get("edges", [])},
        total_latency_ms=total_latency_ms,
        call_count=int(result.get("call_count", 0) or len(llm.calls)),
        prompt_tokens_total=prompt_tokens_total,
        completion_tokens_total=completion_tokens_total,
        tokens_total=tokens_total,
        cost_usd_estimate=_estimate_cost(prompt_tokens_total, completion_tokens_total),
        calls=[asdict(c) for c in llm.calls],
    )


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


def _format_row(m: StrategyRunMetrics, f1: float, match_rate: float) -> str:
    return (
        f"| {m.strategy:<9} | {f1:.2f} | {match_rate:.2f} | "
        f"{m.call_count} | {m.total_latency_ms / 1000:.2f}s | "
        f"{m.prompt_tokens_total} | {m.completion_tokens_total} | "
        f"${m.cost_usd_estimate:.6f} |"
    )


def main() -> int:
    _load_env_local()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY is not set (checked .env.local + environment).")
        return 2

    print("Running baseline strategy against DeepSeek Chat ...")
    baseline_metrics = _run_strategy("baseline", api_key)
    print("Running enhanced strategy against DeepSeek Chat ...")
    enhanced_metrics = _run_strategy("enhanced", api_key)

    evaluator = GraphExtractionEvaluator(GraphSchemaIndex(SCHEMA))
    baseline_eval = evaluator.evaluate(baseline_metrics.predicted, GROUND_TRUTH)
    enhanced_eval = evaluator.evaluate(enhanced_metrics.predicted, GROUND_TRUTH)

    header = "| strategy  |   F1 | match% | calls | latency | in_tok | out_tok |         cost |"
    separator = "|---|---:|---:|---:|---:|---:|---:|---:|"
    print("\n" + header)
    print(separator)
    print(
        _format_row(
            baseline_metrics, baseline_eval.overall_f1, baseline_eval.property_metrics.property_exact_match_rate
        )
    )
    print(
        _format_row(
            enhanced_metrics, enhanced_eval.overall_f1, enhanced_eval.property_metrics.property_exact_match_rate
        )
    )

    workflow_dir = _REPO_ROOT / ".workflow"
    workflow_dir.mkdir(exist_ok=True)
    out_path = workflow_dir / "deepseek_live_run.json"
    payload = {
        "model": DEEPSEEK_MODEL_LITELLM,
        "pricing": {
            "input_usd_per_m": DEEPSEEK_INPUT_USD_PER_M,
            "output_usd_per_m": DEEPSEEK_OUTPUT_USD_PER_M,
        },
        "schema": SCHEMA,
        "corpus": CORPUS,
        "ground_truth": GROUND_TRUTH,
        "baseline": {
            "metrics": asdict(baseline_metrics),
            "evaluation": baseline_eval.to_dict(),
        },
        "enhanced": {
            "metrics": asdict(enhanced_metrics),
            "evaluation": enhanced_eval.to_dict(),
        },
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull run archived to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
