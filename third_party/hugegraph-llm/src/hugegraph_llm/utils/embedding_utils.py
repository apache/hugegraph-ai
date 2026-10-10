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
from typing import Any

from tqdm import tqdm

from hugegraph_llm.models.embeddings.base import BaseEmbedding


async def _get_batch_with_progress(embedding: BaseEmbedding, batch: list[str], pbar: tqdm) -> list[Any]:
    result = await embedding.async_get_texts_embeddings(batch)
    pbar.update(1)
    return result


async def get_embeddings_parallel(embedding: BaseEmbedding, vids: list[str]) -> list[Any]:
    """Get embeddings for texts in parallel.

    This function processes text embeddings asynchronously in parallel, using batching and semaphore
    to control concurrency, improving processing efficiency while preventing resource overuse.

    Args:
        embedding (BaseEmbedding): The embedding model instance used to compute text embeddings.
        vids (list[str]): List of texts to compute embeddings for.

    Returns:
        list[Any]: List of embedding vectors corresponding to the input texts, maintaining the same
                  order as the input vids list.

    Note:
        - Note: Uses a semaphore to limit maximum concurrency if we need
        - Processes texts in batches of 500
        - Displays progress using a progress bar that updates as each batch completes
        - Uses asyncio.gather() to preserve order correspondence between input and output
    """
    batch_size = 500

    # Split vids into batches of size batch_size
    vid_batches = [vids[i : i + batch_size] for i in range(0, len(vids), batch_size)]

    embeddings = []
    with tqdm(total=len(vid_batches)) as pbar:
        # Create tasks for each batch with progress bar updates
        tasks = [_get_batch_with_progress(embedding, batch, pbar) for batch in vid_batches]

        # Use asyncio.gather() to preserve order
        batch_results = await asyncio.gather(*tasks)

        # Combine all batch results in order
        for batch_embeddings in batch_results:
            embeddings.extend(batch_embeddings)

    return embeddings


def get_filename_prefix(embedding_type: str = None, model_name: str = None) -> str:
    """Generate filename based on model name."""
    if not (model_name and model_name.strip() and embedding_type and embedding_type.strip()):
        return ""
    # Sanitize model_name to prevent path traversal or invalid filename chars
    safe_embedding_type = embedding_type.replace("/", "_").replace("\\", "_").strip()
    safe_model_name = model_name.replace("/", "_").replace("\\", "_").strip()
    return f"{safe_embedding_type}_{safe_model_name}"


def get_index_folder_name(graph_name: str, space_name: str = None) -> str:
    if not (space_name and space_name.strip()):
        folder_name = graph_name
    else:
        folder_name = f"{space_name}_{graph_name}"
    return folder_name
