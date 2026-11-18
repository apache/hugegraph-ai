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
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tqdm import tqdm

from hugegraph_llm.config import huge_settings, resource_path
from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManager
from hugegraph_llm.utils.log import log

_VID_META_FILE = "vid_index_meta.json"
_EMBED_WINDOW_SIZE = 10_000


def effective_graphspace(graph_space: Optional[str]) -> str:
    return graph_space.strip() if isinstance(graph_space, str) and graph_space.strip() else "DEFAULT"


def vid_index_name_parts(graph_name: str, graph_space: Optional[str] = None) -> tuple[str, ...]:
    space = effective_graphspace(graph_space)
    if space == "DEFAULT":
        return (graph_name, "graph_vids")
    return (f"{len(space)}_{space}", graph_name, "graph_vids_ns")


def read_vid_index_meta(graph_name: str, graph_space: Optional[str] = None) -> Dict[str, Any]:
    space = effective_graphspace(graph_space)
    parts = vid_index_name_parts(graph_name, graph_space)
    meta_path = os.path.join(resource_path, *parts, _VID_META_FILE)
    if not os.path.exists(meta_path):
        return {
            "graph": graph_name,
            "graphspace": space,
            "index_generation": 0,
            "refreshed_at": None,
        }
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:  # pylint: disable=broad-except
        pass
    return {
        "graph": graph_name,
        "graphspace": space,
        "index_generation": 0,
        "refreshed_at": None,
    }


def _write_vid_index_meta(
    graph_name: str,
    graph_space: Optional[str],
    *,
    total_vids: int,
    added_count: int,
    removed_count: int,
) -> Dict[str, Any]:
    space = effective_graphspace(graph_space)
    parts = vid_index_name_parts(graph_name, graph_space)
    prev = read_vid_index_meta(graph_name, graph_space)
    generation = int(prev.get("index_generation") or 0) + 1
    meta = {
        "graph": graph_name,
        "graphspace": space,
        "index_generation": generation,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "total_vids": total_vids,
        "added_vid_vector_num": added_count,
        "removed_vid_vector_num": removed_count,
    }
    meta_dir = os.path.join(resource_path, *parts)
    os.makedirs(meta_dir, exist_ok=True)
    with open(os.path.join(meta_dir, _VID_META_FILE), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


class BuildSemanticIndex:
    def __init__(self, embedding: BaseEmbedding, vector_index: type[VectorStoreBase]):
        self._index_parts = vid_index_name_parts(huge_settings.graph_name, huge_settings.graph_space)
        self.vid_index = vector_index.from_name(embedding.get_embedding_dim(), *self._index_parts)
        self.embedding = embedding
        self.sm = SchemaManager(huge_settings.graph_name)

    def _extract_names(self, vertices: list[Any]) -> list[str]:
        names = []
        for v in vertices:
            text = str(v)
            names.append(text.split(":", 1)[1] if ":" in text else text)
        return names

    async def _get_embeddings_parallel(self, vids: list[str]) -> list[Any]:
        sem = asyncio.Semaphore(10)
        batch_size = 1000

        async def get_embeddings_with_semaphore(vid_list: list[str], pbar: tqdm) -> Any:
            async with sem:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, self.embedding.get_texts_embeddings, vid_list)
                pbar.update(1)
                return result

        vid_batches = [vids[i : i + batch_size] for i in range(0, len(vids), batch_size)]
        embeddings = []
        with tqdm(total=len(vid_batches)) as pbar:
            tasks = [get_embeddings_with_semaphore(batch, pbar) for batch in vid_batches]
            for batch_embeddings in await asyncio.gather(*tasks):
                embeddings.extend(batch_embeddings)
        return embeddings

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        vertexlabels = self.sm.schema.get_schema()["vertexlabels"]
        all_pk_flag = bool(vertexlabels) and all(data.get("id_strategy") == "PRIMARY_KEY" for data in vertexlabels)

        past_vids = self.vid_index.get_all_properties()
        # TODO: We should build vid vector index separately, especially when the vertices may be very large
        present_vids = context["vertices"]  # Warning: data truncated by fetch_graph_data.py
        scan_complete = context.get("vid_scan_complete") is True
        if scan_complete:
            removed_vids = set(past_vids) - set(present_vids)
            removed_num = self.vid_index.remove(removed_vids)
        else:
            log.warning(
                "Skipping VID vector deletion because paginated scan was incomplete: %s",
                context.get("vid_scan_incomplete_reason"),
            )
            removed_num = 0
        added_vids = list(set(present_vids) - set(past_vids))

        added_count = 0
        succeeded = False
        try:
            if added_vids:
                log.info("Building vector index for %s vertices...", len(added_vids))
                for start in range(0, len(added_vids), _EMBED_WINDOW_SIZE):
                    chunk_vids = added_vids[start : start + _EMBED_WINDOW_SIZE]
                    vids_to_process = self._extract_names(chunk_vids) if all_pk_flag else [str(v) for v in chunk_vids]
                    chunk_embeddings = asyncio.run(self._get_embeddings_parallel(vids_to_process))
                    self.vid_index.add(chunk_embeddings, chunk_vids)
                    added_count += len(chunk_vids)
            else:
                log.debug("No update vertices to build vector index.")
            succeeded = True
        finally:
            if added_count > 0 or removed_num > 0:
                self.vid_index.save_index_by_name(*self._index_parts)

            if added_count > 0 or removed_num > 0 or (succeeded and scan_complete):
                meta = _write_vid_index_meta(
                    huge_settings.graph_name,
                    huge_settings.graph_space,
                    total_vids=len(self.vid_index.get_all_properties()),
                    added_count=added_count,
                    removed_count=removed_num,
                )
                context.update(
                    {
                        "removed_vid_vector_num": removed_num,
                        "added_vid_vector_num": added_count,
                        "index_generation": meta["index_generation"],
                        "refreshed_at": meta["refreshed_at"],
                    }
                )
            else:
                context.update(
                    {
                        "removed_vid_vector_num": removed_num,
                        "added_vid_vector_num": added_count,
                    }
                )
        return context
