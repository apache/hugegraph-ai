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

"""A bounded extract, validate, review and repair loop for one chunk."""

import logging
from typing import Literal, Protocol

from hugegraph_llm.extraction_runtime.v1.contracts import (
    ChunkInput,
    ChunkResult,
    ExtractionOptions,
    Issue,
    ReviewResult,
)
from hugegraph_llm.models.llms.base import LLMOutputTruncatedError

log = logging.getLogger(__name__)


class ExtractionBundle(Protocol):
    def extract(self, chunk: ChunkInput) -> dict: ...

    def validate(self, graph: dict, chunk: ChunkInput) -> list[Issue]: ...

    def review(self, graph: dict, chunk: ChunkInput) -> ReviewResult: ...

    def repair(self, graph: dict, chunk: ChunkInput, issues: list[Issue]) -> dict: ...


class ExtractionEngineV1:
    """Keep the current graph and all business counters local to one run."""

    def run(self, *, bundle: ExtractionBundle, chunk: ChunkInput, options: ExtractionOptions) -> ChunkResult:
        current_graph: dict | None = None
        issues: list[Issue] = []
        reviews_used = fixes_used = llm_calls = 0
        stage = "extract"

        def finish(
            status: Literal["final", "candidate", "blocked", "failed"], reason: str, failure_stage: str | None = None
        ) -> ChunkResult:
            return ChunkResult(
                index=chunk.index,
                status=status,
                graph=current_graph,
                issues=issues,
                reason=reason,
                stage=failure_stage,
                reviews_used=reviews_used,
                fixes_used=fixes_used,
                llm_calls=llm_calls,
            )

        try:
            log.debug("Chunk %s: extract", chunk.index)
            llm_calls += 1
            current_graph = bundle.extract(chunk)
            while True:
                stage = "validate"
                issues = bundle.validate(current_graph, chunk)
                if issues:
                    if fixes_used >= options.max_fixes:
                        return finish("blocked", "validation_failed")
                else:
                    if reviews_used >= options.max_reviews:
                        return finish("candidate", "review_budget_exhausted")
                    stage = "review"
                    reviews_used += 1
                    llm_calls += 1
                    log.debug("Chunk %s: review %s", chunk.index, reviews_used)
                    review = bundle.review(current_graph, chunk)
                    issues = review.issues
                    if review.decision == "pass":
                        return finish("final", "review_passed")
                    if review.decision == "block":
                        return finish("blocked", "review_blocked")
                    if review.decision != "fix":
                        raise ValueError(f"Unsupported review decision: {review.decision!r}")
                    if fixes_used >= options.max_fixes:
                        return finish("candidate", "fix_budget_exhausted")

                stage = "repair"
                fixes_used += 1
                llm_calls += 1
                log.debug("Chunk %s: repair %s", chunk.index, fixes_used)
                current_graph = bundle.repair(current_graph, chunk, issues)
                issues = []
        except LLMOutputTruncatedError as exc:
            log.warning("Chunk %s output truncated during %s (%s)", chunk.index, stage, exc.reason)
            return finish("failed", f"{stage}_output_truncated: {exc.reason}", stage)
        except Exception as exc:  # A chunk failure must not discard other chunks' results.
            log.warning("Chunk %s failed during %s (%s)", chunk.index, stage, type(exc).__name__)
            return finish("failed", f"{stage}_failed: {type(exc).__name__}", stage)
