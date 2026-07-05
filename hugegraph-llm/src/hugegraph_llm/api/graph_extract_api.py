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

import json

from fastapi import APIRouter, HTTPException, status

from hugegraph_llm.api.models.graph_extract_requests import GraphExtractRequest
from hugegraph_llm.api.models.graph_extract_responses import GraphExtractResponse
from hugegraph_llm.config import prompt
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.utils.log import log


class GraphExtractService:
    @staticmethod
    def extract_sync(req: GraphExtractRequest) -> GraphExtractResponse:
        try:
            scheduler = SchedulerSingleton.get_instance()
            result_str = scheduler.schedule_flow(
                FlowName.GRAPH_EXTRACT,
                req.graph_schema,
                req.texts,
                req.example_prompt or prompt.extract_graph_prompt,
                req.extract_type,
                language=req.language,
                split_type=req.split_type,
                client_config=req.client_config,
                extract_strategy=req.extract_strategy,
                include_debug=req.include_debug,
            )
            raw = json.loads(result_str)
            warnings = [raw.pop("warning")] if "warning" in raw else []
            # Enhanced-strategy fields — the flow layer only emits these when
            # extract_strategy == "enhanced", so their absence signals baseline.
            extract_strategy = raw.pop("extract_strategy", "baseline")
            chunk_count = raw.pop("chunk_count", None)
            call_count = raw.pop("call_count", None)
            structured_warnings = raw.pop("structured_warnings", None)
            quality_metrics = raw.pop("quality_metrics", None)
            debug_info = raw.pop("debug_info", None)

            result = {"vertices": raw.get("vertices", []), "edges": raw.get("edges", [])}

            # Surface a short top-level summary of the structured warning count
            # so callers reading the legacy warnings[] can still notice enhanced
            # activity without parsing meta.
            if structured_warnings:
                warnings.append(f"enhanced graph extraction generated {len(structured_warnings)} structured warning(s)")

            meta = {}
            if req.include_meta:
                meta = {
                    "vertex_count": len(result["vertices"]),
                    "edge_count": len(result["edges"]),
                    "text_count": len(req.texts),
                }
                if extract_strategy == "enhanced":
                    meta["extract_strategy"] = extract_strategy
                    if chunk_count is not None:
                        meta["chunk_count"] = chunk_count
                    if call_count is not None:
                        meta["call_count"] = call_count
                    meta["token_usage"] = "unavailable"
                    if structured_warnings is not None:
                        meta["structured_warnings"] = structured_warnings
                    if quality_metrics is not None:
                        meta["quality_metrics"] = quality_metrics
            # include_debug adds debug_info regardless of include_meta so callers
            # can grab the debug payload without opting in to counts.
            if req.include_debug and debug_info is not None:
                meta["debug_info"] = debug_info
            return GraphExtractResponse(result=result, warnings=warnings, meta=meta)
        except HTTPException:
            raise
        except Exception as e:
            log.error("Error in graph_extract_api: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred during graph extraction.",
            ) from e


def graph_extract_http_api(router: APIRouter):
    @router.post("/graph/extract", status_code=status.HTTP_200_OK, response_model=GraphExtractResponse)
    def graph_extract_api(req: GraphExtractRequest):
        return GraphExtractService.extract_sync(req)
