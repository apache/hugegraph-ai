# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from openai.resources.chat.completions import Completions
from openai.types.chat import ChatCompletion

from hugegraph_llm.config import llm_settings
from hugegraph_llm.operators.llm_op.keyword_extract import KeywordExtract

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("provider", ["openai", "litellm"])
def test_legacy_keyword_extraction_parses_truncated_sdk_response(monkeypatch, provider):
    """Keep the real operator, configured extract factory and client wrapper."""
    monkeypatch.setattr(llm_settings, "extract_llm_type", provider)
    monkeypatch.setattr(llm_settings, f"{provider}_extract_api_key", "test-key")
    monkeypatch.setattr(llm_settings, f"{provider}_extract_api_base", "http://model.invalid/v1")
    monkeypatch.setattr(llm_settings, f"{provider}_extract_language_model", "test-model")
    monkeypatch.setattr(llm_settings, f"{provider}_extract_tokens", 37)
    requests = []

    def completion(**kwargs):
        requests.append(kwargs)
        return ChatCompletion(
            id="test-completion",
            created=1,
            model="test-model",
            object="chat.completion",
            choices=[
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "KEYWORDS: graph:0.9, database:0.8, unfinished",
                    },
                    "finish_reason": "length",
                }
            ],
        )

    if provider == "openai":
        monkeypatch.setattr(Completions, "create", lambda _self, **kwargs: completion(**kwargs))
    else:
        monkeypatch.setattr("hugegraph_llm.models.llms.litellm.completion", completion)

    result = KeywordExtract(text="Explain graph databases.").run({"extract_method": "llm", "call_count": 4})

    assert result["keywords"] == ["graph", "database"]
    assert result["call_count"] == 5
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 37
