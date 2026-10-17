# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Bounded concurrency for independent chunks, retaining input order."""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

from hugegraph_llm.extraction_runtime.v1.contracts import ChunkInput, ChunkResult, ExtractionOptions
from hugegraph_llm.extraction_runtime.v1.engine import ExtractionBundle, ExtractionEngineV1


def run_chunks_v1(
    *,
    chunks: Iterable[ChunkInput],
    prepare: Callable[[ChunkInput], ExtractionBundle],
    options: ExtractionOptions,
) -> tuple[ChunkResult, ...]:
    """Create a fresh bundle per chunk and collect failures alongside successes.

    Preparation runs inside the worker limit. The finite batch is submitted and
    retained in memory; input iteration failures propagate after workers finish.
    """

    def run_chunk(chunk: ChunkInput) -> ChunkResult:
        try:
            bundle = prepare(chunk)
        except Exception as exc:
            return ChunkResult(
                index=chunk.index,
                status="failed",
                graph=None,
                issues=[],
                reason=f"prepare_failed: {type(exc).__name__}",
                stage="prepare",
                reviews_used=0,
                fixes_used=0,
                llm_calls=0,
            )
        return ExtractionEngineV1().run(bundle=bundle, chunk=chunk, options=options)

    with ThreadPoolExecutor(max_workers=options.max_workers) as executor:
        return tuple(executor.map(run_chunk, chunks))
