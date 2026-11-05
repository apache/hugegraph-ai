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

from hugegraph_llm.config import LLMConfig, snapshot_llm_settings
from hugegraph_llm.models.llms.litellm import LiteLLMClient
from hugegraph_llm.models.llms.ollama import OllamaClient
from hugegraph_llm.models.llms.openai import OpenAIClient


def get_chat_llm(llm_configs: LLMConfig, *, limit_output: bool = True, raise_on_truncation: bool = False):
    if llm_configs.chat_llm_type == "openai":
        return OpenAIClient(
            api_key=llm_configs.openai_chat_api_key,
            api_base=llm_configs.openai_chat_api_base,
            model_name=llm_configs.openai_chat_language_model,
            max_tokens=llm_configs.openai_chat_tokens if limit_output else None,
            raise_on_truncation=raise_on_truncation,
        )
    if llm_configs.chat_llm_type == "ollama/local":
        return OllamaClient(
            model=llm_configs.ollama_chat_language_model,
            host=llm_configs.ollama_chat_host,
            port=llm_configs.ollama_chat_port,
            raise_on_truncation=raise_on_truncation,
        )
    if llm_configs.chat_llm_type == "litellm":
        return LiteLLMClient(
            api_key=llm_configs.litellm_chat_api_key or "EMPTY",
            api_base=llm_configs.litellm_chat_api_base,
            model_name=llm_configs.litellm_chat_language_model,
            max_tokens=llm_configs.litellm_chat_tokens if limit_output else None,
            raise_on_truncation=raise_on_truncation,
        )
    raise Exception("chat llm type is not supported !")


def get_extract_llm(llm_configs: LLMConfig, *, raise_on_truncation: bool = False):
    if llm_configs.effective_role("extract") == "chat":
        return get_chat_llm(llm_configs, raise_on_truncation=raise_on_truncation)
    if llm_configs.extract_llm_type == "openai":
        return OpenAIClient(
            api_key=llm_configs.openai_extract_api_key,
            api_base=llm_configs.openai_extract_api_base,
            model_name=llm_configs.openai_extract_language_model,
            max_tokens=llm_configs.openai_extract_tokens,
            raise_on_truncation=raise_on_truncation,
        )
    if llm_configs.extract_llm_type == "ollama/local":
        return OllamaClient(
            model=llm_configs.ollama_extract_language_model,
            host=llm_configs.ollama_extract_host,
            port=llm_configs.ollama_extract_port,
            raise_on_truncation=raise_on_truncation,
        )
    if llm_configs.extract_llm_type == "litellm":
        return LiteLLMClient(
            api_key=llm_configs.litellm_extract_api_key or "EMPTY",
            api_base=llm_configs.litellm_extract_api_base,
            model_name=llm_configs.litellm_extract_language_model,
            max_tokens=llm_configs.litellm_extract_tokens,
            raise_on_truncation=raise_on_truncation,
        )
    raise Exception("extract llm type is not supported !")


def get_text2gql_llm(llm_configs: LLMConfig, *, raise_on_truncation: bool = False):
    if llm_configs.effective_role("text2gql") == "chat":
        return get_chat_llm(llm_configs, raise_on_truncation=raise_on_truncation)
    if llm_configs.text2gql_llm_type == "openai":
        return OpenAIClient(
            api_key=llm_configs.openai_text2gql_api_key,
            api_base=llm_configs.openai_text2gql_api_base,
            model_name=llm_configs.openai_text2gql_language_model,
            max_tokens=llm_configs.openai_text2gql_tokens,
            raise_on_truncation=raise_on_truncation,
        )
    if llm_configs.text2gql_llm_type == "ollama/local":
        return OllamaClient(
            model=llm_configs.ollama_text2gql_language_model,
            host=llm_configs.ollama_text2gql_host,
            port=llm_configs.ollama_text2gql_port,
            raise_on_truncation=raise_on_truncation,
        )
    if llm_configs.text2gql_llm_type == "litellm":
        return LiteLLMClient(
            api_key=llm_configs.litellm_text2gql_api_key or "EMPTY",
            api_base=llm_configs.litellm_text2gql_api_base,
            model_name=llm_configs.litellm_text2gql_language_model,
            max_tokens=llm_configs.litellm_text2gql_tokens,
            raise_on_truncation=raise_on_truncation,
        )
    raise Exception("text2gql llm type is not supported !")


class LLMs:
    """Resolve live settings for every new client, including inherited roles."""

    def get_chat_llm(self, *, raise_on_truncation: bool = False):
        return get_chat_llm(snapshot_llm_settings(), raise_on_truncation=raise_on_truncation)

    def get_extract_llm(self, *, raise_on_truncation: bool = False):
        return get_extract_llm(snapshot_llm_settings(), raise_on_truncation=raise_on_truncation)

    def get_text2gql_llm(self, *, raise_on_truncation: bool = False):
        return get_text2gql_llm(snapshot_llm_settings(), raise_on_truncation=raise_on_truncation)


if __name__ == "__main__":
    client = LLMs().get_chat_llm()
    print(client.generate(prompt="What is the capital of China?"))
    print(client.generate(messages=[{"role": "user", "content": "What is the capital of China?"}]))
