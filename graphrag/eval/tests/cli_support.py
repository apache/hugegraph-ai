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

"""Shared request and response model for the CLI-backed Judge tests."""

from typing import Literal

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.evaluation.judges.base import JudgeContentRef, JudgeMessage, JudgeRequest


class CliVerdict(StrictModel):
    verdict: Literal["yes", "no"]
    note: str | None = None


def _content_ref(name: str, fill: str) -> JudgeContentRef:
    return JudgeContentRef(
        component=ComponentRef(namespace="graph", name=name, revision="v1"),
        content_digest="sha256:" + fill * 64,
    )


def cli_request(marker: str = "ok", *, system: str | None = "Judge strictly.") -> JudgeRequest[CliVerdict]:
    messages = [JudgeMessage(role="user", content=f"Is the claim supported? [scenario:{marker}]")]
    if system is not None:
        messages.insert(0, JudgeMessage(role="system", content=system))
    return JudgeRequest(
        messages=tuple(messages),
        response_type=CliVerdict,
        prompt=_content_ref("cli_prompt", "a"),
        rubric=_content_ref("cli_rubric", "b"),
    )
