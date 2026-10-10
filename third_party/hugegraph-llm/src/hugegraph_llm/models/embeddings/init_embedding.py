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
from hugegraph_llm.models.embeddings.litellm import LiteLLMEmbedding
from hugegraph_llm.models.embeddings.ollama import OllamaEmbedding
from hugegraph_llm.models.embeddings.openai import OpenAIEmbedding

model_map = {
    "openai": llm_settings.openai_embedding_model,
    "ollama/local": llm_settings.ollama_embedding_model,
    "litellm": llm_settings.litellm_embedding_model,
}


def get_embedding(llm_configs: LLMConfig):
    if llm_configs.embedding_type == "openai":
        return OpenAIEmbedding(
            model_name=llm_configs.openai_embedding_model,
            api_key=llm_configs.openai_embedding_api_key,
            api_base=llm_configs.openai_embedding_api_base,
        )
    if llm_configs.embedding_type == "ollama/local":
        return OllamaEmbedding(
            model=llm_configs.ollama_embedding_model,
            host=llm_configs.ollama_embedding_host,
            port=llm_configs.ollama_embedding_port,
        )
    if llm_configs.embedding_type == "litellm":
        return LiteLLMEmbedding(
            model_name=llm_configs.litellm_embedding_model,
            api_key=llm_configs.litellm_embedding_api_key,
            api_base=llm_configs.litellm_embedding_api_base,
        )

    raise ValueError("embedding type is not supported !")


class Embeddings:
    def __init__(self):
        self.embedding_type = llm_settings.embedding_type

    def get_embedding(self):
        """Get embedding instance and dynamically determine dimension if needed."""
        if self.embedding_type == "openai":
            # Create with default dimension first
            embedding = OpenAIEmbedding(
                model_name=llm_settings.openai_embedding_model,
                api_key=llm_settings.openai_embedding_api_key,
                api_base=llm_settings.openai_embedding_api_base,
            )
            # Dynamically get actual dimension
            try:
                test_vec = embedding.get_text_embedding("test")
                embedding.embedding_dimension = len(test_vec)
            except Exception:  # pylint: disable=broad-except
                pass  # Keep default dimension
            return embedding
        if self.embedding_type == "ollama/local":
            # Create with default dimension first
            embedding = OllamaEmbedding(
                model=llm_settings.ollama_embedding_model,
                host=llm_settings.ollama_embedding_host,
                port=llm_settings.ollama_embedding_port,
            )
            # Dynamically get actual dimension
            try:
                test_vec = embedding.get_text_embedding("test")
                embedding.embedding_dimension = len(test_vec)
            except Exception:  # pylint: disable=broad-except
                pass  # Keep default dimension
            return embedding
        if self.embedding_type == "litellm":
            # For LiteLLM, we need to get dimension dynamically
            # Create a temporary instance to test dimension
            temp_embedding = LiteLLMEmbedding(
                embedding_dimension=1536,  # Temporary default
                model_name=llm_settings.litellm_embedding_model,
                api_key=llm_settings.litellm_embedding_api_key,
                api_base=llm_settings.litellm_embedding_api_base,
            )
            # Get actual dimension
            try:
                test_vec = temp_embedding.get_text_embedding("test")
                actual_dim = len(test_vec)
            except Exception:  # pylint: disable=broad-except
                actual_dim = 1536  # Fallback

            # Create final instance with correct dimension
            embedding = LiteLLMEmbedding(
                embedding_dimension=actual_dim,
                model_name=llm_settings.litellm_embedding_model,
                api_key=llm_settings.litellm_embedding_api_key,
                api_base=llm_settings.litellm_embedding_api_base,
            )
            return embedding  # type: ignore

        raise Exception("embedding type is not supported !")
