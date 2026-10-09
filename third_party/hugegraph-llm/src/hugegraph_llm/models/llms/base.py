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

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Callable, Dict, Generator, List, Optional


class BaseLLM(ABC):
    """LLM wrapper should take in a prompt and return a string."""

    @abstractmethod
    def generate(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """Comment"""

    @abstractmethod
    async def agenerate(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """Comment"""

    @abstractmethod
    def generate_streaming(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        on_token_callback: Optional[Callable] = None,
    ) -> Generator[str, None, None]:
        """Comment"""

    @abstractmethod
    async def agenerate_streaming(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        on_token_callback: Optional[Callable] = None,
    ) -> AsyncGenerator[str, None]:
        """Comment"""

    @abstractmethod
    def num_tokens_from_string(
        self,
        string: str,
    ) -> str:
        """Given a string returns the number of tokens the given string consists of"""

    @abstractmethod
    def max_allowed_token_length(
        self,
    ) -> int:
        """Returns the maximum number of tokens the LLM can handle"""

    @abstractmethod
    def get_llm_type(self) -> str:
        """Returns the type of the LLM"""
