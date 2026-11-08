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

"""Build evaluation inputs from plain Python values.

The evaluators read content-addressed artifacts. These helpers keep that contract
while letting a caller start from ordinary answers, document ids and graphs.
"""

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from pydantic import JsonValue

from hugegraph_llm_eval.artifacts.memory import InMemoryArtifactStore
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationInput, EvaluationSubject
from hugegraph_llm_eval.contracts.domain.operation import PortName
from hugegraph_llm_eval.contracts.identity import SchemaRef
from hugegraph_llm_eval.integrations.answer.materializers import ANSWER_COMPARISON_INPUT_SCHEMA
from hugegraph_llm_eval.integrations.graph_extraction.materializers import (
    GRAPH_EXTRACTION_INPUT_SCHEMA,
    GRAPH_REVIEW_INPUT_SCHEMA,
)
from hugegraph_llm_eval.integrations.retrieval.materializers import RETRIEVAL_COMPARISON_INPUT_SCHEMA


def answer_input(
    store: InMemoryArtifactStore,
    *,
    question: str,
    answer: str,
    references: Sequence[str],
    contexts: Sequence[str] = (),
    language: Literal["en", "zh"] = "en",
) -> EvaluationInput:
    """Input for answer lexical, correctness, grounding and noise metrics."""
    return _input(
        store,
        ANSWER_COMPARISON_INPUT_SCHEMA,
        (
            ("answer_candidate", "answer", "candidate", {"text": answer}),
            ("answer_reference", "answer", "reference", {"answers": list(references)}),
            (
                "answer_source",
                "answer",
                "source",
                {"question": question, "contexts": list(contexts), "language": language},
            ),
        ),
    )


def retrieval_input(
    store: InMemoryArtifactStore,
    *,
    candidate_doc_ids: Sequence[str],
    reference_doc_ids: Sequence[str],
    question: str = "",
    candidate_contexts: Sequence[str] = (),
    reference_evidence: Sequence[str] = (),
    reference_answer: str = "",
    reference_entities: Sequence[str] | None = None,
) -> EvaluationInput:
    """Input for ranking, context quality and evidence coverage metrics."""
    return _input(
        store,
        RETRIEVAL_COMPARISON_INPUT_SCHEMA,
        (
            (
                "retrieval_candidate",
                "retrieval",
                "candidate",
                {"doc_ids": list(candidate_doc_ids), "contexts": list(candidate_contexts)},
            ),
            (
                "retrieval_reference",
                "retrieval",
                "reference",
                {
                    "doc_ids": list(reference_doc_ids),
                    "evidence": list(reference_evidence),
                    "answer": reference_answer,
                    **({"entities": list(reference_entities)} if reference_entities is not None else {}),
                },
            ),
            ("query", "retrieval", "query", {"question": question}),
        ),
    )


def graph_review_input(
    store: InMemoryArtifactStore,
    *,
    candidate: Mapping[str, object],
    source_text: str,
    schema: Mapping[str, object],
) -> EvaluationInput:
    """Input for candidate-only graph metrics such as schema validity and faithfulness."""
    return _input(
        store,
        GRAPH_REVIEW_INPUT_SCHEMA,
        (
            ("candidate_graph", "graph", "candidate_graph", dict(candidate)),
            ("graph_schema", "graph", "graph_schema", dict(schema)),
        ),
        text_ports=(("source_text", source_text),),
    )


def graph_extraction_input(
    store: InMemoryArtifactStore,
    *,
    candidate: Mapping[str, object],
    reference: Mapping[str, object],
    source_text: str,
    schema: Mapping[str, object],
) -> EvaluationInput:
    """Input for offline extraction metrics that need candidate, reference and evidence."""
    return _input(
        store,
        GRAPH_EXTRACTION_INPUT_SCHEMA,
        (
            ("candidate_graph", "graph", "candidate_graph", dict(candidate)),
            ("reference_graph", "graph", "reference_graph", dict(reference)),
            ("graph_schema", "graph", "graph_schema", dict(schema)),
        ),
        text_ports=(("source_text", source_text),),
    )


def _input(
    store: InMemoryArtifactStore,
    schema_ref: SchemaRef,
    parts: Sequence[tuple[str, str, str, Mapping[str, object]]],
    *,
    text_ports: Sequence[tuple[str, str]] = (),
) -> EvaluationInput:
    subjects = [
        EvaluationSubject(
            port=PortName(value=port),
            artifact=store.put_json(
                cast(JsonValue, dict(payload)),
                schema_namespace=namespace,
                schema_name=name,
            ),
        )
        for port, namespace, name, payload in parts
    ]
    subjects.extend(
        EvaluationSubject(port=PortName(value=port), artifact=store.put_text(text)) for port, text in text_ports
    )
    return EvaluationInput.create(schema_ref=schema_ref, subjects=tuple(subjects))
