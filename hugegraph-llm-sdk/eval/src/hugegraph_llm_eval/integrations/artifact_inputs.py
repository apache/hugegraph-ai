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

"""Validated Artifact-port reading shared by domain integration adapters."""

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef, ArtifactStore
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationInput
from hugegraph_llm_eval.contracts.identity import SchemaRef

ModelT = TypeVar("ModelT", bound=BaseModel)


class ArtifactInputError(ValueError):
    pass


class ArtifactInputReader:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self._artifacts = artifacts

    @staticmethod
    def subjects(
        evaluation_input: EvaluationInput,
        *,
        expected_schema: SchemaRef,
        expected_ports: frozenset[str],
        domain: str,
    ) -> dict[str, ArtifactRef]:
        if evaluation_input.schema_ref != expected_schema:
            raise ArtifactInputError(f"{domain} input schema must be {expected_schema}")
        subjects = {subject.port.value: subject.artifact for subject in evaluation_input.subjects}
        actual_ports = frozenset(subjects)
        if actual_ports != expected_ports:
            missing = sorted(expected_ports - actual_ports)
            unexpected = sorted(actual_ports - expected_ports)
            raise ArtifactInputError(
                f"{domain} input has missing required ports {missing} and unexpected ports {unexpected}"
            )
        return subjects

    def json_model(
        self,
        artifact: ArtifactRef,
        model_type: type[ModelT],
        *,
        expected_schema: SchemaRef,
        domain: str,
    ) -> ModelT:
        if artifact.descriptor.media_type != "application/json":
            raise ArtifactInputError(f"{domain} Artifact must use application/json")
        if artifact.descriptor.schema_ref != expected_schema:
            raise ArtifactInputError(f"{domain} Artifact schema must be {expected_schema}")
        try:
            payload = json.loads(self._artifacts.read(artifact))
            return model_type.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ArtifactInputError(f"{domain} Artifact must contain valid JSON") from exc
        except ValidationError as exc:
            raise ArtifactInputError(f"{domain} Artifact violates {model_type.__name__}") from exc
