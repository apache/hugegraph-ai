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

"""Score retrieval ranking with the installed SDK and no application runtime."""

from hugegraph_llm_eval import (
    EvaluationContext,
    EvaluationInput,
    EvaluationOptions,
    EvaluationSubject,
    HitAtKEvaluator,
    InMemoryArtifactStore,
    MRREvaluator,
    RecallAtKEvaluator,
)
from hugegraph_llm_eval.contracts.domain.operation import PortName
from hugegraph_llm_eval.contracts.identity import EvaluationRunId
from hugegraph_llm_eval.integrations.retrieval.materializers import (
    RETRIEVAL_COMPARISON_INPUT_SCHEMA,
    RetrievalArtifactMaterializer,
)
from hugegraph_llm_eval.utils.clock import utc_now


def main() -> None:
    store = InMemoryArtifactStore()
    candidate = store.put_json(
        {"doc_ids": ["doc-b", "doc-a", "doc-c"]},
        schema_namespace="retrieval",
        schema_name="candidate",
    )
    reference = store.put_json(
        {"doc_ids": ["doc-a", "doc-b"]},
        schema_namespace="retrieval",
        schema_name="reference",
    )
    query = store.put_json(
        {"question": "Which service rotates its tokens?"},
        schema_namespace="retrieval",
        schema_name="query",
    )
    evaluation_input = EvaluationInput.create(
        schema_ref=RETRIEVAL_COMPARISON_INPUT_SCHEMA,
        subjects=(
            EvaluationSubject(port=PortName(value="retrieval_candidate"), artifact=candidate),
            EvaluationSubject(port=PortName(value="retrieval_reference"), artifact=reference),
            EvaluationSubject(port=PortName(value="query"), artifact=query),
        ),
    )

    options = EvaluationOptions(request_key="example-retrieval", max_concurrency=3)
    context = EvaluationContext(
        run_id=EvaluationRunId.new(),
        request_key=options.request_key,
        deadline=options.deadline,
        cancellation=options.cancellation,
        max_concurrency=options.max_concurrency,
    )
    materializer = RetrievalArtifactMaterializer(store)
    evaluators = (
        RecallAtKEvaluator(materializer, k_values=(1, 3), clock=utc_now),
        HitAtKEvaluator(materializer, k_values=(1, 3), clock=utc_now),
        MRREvaluator(materializer, clock=utc_now),
    )
    for evaluator in evaluators:
        draft = evaluator.evaluate(evaluation_input, context)
        measurements = ", ".join(f"{item.name}={item.value}" for item in draft.measurements)
        print(f"{draft.invocation_key}: {measurements}")


if __name__ == "__main__":
    main()
