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

"""Strict answer candidate, reference, and source schemas."""

from typing import Literal

from pydantic import Field

from hugegraph_llm_eval.contracts.base import StrictModel, VersionedModel


class AnswerCandidate(VersionedModel):
    text: str = Field(max_length=1_000_000)


class AnswerReference(VersionedModel):
    answers: tuple[str, ...] = Field(min_length=1)


class AnswerSource(VersionedModel):
    question: str = Field(min_length=1, max_length=100_000)
    contexts: tuple[str, ...] = ()
    language: Literal["en", "zh"] = "en"


class AnswerComparisonInput(StrictModel):
    candidate: AnswerCandidate
    reference: AnswerReference
    source: AnswerSource
