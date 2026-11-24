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

"""Shared fixtures: in-memory artifacts and neutral graph inputs."""

from fakes import NOW
from pydantic import JsonValue

from hugegraph_llm_eval.artifacts.memory import InMemoryArtifactStore
from hugegraph_llm_eval.contracts.digests import canonical_json_bytes
from hugegraph_llm_eval.contracts.domain.artifacts import (
    ArtifactDescriptor,
    ArtifactRef,
    ArtifactRetention,
    ArtifactSensitivity,
)
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationInput, EvaluationSubject
from hugegraph_llm_eval.contracts.domain.operation import PortName
from hugegraph_llm_eval.contracts.identity import SchemaRef
from hugegraph_llm_eval.integrations.graph_extraction.materializers import (
    GRAPH_EXTRACTION_INPUT_SCHEMA,
    GRAPH_REVIEW_INPUT_SCHEMA,
)


def make_store() -> InMemoryArtifactStore:
    return InMemoryArtifactStore(clock=lambda: NOW)


def put_json(store: InMemoryArtifactStore, name: str, value: JsonValue) -> ArtifactRef:
    return store.put(
        canonical_json_bytes(value),
        ArtifactDescriptor(
            media_type="application/json",
            schema_ref=SchemaRef(namespace="graph", name=name, version=1),
            sensitivity=ArtifactSensitivity.INTERNAL,
            retention=ArtifactRetention.STANDARD,
        ),
    )


def put_text(store: InMemoryArtifactStore, value: str) -> ArtifactRef:
    return store.put(
        value.encode(),
        ArtifactDescriptor(
            media_type="text/plain",
            schema_ref=SchemaRef(namespace="document", name="source_text", version=1),
            sensitivity=ArtifactSensitivity.INTERNAL,
            retention=ArtifactRetention.STANDARD,
        ),
    )


def graph_candidate() -> dict[str, object]:
    return {
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


def graph_schema() -> dict[str, object]:
    return {
        "vertexlabels": [
            {"name": "Person", "primary_keys": ["name"]},
            {"name": "Skill", "primary_keys": []},
        ],
        "edgelabels": [
            {"name": "HAS_SKILL", "source_label": "Person", "target_label": "Skill"},
        ],
    }


def graph_input(
    store: InMemoryArtifactStore,
    *,
    candidate_payload: dict[str, object] | None = None,
) -> EvaluationInput:
    candidate = put_json(store, "draft", graph_candidate() if candidate_payload is None else candidate_payload)
    subjects = [
        EvaluationSubject(port=PortName(value="candidate_graph"), artifact=candidate),
        EvaluationSubject(port=PortName(value="graph_schema"), artifact=put_json(store, "schema", graph_schema())),
    ]
    subjects.append(
        EvaluationSubject(port=PortName(value="source_text"), artifact=put_text(store, "Alice knows GraphQL."))
    )
    return EvaluationInput.create(
        schema_ref=GRAPH_REVIEW_INPUT_SCHEMA,
        subjects=tuple(subjects),
    )


def extraction_input(
    store: InMemoryArtifactStore,
    *,
    candidate_payload: dict[str, object] | None = None,
    reference_payload: dict[str, object] | None = None,
) -> EvaluationInput:
    candidate = put_json(store, "candidate", graph_candidate() if candidate_payload is None else candidate_payload)
    reference = candidate if reference_payload is None else put_json(store, "reference", reference_payload)
    return EvaluationInput.create(
        schema_ref=GRAPH_EXTRACTION_INPUT_SCHEMA,
        subjects=(
            EvaluationSubject(port=PortName(value="candidate_graph"), artifact=candidate),
            EvaluationSubject(port=PortName(value="reference_graph"), artifact=reference),
            EvaluationSubject(port=PortName(value="source_text"), artifact=put_text(store, "Alice knows GraphQL.")),
            EvaluationSubject(port=PortName(value="graph_schema"), artifact=put_json(store, "schema", graph_schema())),
        ),
    )
