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

from tqdm import tqdm

from hugegraph_llm.config import huge_settings
from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManager
from hugegraph_llm.utils.log import log


class BuildSemanticIndex:
    def __init__(self, embedding: BaseEmbedding, vector_index: type[VectorStoreBase], graph_config=None):
        graph_config = graph_config or {}
        self.graph_name = graph_config.get("graph") or huge_settings.graph_name
        self.vid_index = vector_index.from_name(embedding.get_embedding_dim(), self.graph_name, "graph_vids")
        self.embedding = embedding
        self.sm = SchemaManager(self.graph_name, graph_config=graph_config)

    def _extract_names(self, vertices: list[str]) -> list[str]:
        return [v.split(":")[1] for v in vertices]

    async def _get_embeddings_parallel(self, vids: list[str]) -> list[Any]:
        sem = asyncio.Semaphore(10)
        batch_size = 1000

        async def get_embeddings_with_semaphore(vid_list: list[str]) -> Any:
            async with sem:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, self.embedding.get_texts_embeddings, vid_list)

        vid_batches = [vids[i : i + batch_size] for i in range(0, len(vids), batch_size)]
        tasks = [get_embeddings_with_semaphore(batch) for batch in vid_batches]

        embeddings = []
        with tqdm(total=len(tasks)) as pbar:
            for future in asyncio.as_completed(tasks):
                batch_embeddings = await future
                embeddings.extend(batch_embeddings)
                pbar.update(1)
        return embeddings

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        vertexlabels = self.sm.schema.getSchema()["vertexlabels"]
        all_pk_flag = bool(vertexlabels) and all(data.get("id_strategy") == "PRIMARY_KEY" for data in vertexlabels)

        past_vids = self.vid_index.get_all_properties()
        # TODO: We should build vid vector index separately, especially when the vertices may be very large
        present_vids = context["vertices"]  # Warning: data truncated by fetch_graph_data.py
        removed_vids = set(past_vids) - set(present_vids)
        removed_num = self.vid_index.remove(removed_vids)
        added_vids = list(set(present_vids) - set(past_vids))

        if added_vids:
            vids_to_process = self._extract_names(added_vids) if all_pk_flag else added_vids
            added_embeddings = asyncio.run(self._get_embeddings_parallel(vids_to_process))
            log.info("Building vector index for %s vertices...", len(added_vids))
            self.vid_index.add(added_embeddings, added_vids)
            self.vid_index.save_index_by_name(self.graph_name, "graph_vids")
        else:
            log.debug("No update vertices to build vector index.")
        context.update(
            {
                "removed_vid_vector_num": removed_num,
                "added_vid_vector_num": len(added_vids),
            }
        )
        return context
