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

from hugegraph_llm.config import LLMConfig, llm_settings
from hugegraph_llm.models.llms.litellm import LiteLLMClient
from hugegraph_llm.models.llms.ollama import OllamaClient
from hugegraph_llm.models.llms.openai import OpenAIClient


def get_chat_llm(llm_configs: LLMConfig):
    if llm_configs.chat_llm_type == "openai":
        return OpenAIClient(
            api_key=llm_configs.openai_chat_api_key,
            api_base=llm_configs.openai_chat_api_base,
            model_name=llm_configs.openai_chat_language_model,
            max_tokens=llm_configs.openai_chat_tokens,
        )
    if llm_configs.chat_llm_type == "ollama/local":
        return OllamaClient(
            model=llm_configs.ollama_chat_language_model,
            host=llm_configs.ollama_chat_host,
            port=llm_configs.ollama_chat_port,
        )
    if llm_configs.chat_llm_type == "litellm":
        return LiteLLMClient(
            api_key=llm_configs.litellm_chat_api_key,
            api_base=llm_configs.litellm_chat_api_base,
            model_name=llm_configs.litellm_chat_language_model,
            max_tokens=llm_configs.litellm_chat_tokens,
        )
    raise Exception("chat llm type is not supported !")


def get_extract_llm(llm_configs: LLMConfig):
    if llm_configs.extract_llm_type == "openai":
        return OpenAIClient(
            api_key=llm_configs.openai_extract_api_key,
            api_base=llm_configs.openai_extract_api_base,
            model_name=llm_configs.openai_extract_language_model,
            max_tokens=llm_configs.openai_extract_tokens,
        )
    if llm_configs.extract_llm_type == "ollama/local":
        return OllamaClient(
            model=llm_configs.ollama_extract_language_model,
            host=llm_configs.ollama_extract_host,
            port=llm_configs.ollama_extract_port,
        )
    if llm_configs.extract_llm_type == "litellm":
        return LiteLLMClient(
            api_key=llm_configs.litellm_extract_api_key,
            api_base=llm_configs.litellm_extract_api_base,
            model_name=llm_configs.litellm_extract_language_model,
            max_tokens=llm_configs.litellm_extract_tokens,
        )
    raise Exception("extract llm type is not supported !")


def get_text2gql_llm(llm_configs: LLMConfig):
    if llm_configs.text2gql_llm_type == "openai":
        return OpenAIClient(
            api_key=llm_configs.openai_text2gql_api_key,
            api_base=llm_configs.openai_text2gql_api_base,
            model_name=llm_configs.openai_text2gql_language_model,
            max_tokens=llm_configs.openai_text2gql_tokens,
        )
    if llm_configs.text2gql_llm_type == "ollama/local":
        return OllamaClient(
            model=llm_configs.ollama_text2gql_language_model,
            host=llm_configs.ollama_text2gql_host,
            port=llm_configs.ollama_text2gql_port,
        )
    if llm_configs.text2gql_llm_type == "litellm":
        return LiteLLMClient(
            api_key=llm_configs.litellm_text2gql_api_key,
            api_base=llm_configs.litellm_text2gql_api_base,
            model_name=llm_configs.litellm_text2gql_language_model,
            max_tokens=llm_configs.litellm_text2gql_tokens,
        )
    raise Exception("text2gql llm type is not supported !")


class LLMs:
    def __init__(self):
        self.chat_llm_type = llm_settings.chat_llm_type
        self.extract_llm_type = llm_settings.extract_llm_type
        self.text2gql_llm_type = llm_settings.text2gql_llm_type

    def get_chat_llm(self):
        if self.chat_llm_type == "openai":
            return OpenAIClient(
                api_key=llm_settings.openai_chat_api_key,
                api_base=llm_settings.openai_chat_api_base,
                model_name=llm_settings.openai_chat_language_model,
                max_tokens=llm_settings.openai_chat_tokens,
            )
        if self.chat_llm_type == "ollama/local":
            return OllamaClient(
                model=llm_settings.ollama_chat_language_model,
                host=llm_settings.ollama_chat_host,
                port=llm_settings.ollama_chat_port,
            )
        if self.chat_llm_type == "litellm":
            return LiteLLMClient(
                api_key=llm_settings.litellm_chat_api_key,
                api_base=llm_settings.litellm_chat_api_base,
                model_name=llm_settings.litellm_chat_language_model,
                max_tokens=llm_settings.litellm_chat_tokens,
            )
        raise Exception("chat llm type is not supported !")

    def get_extract_llm(self):
        if self.extract_llm_type == "openai":
            return OpenAIClient(
                api_key=llm_settings.openai_extract_api_key,
                api_base=llm_settings.openai_extract_api_base,
                model_name=llm_settings.openai_extract_language_model,
                max_tokens=llm_settings.openai_extract_tokens,
            )
        if self.extract_llm_type == "ollama/local":
            return OllamaClient(
                model=llm_settings.ollama_extract_language_model,
                host=llm_settings.ollama_extract_host,
                port=llm_settings.ollama_extract_port,
            )
        if self.extract_llm_type == "litellm":
            return LiteLLMClient(
                api_key=llm_settings.litellm_extract_api_key,
                api_base=llm_settings.litellm_extract_api_base,
                model_name=llm_settings.litellm_extract_language_model,
                max_tokens=llm_settings.litellm_extract_tokens,
            )
        raise Exception("extract llm type is not supported !")

    def get_text2gql_llm(self):
        if self.text2gql_llm_type == "openai":
            return OpenAIClient(
                api_key=llm_settings.openai_text2gql_api_key,
                api_base=llm_settings.openai_text2gql_api_base,
                model_name=llm_settings.openai_text2gql_language_model,
                max_tokens=llm_settings.openai_text2gql_tokens,
            )
        if self.text2gql_llm_type == "ollama/local":
            return OllamaClient(
                model=llm_settings.ollama_text2gql_language_model,
                host=llm_settings.ollama_text2gql_host,
                port=llm_settings.ollama_text2gql_port,
            )
        if self.text2gql_llm_type == "litellm":
            return LiteLLMClient(
                api_key=llm_settings.litellm_text2gql_api_key,
                api_base=llm_settings.litellm_text2gql_api_base,
                model_name=llm_settings.litellm_text2gql_language_model,
                max_tokens=llm_settings.litellm_text2gql_tokens,
            )
        raise Exception("text2gql llm type is not supported !")


if __name__ == "__main__":
    client = LLMs().get_chat_llm()
    print(client.generate(prompt="What is the capital of China?"))
    print(client.generate(messages=[{"role": "user", "content": "What is the capital of China?"}]))
