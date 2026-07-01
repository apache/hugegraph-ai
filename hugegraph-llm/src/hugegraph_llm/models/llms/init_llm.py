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

OPENAI_DEFAULT_API_BASE = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-4.1-mini"
OPENAI_DEFAULT_EXTRACT_TOKENS = 256
LITELLM_DEFAULT_MODEL = "openai/gpt-4.1-mini"
LITELLM_DEFAULT_EXTRACT_TOKENS = 256


def _extract_key_is_absent_or_shared(extract_api_key, chat_api_key) -> bool:
    return not extract_api_key or extract_api_key == chat_api_key


def _use_openai_chat_fallback(llm_configs: LLMConfig) -> bool:
    if llm_configs.chat_llm_type != "openai":
        return False
    explicit_extract_config = (
        not _extract_key_is_absent_or_shared(llm_configs.openai_extract_api_key, llm_configs.openai_chat_api_key)
        or llm_configs.openai_extract_api_base not in {OPENAI_DEFAULT_API_BASE, llm_configs.openai_chat_api_base}
        or (
            llm_configs.openai_extract_language_model
            not in {OPENAI_DEFAULT_MODEL, llm_configs.openai_chat_language_model}
        )
        or (llm_configs.openai_extract_tokens not in {OPENAI_DEFAULT_EXTRACT_TOKENS, llm_configs.openai_chat_tokens})
    )
    return not explicit_extract_config and bool(
        llm_configs.openai_chat_api_key or llm_configs.openai_chat_api_base or llm_configs.openai_chat_language_model
    )


def _use_litellm_chat_fallback(llm_configs: LLMConfig) -> bool:
    if llm_configs.chat_llm_type != "litellm":
        return False
    explicit_extract_config = (
        not _extract_key_is_absent_or_shared(llm_configs.litellm_extract_api_key, llm_configs.litellm_chat_api_key)
        or llm_configs.litellm_extract_api_base not in {None, llm_configs.litellm_chat_api_base}
        or (
            llm_configs.litellm_extract_language_model
            not in {LITELLM_DEFAULT_MODEL, llm_configs.litellm_chat_language_model}
        )
        or (llm_configs.litellm_extract_tokens not in {LITELLM_DEFAULT_EXTRACT_TOKENS, llm_configs.litellm_chat_tokens})
    )
    return not explicit_extract_config and bool(
        llm_configs.litellm_chat_api_key or llm_configs.litellm_chat_api_base or llm_configs.litellm_chat_language_model
    )


def _ollama_extract_config(llm_configs: LLMConfig):
    if (
        llm_configs.chat_llm_type == "ollama/local"
        and not llm_configs.ollama_extract_language_model
        and llm_configs.ollama_chat_language_model
    ):
        return {
            "model": llm_configs.ollama_chat_language_model,
            "host": llm_configs.ollama_chat_host,
            "port": llm_configs.ollama_chat_port,
        }
    return {
        "model": llm_configs.ollama_extract_language_model,
        "host": llm_configs.ollama_extract_host,
        "port": llm_configs.ollama_extract_port,
    }


def _openai_extract_config(llm_configs: LLMConfig):
    if _use_openai_chat_fallback(llm_configs):
        return {
            "api_key": llm_configs.openai_chat_api_key,
            "api_base": llm_configs.openai_chat_api_base,
            "model_name": llm_configs.openai_chat_language_model,
            "max_tokens": llm_configs.openai_chat_tokens,
        }
    return {
        "api_key": llm_configs.openai_extract_api_key,
        "api_base": llm_configs.openai_extract_api_base,
        "model_name": llm_configs.openai_extract_language_model,
        "max_tokens": llm_configs.openai_extract_tokens,
    }


def _litellm_extract_config(llm_configs: LLMConfig):
    if _use_litellm_chat_fallback(llm_configs):
        return {
            "api_key": llm_configs.litellm_chat_api_key,
            "api_base": llm_configs.litellm_chat_api_base,
            "model_name": llm_configs.litellm_chat_language_model,
            "max_tokens": llm_configs.litellm_chat_tokens,
        }
    return {
        "api_key": llm_configs.litellm_extract_api_key,
        "api_base": llm_configs.litellm_extract_api_base,
        "model_name": llm_configs.litellm_extract_language_model,
        "max_tokens": llm_configs.litellm_extract_tokens,
    }


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
        return OpenAIClient(**_openai_extract_config(llm_configs))
    if llm_configs.extract_llm_type == "ollama/local":
        return OllamaClient(**_ollama_extract_config(llm_configs))
    if llm_configs.extract_llm_type == "litellm":
        return LiteLLMClient(**_litellm_extract_config(llm_configs))
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
            return OpenAIClient(**_openai_extract_config(llm_settings))
        if self.extract_llm_type == "ollama/local":
            return OllamaClient(**_ollama_extract_config(llm_settings))
        if self.extract_llm_type == "litellm":
            return LiteLLMClient(**_litellm_extract_config(llm_settings))
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
