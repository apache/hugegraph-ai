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


from hugegraph_llm.config import LLMConfig, llm_settings, snapshot_llm_settings
from hugegraph_llm.models.embeddings.ollama import OllamaEmbedding
from hugegraph_llm.models.embeddings.openai import OpenAIEmbedding

model_map = {
    "openai": llm_settings.openai_embedding_model,
    "ollama/local": llm_settings.ollama_embedding_model,
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

    raise ValueError("embedding type is not supported !")


class Embeddings:
    def get_embedding(self):
        """Build one embedding client from a complete runtime snapshot."""
        settings = snapshot_llm_settings()
        if settings.embedding_type == "openai":
            # Create with default dimension first
            embedding = OpenAIEmbedding(
                model_name=settings.openai_embedding_model,
                api_key=settings.openai_embedding_api_key,
                api_base=settings.openai_embedding_api_base,
            )
            # Dynamically get actual dimension
            try:
                test_vec = embedding.get_text_embedding("test")
                embedding.embedding_dimension = len(test_vec)
            except Exception:  # pylint: disable=broad-except
                pass  # Keep default dimension
            return embedding
        if settings.embedding_type == "ollama/local":
            # Create with default dimension first
            embedding = OllamaEmbedding(
                model=settings.ollama_embedding_model,
                host=settings.ollama_embedding_host,
                port=settings.ollama_embedding_port,
            )
            # Dynamically get actual dimension
            try:
                test_vec = embedding.get_text_embedding("test")
                embedding.embedding_dimension = len(test_vec)
            except Exception:  # pylint: disable=broad-except
                pass  # Keep default dimension
            return embedding

        raise Exception("embedding type is not supported !")
