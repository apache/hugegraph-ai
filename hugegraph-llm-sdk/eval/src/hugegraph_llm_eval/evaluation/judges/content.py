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

"""Judge instruction text whose persisted identity is derived from its bytes."""

from pydantic import Field

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.digests import ContentDigest
from hugegraph_llm_eval.contracts.domain.judge import JudgeContentRef
from hugegraph_llm_eval.contracts.identity import ComponentRef


class JudgeContent(StrictModel):
    component: ComponentRef
    text: str = Field(min_length=1, max_length=1_000_000)

    @property
    def reference(self) -> JudgeContentRef:
        return JudgeContentRef(
            component=self.component,
            content_digest=ContentDigest.from_bytes(self.text.encode("utf-8")),
        )
