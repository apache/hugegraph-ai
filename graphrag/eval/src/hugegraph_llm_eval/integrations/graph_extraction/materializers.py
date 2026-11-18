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

"""Materialize typed graph inputs from content-addressed Artifact ports."""

import json
from typing import TypeVar

from pydantic import ValidationError

from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef, ArtifactStore
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationInput
from hugegraph_llm_eval.contracts.domain.graph import (
    GraphCandidate,
    GraphExtractionInput,
    GraphReviewInput,
    GraphSchema,
)
from hugegraph_llm_eval.contracts.identity import SchemaRef

ModelT = TypeVar("ModelT", GraphCandidate, GraphSchema)

GRAPH_REVIEW_INPUT_SCHEMA = SchemaRef(namespace="graph", name="candidate_review", version=1)
GRAPH_EXTRACTION_INPUT_SCHEMA = SchemaRef(namespace="graph", name="extraction", version=1)

_REVIEW_PORTS = frozenset({"candidate_graph", "source_text", "graph_schema"})
_EXTRACTION_PORTS = frozenset({"candidate_graph", "reference_graph", "source_text", "graph_schema"})
QUALITY_INPUT_SCHEMAS = frozenset((GRAPH_REVIEW_INPUT_SCHEMA, GRAPH_EXTRACTION_INPUT_SCHEMA))


class GraphMaterializationError(ValueError):
    """An Artifact set cannot satisfy its declared graph input schema."""


class GraphArtifactMaterializer:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self._artifacts = artifacts

    def review(self, evaluation_input: EvaluationInput) -> GraphReviewInput:
        subjects = self._subjects(evaluation_input, GRAPH_REVIEW_INPUT_SCHEMA, _REVIEW_PORTS)
        return GraphReviewInput(
            candidate=self._json_model(subjects["candidate_graph"], GraphCandidate),
            source_text=self._text(subjects["source_text"]),
            graph_schema=self._json_model(subjects["graph_schema"], GraphSchema),
        )

    def extraction(self, evaluation_input: EvaluationInput) -> GraphExtractionInput:
        """Materialize the complete offline extraction input without metric-specific fallbacks."""
        subjects = self._subjects(evaluation_input, GRAPH_EXTRACTION_INPUT_SCHEMA, _EXTRACTION_PORTS)
        return GraphExtractionInput(
            candidate=self._json_model(subjects["candidate_graph"], GraphCandidate),
            reference=self._json_model(subjects["reference_graph"], GraphCandidate),
            source_text=self._text(subjects["source_text"]),
            graph_schema=self._json_model(subjects["graph_schema"], GraphSchema),
        )

    def quality(
        self,
        evaluation_input: EvaluationInput,
        *,
        expected_schema: SchemaRef,
    ) -> GraphReviewInput | GraphExtractionInput:
        """Materialize one of the two contracts supported by graph quality metrics."""
        if expected_schema not in QUALITY_INPUT_SCHEMAS:
            raise GraphMaterializationError("graph quality input schema must be candidate_review or extraction")
        if evaluation_input.schema_ref != expected_schema:
            raise GraphMaterializationError(f"graph input schema must be {expected_schema}")
        if expected_schema == GRAPH_REVIEW_INPUT_SCHEMA:
            return self.review(evaluation_input)
        return self.extraction(evaluation_input)

    @staticmethod
    def _subjects(
        evaluation_input: EvaluationInput,
        expected_schema: SchemaRef,
        expected_ports: frozenset[str],
    ) -> dict[str, ArtifactRef]:
        if evaluation_input.schema_ref != expected_schema:
            msg = f"graph input schema must be {expected_schema}"
            raise GraphMaterializationError(msg)
        subjects = {subject.port.value: subject.artifact for subject in evaluation_input.subjects}
        actual_ports = frozenset(subjects)
        if actual_ports != expected_ports:
            missing = sorted(expected_ports - actual_ports)
            unexpected = sorted(actual_ports - expected_ports)
            msg = f"graph input has missing required ports {missing} and unexpected ports {unexpected}"
            raise GraphMaterializationError(msg)
        return subjects

    def _json_model(
        self,
        artifact: ArtifactRef,
        model_type: type[ModelT],
    ) -> ModelT:
        if artifact.descriptor.media_type != "application/json":
            msg = "graph structured Artifact must use application/json"
            raise GraphMaterializationError(msg)
        try:
            payload = json.loads(self._artifacts.read(artifact))
            return model_type.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            msg = "graph Artifact must contain valid JSON"
            raise GraphMaterializationError(msg) from exc
        except ValidationError as exc:
            msg = f"graph Artifact violates {model_type.__name__}"
            raise GraphMaterializationError(msg) from exc

    def _text(self, artifact: ArtifactRef) -> str:
        if artifact.descriptor.media_type != "text/plain":
            msg = "source text Artifact must use text/plain"
            raise GraphMaterializationError(msg)
        try:
            return self._artifacts.read(artifact).decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = "source text Artifact must contain UTF-8"
            raise GraphMaterializationError(msg) from exc
