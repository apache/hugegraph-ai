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

"""Materialize typed answer inputs from named Artifact ports."""

from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactStore
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationInput
from hugegraph_llm_eval.contracts.identity import SchemaRef
from hugegraph_llm_eval.integrations.answer.schemas import (
    AnswerCandidate,
    AnswerComparisonInput,
    AnswerReference,
    AnswerSource,
)
from hugegraph_llm_eval.integrations.artifact_inputs import ArtifactInputError, ArtifactInputReader

ANSWER_COMPARISON_INPUT_SCHEMA = SchemaRef(namespace="answer", name="comparison_input", version=1)
ANSWER_CANDIDATE_SCHEMA = SchemaRef(namespace="answer", name="candidate", version=1)
ANSWER_REFERENCE_SCHEMA = SchemaRef(namespace="answer", name="reference", version=1)
ANSWER_SOURCE_SCHEMA = SchemaRef(namespace="answer", name="source", version=1)

_PORTS = frozenset({"answer_candidate", "answer_reference", "answer_source"})


class AnswerMaterializationError(ValueError):
    pass


class AnswerArtifactMaterializer:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self._reader = ArtifactInputReader(artifacts)

    def comparison(self, evaluation_input: EvaluationInput) -> AnswerComparisonInput:
        try:
            subjects = self._reader.subjects(
                evaluation_input,
                expected_schema=ANSWER_COMPARISON_INPUT_SCHEMA,
                expected_ports=_PORTS,
                domain="answer",
            )
            return AnswerComparisonInput(
                candidate=self._reader.json_model(
                    subjects["answer_candidate"],
                    AnswerCandidate,
                    expected_schema=ANSWER_CANDIDATE_SCHEMA,
                    domain="answer candidate",
                ),
                reference=self._reader.json_model(
                    subjects["answer_reference"],
                    AnswerReference,
                    expected_schema=ANSWER_REFERENCE_SCHEMA,
                    domain="answer reference",
                ),
                source=self._reader.json_model(
                    subjects["answer_source"],
                    AnswerSource,
                    expected_schema=ANSWER_SOURCE_SCHEMA,
                    domain="answer source",
                ),
            )
        except ArtifactInputError as exc:
            raise AnswerMaterializationError(str(exc)) from exc
