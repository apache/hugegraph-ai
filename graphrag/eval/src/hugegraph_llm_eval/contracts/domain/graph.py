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

"""Published graph artifacts and typed inputs shared by graph evaluators."""

from pydantic import AliasChoices, Field, JsonValue, model_validator

from hugegraph_llm_eval.contracts.base import VersionedModel


class GraphVertex(VersionedModel):
    """Canonical graph vertex artifact value."""

    label: str = Field(min_length=1, max_length=127)
    name: str = Field(min_length=1, max_length=2_000)
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    source_snippet: str | None = Field(default=None, max_length=100_000)


class GraphEdge(VersionedModel):
    """Canonical graph edge artifact value."""

    label: str = Field(min_length=1, max_length=127)
    out_v: str = Field(
        min_length=1,
        max_length=2_000,
        validation_alias=AliasChoices("outV", "out_v"),
        serialization_alias="outV",
    )
    in_v: str = Field(
        min_length=1,
        max_length=2_000,
        validation_alias=AliasChoices("inV", "in_v"),
        serialization_alias="inV",
    )
    out_v_label: str | None = Field(
        default=None,
        max_length=127,
        validation_alias=AliasChoices("outVLabel", "out_v_label"),
        serialization_alias="outVLabel",
    )
    in_v_label: str | None = Field(
        default=None,
        max_length=127,
        validation_alias=AliasChoices("inVLabel", "in_v_label"),
        serialization_alias="inVLabel",
    )
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    source_snippet: str | None = Field(default=None, max_length=100_000)


class GraphCandidate(VersionedModel):
    """Canonical graph artifact, including invalid candidates to be evaluated.

    Schema validity treats this as a complete graph: every edge endpoint must
    identify a vertex in ``vertices``. Explicit endpoint labels disambiguate
    equal names with different types; an omitted label requires a unique type.
    Invalid endpoint references remain representable so evaluators can report
    them as findings instead of rejecting the candidate during construction.
    """

    chunk_id: str = Field(default="", max_length=2_000)
    heading_path: str = Field(default="", max_length=10_000)
    source_section: str = Field(default="", max_length=10_000)
    line_start: int | None = Field(default=None, ge=0)
    line_end: int | None = Field(default=None, ge=0)
    vertices: tuple[GraphVertex, ...] = ()
    edges: tuple[GraphEdge, ...] = ()


class GraphVertexLabel(VersionedModel):
    """Schema definition for one vertex label."""

    name: str = Field(min_length=1, max_length=127)
    primary_keys: tuple[str, ...] = ()


class GraphEdgeLabel(VersionedModel):
    """Schema definition for one edge label."""

    name: str = Field(min_length=1, max_length=127)
    source_label: str = Field(min_length=1, max_length=127)
    target_label: str = Field(min_length=1, max_length=127)


class GraphSchema(VersionedModel):
    """Canonical graph schema artifact value."""

    vertexlabels: tuple[GraphVertexLabel, ...] = ()
    edgelabels: tuple[GraphEdgeLabel, ...] = ()

    @model_validator(mode="after")
    def _validate_unique_labels(self) -> "GraphSchema":
        vertex_names = tuple(item.name.casefold() for item in self.vertexlabels)
        edge_names = tuple(item.name.casefold() for item in self.edgelabels)
        if len(vertex_names) != len(set(vertex_names)) or len(edge_names) != len(set(edge_names)):
            raise ValueError("graph schema labels must be unique ignoring case")
        return self


class GraphReviewInput(VersionedModel):
    """Production evidence boundary where ground truth is structurally absent."""

    candidate: GraphCandidate
    source_text: str = Field(max_length=10_000_000)
    graph_schema: GraphSchema


class GraphExtractionInput(VersionedModel):
    """Complete offline input shared by every graph extraction metric."""

    candidate: GraphCandidate
    reference: GraphCandidate
    source_text: str = Field(max_length=10_000_000)
    graph_schema: GraphSchema
