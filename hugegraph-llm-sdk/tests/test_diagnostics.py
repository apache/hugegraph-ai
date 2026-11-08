# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from types import SimpleNamespace

import pytest

from hugegraph_llm_sdk.providers._diagnostics import token_usage


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (
            {"prompt_tokens": 3, "completion_tokens": 4},
            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        ),
        (
            SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=9),
            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 9},
        ),
        ({"prompt_tokens": True, "completion_tokens": -1, "total_tokens": 2.0}, {}),
        ({"prompt_tokens": 3, "cached_tokens": 2}, {"prompt_tokens": 3}),
        (None, {}),
    ],
)
def test_token_usage_keeps_only_non_negative_integer_counters(usage, expected):
    assert token_usage(usage) == expected
