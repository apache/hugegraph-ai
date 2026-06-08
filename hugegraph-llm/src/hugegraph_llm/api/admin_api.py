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

import ntpath
import os

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from hugegraph_llm.api.exceptions.rag_exceptions import generate_response
from hugegraph_llm.api.models.rag_requests import LogStreamRequest
from hugegraph_llm.api.models.rag_response import RAGResponse
from hugegraph_llm.config import admin_settings

LOG_DIR = "logs"
INSECURE_ADMIN_TOKENS = {"", "xxxx"}


def _is_configured_admin_token(admin_token: str | None) -> bool:
    return admin_token is not None and admin_token not in INSECURE_ADMIN_TOKENS


def _resolve_log_path(log_file: str | None) -> str:
    if not log_file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid log file name.")
    if (
        os.path.isabs(log_file)
        or ntpath.isabs(log_file)
        or ntpath.splitdrive(log_file)[0]
        or "/" in log_file
        or "\\" in log_file
        or os.path.normpath(log_file) in {"", ".", ".."}
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid log file name.")
    return os.path.join(LOG_DIR, log_file)


def admin_http_api(router: APIRouter, log_stream):
    @router.post("/logs", status_code=status.HTTP_200_OK)
    async def log_stream_api(req: LogStreamRequest):
        if not _is_configured_admin_token(admin_settings.admin_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin token is not configured securely.",
            )
        if admin_settings.admin_token != req.admin_token:
            return generate_response(
                RAGResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="Invalid admin_token",
                )
            )
        log_path = _resolve_log_path(req.log_file)

        # Create a StreamingResponse that reads from the log stream generator
        return StreamingResponse(log_stream(log_path), media_type="text/plain")
