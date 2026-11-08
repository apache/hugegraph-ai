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

"""Score a graph against its source text with a real model.

OpenAI-compatible endpoint (the default backend):

    pip install "hugegraph-llm-eval[openai]"
    export EVAL_JUDGE_MODEL=<model name>
    export EVAL_JUDGE_API_KEY=<api key>
    # optional for self-hosted or gateway endpoints
    export EVAL_JUDGE_BASE_URL=<base url>

Claude or Codex subscription (needs the logged-in `claude` or `codex` CLI on PATH):

    export EVAL_JUDGE_BACKEND=claude-code   # or: codex
    export EVAL_JUDGE_MODEL=<model name or alias>

Run:

    python examples/real_model.py
"""

import os
import sys

from hugegraph_llm_eval import (
    ClaudeCodeJudge,
    CodexAppServerJudge,
    EvaluationOptions,
    GraphFaithfulnessEvaluator,
    InMemoryArtifactStore,
    JudgeContent,
    evaluate,
    graph_review_input,
    openai_judge,
)
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer
from hugegraph_llm_eval.prompt import graph_judge_prompt, graph_judge_rubric
from hugegraph_llm_eval.utils.clock import utc_now

SOURCE_TEXT = "The auth service issues OAuth 2.0 tokens. Tokens rotate every 24 hours."

SCHEMA = {
    "vertexlabels": [
        {"name": "Service", "primary_keys": ["name"]},
        {"name": "Specification", "primary_keys": ["name"]},
    ],
    "edgelabels": [
        {"name": "HAS_SPEC", "source_label": "Service", "target_label": "Specification"},
    ],
}

CANDIDATE = {
    "chunk_id": "example-1",
    "vertices": [
        {"label": "Service", "name": "auth", "properties": {"name": "auth"}},
        {"label": "Specification", "name": "rotation:24h", "properties": {}},
        {"label": "Specification", "name": "rotation:7d", "properties": {}},
    ],
    "edges": [
        {
            "label": "HAS_SPEC",
            "outVLabel": "Service",
            "outV": "auth",
            "inVLabel": "Specification",
            "inV": "rotation:24h",
            "properties": {},
        },
        {
            "label": "HAS_SPEC",
            "outVLabel": "Service",
            "outV": "auth",
            "inVLabel": "Specification",
            "inV": "rotation:7d",
            "properties": {},
        },
    ],
}


def build_judge():
    backend = os.environ.get("EVAL_JUDGE_BACKEND", "openai")
    model = os.environ.get("EVAL_JUDGE_MODEL")
    if backend == "claude-code" and model:
        return ClaudeCodeJudge(model=model)
    if backend == "codex" and model:
        return CodexAppServerJudge(model=model)
    api_key = os.environ.get("EVAL_JUDGE_API_KEY")
    if backend == "openai" and model and api_key:
        return openai_judge(
            model=model,
            api_key=api_key,
            base_url=os.environ.get("EVAL_JUDGE_BASE_URL"),
            provider=os.environ.get("EVAL_JUDGE_PROVIDER", "openai"),
        )
    if backend not in ("openai", "claude-code", "codex"):
        print(f"Unknown EVAL_JUDGE_BACKEND {backend!r}; use openai, claude-code or codex.", file=sys.stderr)
    elif backend == "openai":
        print("Set EVAL_JUDGE_MODEL and EVAL_JUDGE_API_KEY to run this example.", file=sys.stderr)
        print("Install the transport with: pip install 'hugegraph-llm-eval[openai]'", file=sys.stderr)
    else:
        print("Set EVAL_JUDGE_MODEL to run this example.", file=sys.stderr)
    return None


def main() -> int:
    judge = build_judge()
    if judge is None:
        return 2
    try:
        return run(judge)
    finally:
        close = getattr(judge, "close", None)
        if close is not None:
            close()


def run(judge) -> int:
    store = InMemoryArtifactStore()
    evaluation_input = graph_review_input(
        store,
        candidate=CANDIDATE,
        source_text=SOURCE_TEXT,
        schema=SCHEMA,
    )
    evaluator = GraphFaithfulnessEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=JudgeContent(
            component=ComponentRef(namespace="graph", name="faithfulness_prompt", revision="v1"),
            text=graph_judge_prompt("faithfulness", "en"),
        ),
        rubric=JudgeContent(
            component=ComponentRef(namespace="graph", name="faithfulness_rubric", revision="v1"),
            text=graph_judge_rubric("faithfulness", "en"),
        ),
        clock=utc_now,
    )

    result = evaluate(
        [evaluator],
        evaluation_input,
        options=EvaluationOptions(request_key="example-faithfulness", max_attempts=2),
    )
    record = result.records[0]
    print(f"run: {result.status}")
    print(f"record: {record.status}")
    for measurement in record.measurements:
        print(f"  {measurement.name} = {measurement.value}")
    for finding in record.findings:
        print(f"  [{finding.severity}] {finding.code}: {finding.message}")
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
