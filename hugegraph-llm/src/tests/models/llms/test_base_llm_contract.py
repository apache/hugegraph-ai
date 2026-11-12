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

import asyncio
from typing import AsyncGenerator, get_type_hints

from hugegraph_llm.models.llms.base import BaseLLM


def test_agenerate_streaming_is_directly_async_iterable():
    """The streaming entry point must not be typed as a coroutine of a generator.

    `async def ... -> AsyncGenerator` mis-types the call result as
    `Coroutine[..., AsyncGenerator[...]]`, contradicting every implementation
    (async generator functions) and every call site (plain `async for`).
    """
    assert not asyncio.iscoroutinefunction(BaseLLM.agenerate_streaming)
    assert get_type_hints(BaseLLM.agenerate_streaming)["return"] == AsyncGenerator[str, None]


def test_num_tokens_from_string_returns_int():
    """Implementations return int token counts; the base previously declared str."""
    assert get_type_hints(BaseLLM.num_tokens_from_string)["return"] is int
