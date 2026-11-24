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

"""Sample builders hide artifact plumbing without weakening the typed inputs."""

from hugegraph_llm_eval import (
    answer_input,
    graph_extraction_input,
    graph_review_input,
    retrieval_input,
)
from hugegraph_llm_eval.artifacts.memory import InMemoryArtifactStore
from hugegraph_llm_eval.integrations.answer.materializers import AnswerArtifactMaterializer
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer

CANDIDATE = {
    "chunk_id": "chunk-1",
    "vertices": [
        {"label": "Person", "name": "Alice", "properties": {"name": "Alice"}},
        {"label": "Skill", "name": "GraphQL", "properties": {}},
    ],
    "edges": [
        {
            "label": "HAS_SKILL",
            "outVLabel": "Person",
            "outV": "Alice",
            "inVLabel": "Skill",
            "inV": "GraphQL",
            "properties": {},
        },
    ],
}

SCHEMA = {
    "vertexlabels": [
        {"name": "Person", "primary_keys": ["name"]},
        {"name": "Skill", "primary_keys": []},
    ],
    "edgelabels": [{"name": "HAS_SKILL", "source_label": "Person", "target_label": "Skill"}],
}


def _store() -> InMemoryArtifactStore:
    return InMemoryArtifactStore()


def test_answer_input_materializes() -> None:
    store = _store()
    evaluation_input = answer_input(
        store,
        question="Which service rotates tokens?",
        answer="The auth service.",
        references=("The auth service rotates tokens.",),
        contexts=("The auth service rotates tokens every 24 hours.",),
    )

    materialized = AnswerArtifactMaterializer(store).comparison(evaluation_input)

    assert materialized.candidate.text == "The auth service."
    assert materialized.reference.answers == ("The auth service rotates tokens.",)
    assert materialized.source.question == "Which service rotates tokens?"
    assert materialized.source.contexts == ("The auth service rotates tokens every 24 hours.",)


def test_retrieval_input_materializes() -> None:
    store = _store()
    evaluation_input = retrieval_input(
        store,
        candidate_doc_ids=("doc-b", "doc-a"),
        reference_doc_ids=("doc-a",),
        question="Which service rotates tokens?",
        candidate_contexts=("b", "a"),
    )

    materialized = RetrievalArtifactMaterializer(store).comparison(evaluation_input)

    assert materialized.candidate.doc_ids == ("doc-b", "doc-a")
    assert materialized.reference.doc_ids == ("doc-a",)
    assert materialized.query.question == "Which service rotates tokens?"


def test_graph_review_input_materializes() -> None:
    store = _store()
    evaluation_input = graph_review_input(
        store,
        candidate=CANDIDATE,
        source_text="Alice knows GraphQL.",
        schema=SCHEMA,
    )

    materialized = GraphArtifactMaterializer(store).review(evaluation_input)

    assert materialized.candidate.vertices[0].label == "Person"
    assert materialized.source_text == "Alice knows GraphQL."
    assert materialized.graph_schema.vertexlabels[0].name == "Person"


def test_graph_extraction_input_materializes() -> None:
    store = _store()
    evaluation_input = graph_extraction_input(
        store,
        candidate=CANDIDATE,
        reference=CANDIDATE,
        source_text="Alice knows GraphQL.",
        schema=SCHEMA,
    )

    materialized = GraphArtifactMaterializer(store).extraction(evaluation_input)

    assert materialized.candidate == materialized.reference
    assert materialized.source_text == "Alice knows GraphQL."
