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

"""Candidate-only graph schema conformance with item-level violations."""

from collections.abc import Callable
from datetime import datetime

from hugegraph_llm_eval.contracts.digests import canonical_digest, canonical_json_bytes
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluatorDescriptor,
    EvidenceLink,
    Finding,
    FindingSeverity,
    Measurement,
    MeasurementDirection,
)
from hugegraph_llm_eval.contracts.domain.graph import (
    GraphEdge,
    GraphEdgeLabel,
    GraphExtractionInput,
    GraphReviewInput,
    GraphVertex,
    GraphVertexLabel,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.contracts.identity import EvaluatorRef, SchemaRef
from hugegraph_llm_eval.integrations.graph_extraction.materializers import (
    GRAPH_EXTRACTION_INPUT_SCHEMA,
    GRAPH_REVIEW_INPUT_SCHEMA,
    QUALITY_INPUT_SCHEMAS,
    GraphArtifactMaterializer,
    GraphMaterializationError,
)
from hugegraph_llm_eval.utils.text_preview import text_preview

SCHEMA_VALIDITY_REF = EvaluatorRef(namespace="graph", name="schema_validity", revision="v1")
EXTRACTION_SCHEMA_VALIDITY_REF = EvaluatorRef(namespace="graph", name="schema_validity", revision="v2")


class SchemaValidityEvaluator:
    input_type = EvaluationInput

    def __init__(
        self,
        materializer: GraphArtifactMaterializer,
        *,
        clock: Callable[[], datetime],
        input_schema: SchemaRef = GRAPH_REVIEW_INPUT_SCHEMA,
    ) -> None:
        if input_schema not in QUALITY_INPUT_SCHEMAS:
            raise ValueError("graph quality input schema must be candidate_review or extraction")
        self._materializer = materializer
        self._clock = clock
        self._input_schema = input_schema
        self.descriptor = EvaluatorDescriptor(
            evaluator=_evaluator_ref(input_schema),
            implementation_digest=canonical_digest(
                {
                    "algorithm": "graph-schema-validity",
                    "version": 4,
                    "input_schema": input_schema.model_dump(mode="json"),
                }
            ),
            input_schema=input_schema,
            output_schema=SchemaRef(namespace="graph", name="schema_validity_record", version=1),
        )

    @property
    def invocation_key(self) -> str:
        return "schema_validity"

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        try:
            materialized = self._materialize(evaluation_input)
        except GraphMaterializationError as exc:
            return self._invalid_input(str(exc))
        findings, counts = _validate_schema(materialized, evaluation_input)
        vertex_count, valid_types, filled_properties, edge_count, illegal_edges = counts
        measurements = (
            _measurement("schema_validity", float(not findings), MeasurementDirection.HIGHER_IS_BETTER),
            _measurement(
                "type_constraint_pass", _ratio(valid_types, vertex_count), MeasurementDirection.HIGHER_IS_BETTER
            ),
            _measurement(
                "required_property_fill",
                _ratio(filled_properties, vertex_count),
                MeasurementDirection.HIGHER_IS_BETTER,
            ),
            _measurement("illegal_edge_rate", _ratio(illegal_edges, edge_count), MeasurementDirection.LOWER_IS_BETTER),
        )
        reason = "candidate graph conforms to the declared schema"
        if findings:
            reason = f"candidate graph has {len(findings)} schema violation(s)"
        return EvaluationRecordDraft(
            invocation_key="schema_validity",
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.COMPLETED,
            measurements=measurements,
            findings=findings,
            reason=reason,
            attempts=1,
            latency_ms=0,
            created_at=self._clock(),
        )

    def _invalid_input(self, message: str) -> EvaluationRecordDraft:
        failure = FailureDetail(
            category=FailureCategory.INVALID_INPUT,
            code="graph_materialization_failed",
            message=message,
            retryable=False,
        )
        return EvaluationRecordDraft(
            invocation_key="schema_validity",
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.FAILED,
            reason=message,
            attempts=1,
            latency_ms=0,
            failure=failure,
            created_at=self._clock(),
        )

    def _materialize(self, evaluation_input: EvaluationInput) -> GraphReviewInput | GraphExtractionInput:
        """Use the complete offline contract without widening the production review boundary."""
        return self._materializer.quality(evaluation_input, expected_schema=self._input_schema)


def _evaluator_ref(input_schema: SchemaRef) -> EvaluatorRef:
    """Version the full offline contract independently from candidate-only review."""
    return EXTRACTION_SCHEMA_VALIDITY_REF if input_schema == GRAPH_EXTRACTION_INPUT_SCHEMA else SCHEMA_VALIDITY_REF


def _validate_schema(
    materialized: GraphReviewInput | GraphExtractionInput,
    evaluation_input: EvaluationInput,
) -> tuple[tuple[Finding, ...], tuple[int, int, int, int, int]]:
    schema = materialized.graph_schema
    vertices = materialized.candidate.vertices
    edges = materialized.candidate.edges
    vertex_schemas = {item.name.casefold(): item for item in schema.vertexlabels}
    edge_schemas = {item.name.casefold(): item for item in schema.edgelabels}
    labels_by_name: dict[str, set[str]] = {}
    for vertex in vertices:
        labels_by_name.setdefault(vertex.name.casefold(), set()).add(vertex.label.casefold())
    candidate_artifact = next(
        item.artifact for item in evaluation_input.subjects if item.port.value == "candidate_graph"
    )
    findings: list[Finding] = []
    valid_types, filled_properties = _validate_vertices(
        vertices,
        vertex_schemas,
        candidate_artifact,
        findings,
    )
    illegal_edges = _validate_edges(edges, edge_schemas, labels_by_name, candidate_artifact, findings)
    return tuple(findings), (len(vertices), valid_types, filled_properties, len(edges), illegal_edges)


def _validate_vertices(
    vertices: tuple[GraphVertex, ...],
    vertex_schemas: dict[str, GraphVertexLabel],
    artifact: ArtifactRef,
    findings: list[Finding],
) -> tuple[int, int]:
    valid_types = 0
    filled_properties = 0
    primary_key_owners: dict[tuple[str, bytes], int] = {}
    for index, vertex in enumerate(vertices):
        declared = vertex_schemas.get(vertex.label.casefold())
        if declared is None:
            findings.append(
                _finding(
                    "schema.unknown_vertex_label",
                    f"unknown vertex label {vertex.label!r}",
                    artifact,
                    f"vertices[{index}]",
                )
            )
            continue
        valid_types += 1
        missing = tuple(
            key
            for key in declared.primary_keys
            if vertex.properties.get(key) is None or not str(vertex.properties[key]).strip()
        )
        if missing:
            message = f"vertex {vertex.name!r} is missing required properties: {', '.join(missing)}"
            findings.append(_finding("schema.missing_required_property", message, artifact, f"vertices[{index}]"))
        else:
            filled_properties += 1
            if declared.primary_keys:
                key = (
                    vertex.label.casefold(),
                    canonical_json_bytes([vertex.properties[name] for name in declared.primary_keys]),
                )
                owner = primary_key_owners.setdefault(key, index)
                if owner != index:
                    findings.append(
                        Finding(
                            code="schema.duplicate_primary_key",
                            severity=FindingSeverity.ERROR,
                            message=f"vertices[{index}] and vertices[{owner}] have the same primary key for this label",
                            evidence=(
                                EvidenceLink(artifact=artifact, locator=f"vertices[{index}]"),
                                EvidenceLink(artifact=artifact, locator=f"vertices[{owner}]"),
                            ),
                        )
                    )
    return valid_types, filled_properties


def _validate_edges(
    edges: tuple[GraphEdge, ...],
    edge_schemas: dict[str, GraphEdgeLabel],
    labels_by_name: dict[str, set[str]],
    artifact: ArtifactRef,
    findings: list[Finding],
) -> int:
    illegal = 0
    for index, edge in enumerate(edges):
        declared = edge_schemas.get(edge.label.casefold())
        actual_source = _endpoint_label(edge.out_v, edge.out_v_label, labels_by_name)
        actual_target = _endpoint_label(edge.in_v, edge.in_v_label, labels_by_name)
        valid = declared is not None
        if declared is not None:
            valid = (
                actual_source == declared.source_label.casefold() and actual_target == declared.target_label.casefold()
            )
        if valid:
            continue
        illegal += 1
        message = f"edge {edge.label!r} has an unknown label or missing, ambiguous, or incompatible endpoints"
        findings.append(_finding("schema.illegal_edge", message, artifact, f"edges[{index}]"))
    return illegal


def _endpoint_label(name: str, label: str | None, labels_by_name: dict[str, set[str]]) -> str | None:
    """Resolve a real vertex type, requiring a label to disambiguate names."""
    labels = labels_by_name.get(name.casefold(), set())
    if label is not None:
        normalized = label.casefold()
        return normalized if normalized in labels else None
    return next(iter(labels)) if len(labels) == 1 else None


def _finding(code: str, message: str, artifact: ArtifactRef, locator: str) -> Finding:
    return Finding(
        code=code,
        severity=FindingSeverity.ERROR,
        message=text_preview(message, 4_000),
        evidence=(EvidenceLink(artifact=artifact, locator=locator),),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _measurement(name: str, value: float, direction: MeasurementDirection) -> Measurement:
    return Measurement(name=name, value=value, unit="ratio", direction=direction)
