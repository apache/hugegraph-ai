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

from hugegraph_llm.api.models.rag_requests import GraphExtractRequest
from hugegraph_llm.config import prompt
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.utils.log import log


def graph_http_api(router: APIRouter):
    @router.post("/graph/extract", status_code=status.HTTP_200_OK)
    def graph_extract_api(req: GraphExtractRequest):
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
            )
            result = json.loads(result_str)
            if req.include_meta:
                result["meta"] = {
                    "vertex_count": len(result.get("vertices", [])),
                    "edge_count": len(result.get("edges", [])),
                    "text_count": len(req.texts),
                }
            return result
        except HTTPException:
            raise
        except Exception as e:
            log.error("Error in graph_extract_api: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred during graph extraction.",
            ) from e
