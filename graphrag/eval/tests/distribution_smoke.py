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

"""Run against an installed wheel or sdist, never against the source tree.

    /path/to/clean-venv/bin/python -B /path/to/distribution_smoke.py

No checkout path is added to ``sys.path`` and only base dependencies may exist.
"""

import importlib.metadata
import os
import sys

FORBIDDEN_ROOTS = {
    "hugegraph_llm",
    "hugegraph_llm_sdk",
    "openai",
    "networkx",
    "rouge_score",
    "litellm",
    "ollama",
    "jieba",
    "nltk",
    "tenacity",
    "tiktoken",
}

REQUIRED_EXPORTS = (
    "EvaluationEngine",
    "EvaluationOptions",
    "InMemoryArtifactStore",
    "MRREvaluator",
    "RecallAtKEvaluator",
    "evaluate",
    "evaluate_many",
    "retrieval_input",
)


class DependencyBoundary:
    """Reject any import of an application or optional dependency."""

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.partition(".")[0]
        if root in FORBIDDEN_ROOTS:
            raise AssertionError(f"base install attempted to import {fullname}")
        return None


def main() -> None:
    sys.meta_path.insert(0, DependencyBoundary())

    import hugegraph_llm_eval
    from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer
    from hugegraph_llm_eval.utils.clock import utc_now

    location = os.path.realpath(hugegraph_llm_eval.__file__)
    if "site-packages" not in location:
        raise AssertionError(f"imported the source tree instead of the installed package: {location}")

    installed = importlib.metadata.version("hugegraph-llm-eval")
    if hugegraph_llm_eval.__version__ != installed:
        raise AssertionError(f"__version__ {hugegraph_llm_eval.__version__} != installed {installed}")

    missing = [name for name in REQUIRED_EXPORTS if not hasattr(hugegraph_llm_eval, name)]
    if missing:
        raise AssertionError(f"missing public entry points: {missing}")

    store = hugegraph_llm_eval.InMemoryArtifactStore()
    evaluation_input = hugegraph_llm_eval.retrieval_input(
        store,
        candidate_doc_ids=["doc-b", "doc-a"],
        reference_doc_ids=["doc-a"],
        question="Which document is relevant?",
    )
    result = hugegraph_llm_eval.evaluate(
        [hugegraph_llm_eval.RecallAtKEvaluator(RetrievalArtifactMaterializer(store), k_values=(1,), clock=utc_now)],
        evaluation_input,
        options=hugegraph_llm_eval.EvaluationOptions(request_key="smoke"),
    )
    if result.status.value != "completed":
        raise AssertionError(f"smoke evaluation finished as {result.status}")


if __name__ == "__main__":
    main()
