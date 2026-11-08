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

"""Materialize typed retrieval inputs from named Artifact ports."""

from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactStore
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationInput
from hugegraph_llm_eval.contracts.identity import SchemaRef
from hugegraph_llm_eval.integrations.artifact_inputs import ArtifactInputError, ArtifactInputReader
from hugegraph_llm_eval.integrations.retrieval.schemas import (
    RetrievalCandidate,
    RetrievalComparisonInput,
    RetrievalQuery,
    RetrievalReference,
)

RETRIEVAL_COMPARISON_INPUT_SCHEMA = SchemaRef(namespace="retrieval", name="comparison_input", version=1)
RETRIEVAL_CANDIDATE_SCHEMA = SchemaRef(namespace="retrieval", name="candidate", version=1)
RETRIEVAL_REFERENCE_SCHEMA = SchemaRef(namespace="retrieval", name="reference", version=1)
RETRIEVAL_QUERY_SCHEMA = SchemaRef(namespace="retrieval", name="query", version=1)

_PORTS = frozenset({"retrieval_candidate", "retrieval_reference", "query"})


class RetrievalMaterializationError(ValueError):
    pass


class RetrievalArtifactMaterializer:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self._reader = ArtifactInputReader(artifacts)

    def comparison(self, evaluation_input: EvaluationInput) -> RetrievalComparisonInput:
        try:
            subjects = self._reader.subjects(
                evaluation_input,
                expected_schema=RETRIEVAL_COMPARISON_INPUT_SCHEMA,
                expected_ports=_PORTS,
                domain="retrieval",
            )
            return RetrievalComparisonInput(
                candidate=self._reader.json_model(
                    subjects["retrieval_candidate"],
                    RetrievalCandidate,
                    expected_schema=RETRIEVAL_CANDIDATE_SCHEMA,
                    domain="retrieval candidate",
                ),
                reference=self._reader.json_model(
                    subjects["retrieval_reference"],
                    RetrievalReference,
                    expected_schema=RETRIEVAL_REFERENCE_SCHEMA,
                    domain="retrieval reference",
                ),
                query=self._reader.json_model(
                    subjects["query"],
                    RetrievalQuery,
                    expected_schema=RETRIEVAL_QUERY_SCHEMA,
                    domain="retrieval query",
                ),
            )
        except ArtifactInputError as exc:
            raise RetrievalMaterializationError(str(exc)) from exc
