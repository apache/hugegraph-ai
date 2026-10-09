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
from typing import Any, Dict

from hugegraph_llm.config import huge_settings
from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.utils.embedding_utils import get_embeddings_parallel
from hugegraph_llm.utils.log import log


class BuildVectorIndex:
    def __init__(self, embedding: BaseEmbedding, vector_index: type[VectorStoreBase]):
        self.embedding = embedding
        self.vector_index = vector_index.from_name(
            embedding.get_embedding_dim(),
            huge_settings.graph_name,
            "chunks",
        )

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if "chunks" not in context:
            raise ValueError("chunks not found in context.")
        chunks = context["chunks"]
        log.debug("Building vector index for %s chunks...", len(context["chunks"]))
        # Use async parallel embedding to speed up
        chunks_embedding = asyncio.run(get_embeddings_parallel(self.embedding, chunks))  # type: ignore
        if len(chunks_embedding) > 0:
            self.vector_index.add(chunks_embedding, chunks)
            self.vector_index.save_index_by_name(huge_settings.graph_name, "chunks")
        return context
