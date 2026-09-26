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

"""Concurrent execution of independent chunks using the single-chunk engine."""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from hugegraph_llm.extraction_runtime.v1.contracts import NormalizedChunkV1
from hugegraph_llm.extraction_runtime.v1.engine import (
    ExtractionBundleV1,
    ExtractionEngineV1,
    ExtractionRunResultV1,
    RunControlV1,
)


@dataclass(frozen=True)
class ChunkRunResultV1:
    chunk: NormalizedChunkV1
    result: ExtractionRunResultV1


def run_chunks_v1(
    *,
    chunks: Iterable[NormalizedChunkV1],
    prepare: Callable[[NormalizedChunkV1], tuple[ExtractionBundleV1, RunControlV1]],
    max_workers: int = 4,
) -> tuple[ChunkRunResultV1, ...]:
    """Run a finite batch with at most ``max_workers`` chunks executing at once.

    ``prepare`` runs in worker threads and must create a separate Bundle and
    stateful Provider for each chunk. It returns that Bundle and its control.
    Results follow input order, regardless of completion order or chunk ordinal.
    Engine failure terminals are collected normally; preparation and input
    iteration errors propagate to the caller. The pool closes after running
    tasks finish; preparation errors may cancel tasks that have not started.
    The full batch is submitted and retained in memory.
    """

    def run_chunk(chunk: NormalizedChunkV1) -> ChunkRunResultV1:
        bundle, control = prepare(chunk)
        result = ExtractionEngineV1().run(bundle=bundle, chunk=chunk, control=control)
        return ChunkRunResultV1(chunk=chunk, result=result)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return tuple(executor.map(run_chunk, chunks))
