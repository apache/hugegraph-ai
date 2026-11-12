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

"""Strict retrieval candidate, reference, and query schemas."""

from typing import Annotated

from pydantic import Field, model_validator

from hugegraph_llm_eval.contracts.base import StrictModel, VersionedModel


class RetrievalCandidate(VersionedModel):
    doc_ids: tuple[str, ...] = ()
    contexts: tuple[str, ...] = ()


class RetrievalReference(VersionedModel):
    doc_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    answer: str = ""
    entities: tuple[Annotated[str, Field(min_length=1, max_length=4_000)], ...] | None = None

    @model_validator(mode="after")
    def _unique_entities(self) -> "RetrievalReference":
        if self.entities is not None and len(self.entities) != len(set(self.entities)):
            raise ValueError("reference entities must be unique")
        return self


class RetrievalQuery(VersionedModel):
    question: str = Field(max_length=100_000)


class RetrievalComparisonInput(StrictModel):
    candidate: RetrievalCandidate
    reference: RetrievalReference
    query: RetrievalQuery
