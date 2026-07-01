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

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from hugegraph_llm.api.models.graph_extract_requests import (
    GraphExtractAndImportRequest,
    GraphExtractRequest,
    GraphImportRequest,
)
from hugegraph_llm.api.models.graph_extract_responses import (
    GraphExtractAndImportResponse,
    GraphExtractError,
    GraphExtractJobCreateResponse,
    GraphExtractJobStatusResponse,
    GraphExtractResponse,
    GraphImportResponse,
)
from hugegraph_llm.services.graph_extract_jobs import (
    GraphExtractJob,
    GraphExtractJobStatus,
    InMemoryGraphExtractJobStore,
)
from hugegraph_llm.services.graph_extract_service import (
    FlowOutputValidationError,
    GraphExtractService,
    GraphImportService,
)
from hugegraph_llm.utils.log import log

GRAPH_EXTRACT_FLOW_OUTPUT_ERROR = "Graph extraction flow output is invalid"
GRAPH_EXTRACT_RUNTIME_ERROR = "Graph extraction failed during execution"
GRAPH_IMPORT_FLOW_OUTPUT_ERROR = "Graph import flow output is invalid"
GRAPH_IMPORT_RUNTIME_ERROR = "Graph import failed during execution"


def _error(code: str, message: str, phase: str, job_id: Optional[str] = None) -> dict:
    return GraphExtractError(code=code, message=message, phase=phase, job_id=job_id).model_dump(exclude_none=True)


def _job_ts(value) -> Optional[str]:
    return value.isoformat() if value else None


def _job_status_response(job: GraphExtractJob) -> GraphExtractJobStatusResponse:
    return GraphExtractJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=_job_ts(job.created_at),
        updated_at=_job_ts(job.updated_at),
        started_at=_job_ts(job.started_at),
        finished_at=_job_ts(job.finished_at),
        expires_at=_job_ts(job.expires_at),
        error=job.error,
    )


def _validation_message(errors) -> str:
    details = []
    for error in errors:
        loc = ".".join(str(part) for part in error.get("loc", []) if part not in {"body"})
        msg = error.get("msg", "invalid input")
        err_type = error.get("type", "validation_error")
        details.append(f"{loc or 'request'}: {msg} ({err_type})")
    return "; ".join(details) or "request validation failed"


def _validation_error_for_path(path: str, message: str) -> dict:
    if path.endswith("/graph/import"):
        return _error("GRAPH_IMPORT_VALIDATION_ERROR", message, "import")
    if path.endswith("/graph/extract-and-import"):
        return _error("GRAPH_EXTRACT_AND_IMPORT_VALIDATION_ERROR", message, "request")
    return _error("GRAPH_EXTRACT_VALIDATION_ERROR", message, "request")


class GraphExtractAPIRoute(APIRoute):
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request):
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                message = _validation_message(exc.errors())
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"detail": _validation_error_for_path(request.url.path, message)},
                )

        return custom_route_handler


def graph_extract_http_api(
    router: APIRouter,
    service=None,
    job_store=None,
    import_service=None,
    run_jobs_inline: Optional[bool] = None,
):
    extract_service = service or GraphExtractService()
    graph_import_service = import_service or GraphImportService()
    jobs = job_store or InMemoryGraphExtractJobStore()
    original_route_class = router.route_class
    router.route_class = GraphExtractAPIRoute

    @router.post("/graph/extract", status_code=status.HTTP_200_OK, response_model=GraphExtractResponse)
    def graph_extract_api(req: GraphExtractRequest) -> GraphExtractResponse:
        try:
            return extract_service.extract_sync(req)
        except FlowOutputValidationError as exc:
            log.error("Graph extraction flow output is invalid: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error("GRAPH_EXTRACT_INVALID_FLOW_OUTPUT", GRAPH_EXTRACT_FLOW_OUTPUT_ERROR, "extract"),
            ) from exc
        except ValueError as exc:
            log.error("Graph extraction input is invalid: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_error("GRAPH_EXTRACT_INVALID_INPUT", str(exc), "request"),
            ) from exc
        except Exception as exc:
            log.error("Unexpected graph extraction error: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error("GRAPH_EXTRACT_FAILED", GRAPH_EXTRACT_RUNTIME_ERROR, "extract"),
            ) from exc

    @router.post(
        "/graph/extract/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=GraphExtractJobCreateResponse,
    )
    def create_graph_extract_job(
        req: GraphExtractRequest,
    ) -> GraphExtractJobCreateResponse:
        """Create a process-local graph extraction job.

        Jobs are stored in memory and are not shared across API worker processes.
        Job status/results are lost on service restart, and cancellation only applies before
        a queued job starts running; it cannot interrupt an active LLM call.
        """
        try:
            job = jobs.create(req)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=_error("GRAPH_EXTRACT_JOB_LIMIT_EXCEEDED", str(exc), "job"),
            ) from exc
        if run_jobs_inline is True:
            jobs.run_job(job.job_id, extract_service)
        elif run_jobs_inline is None:
            try:
                jobs.submit_job(job.job_id, extract_service)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=_error("GRAPH_EXTRACT_JOB_QUEUE_FULL", str(exc), "job", job.job_id),
                ) from exc
        return GraphExtractJobCreateResponse(
            job_id=job.job_id,
            status=job.status,
            result_url=f"/graph/extract/jobs/{job.job_id}/result",
            created_at=_job_ts(job.created_at),
            updated_at=_job_ts(job.updated_at),
        )

    @router.get(
        "/graph/extract/jobs/{job_id}",
        status_code=status.HTTP_200_OK,
        response_model=GraphExtractJobStatusResponse,
    )
    def get_graph_extract_job(job_id: str) -> GraphExtractJobStatusResponse:
        jobs.expire_jobs()
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_error("GRAPH_EXTRACT_JOB_NOT_FOUND", f"Job {job_id} was not found", "job", job_id),
            )
        return _job_status_response(job)

    @router.get(
        "/graph/extract/jobs/{job_id}/result",
        status_code=status.HTTP_200_OK,
        response_model=GraphExtractResponse,
    )
    def get_graph_extract_job_result(job_id: str) -> GraphExtractResponse:
        jobs.expire_jobs()
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_error("GRAPH_EXTRACT_JOB_NOT_FOUND", f"Job {job_id} was not found", "job", job_id),
            )
        if job.status == GraphExtractJobStatus.EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=_error("GRAPH_EXTRACT_JOB_EXPIRED", f"Job {job_id} result has expired", "job", job_id),
            )
        if job.status in {GraphExtractJobStatus.PENDING, GraphExtractJobStatus.RUNNING}:
            raise HTTPException(
                status_code=status.HTTP_202_ACCEPTED,
                detail=_error(
                    "GRAPH_EXTRACT_JOB_NOT_COMPLETE",
                    f"Job {job_id} is not complete",
                    "job",
                    job_id,
                ),
            )
        if job.status == GraphExtractJobStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_error("GRAPH_EXTRACT_JOB_CANCELLED", f"Job {job_id} was cancelled", "job", job_id),
            )
        if job.status == GraphExtractJobStatus.FAILED:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=job.error.model_dump())
        if job.result is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error(
                    "GRAPH_EXTRACT_JOB_RESULT_MISSING", f"Job {job_id} finished without a result", "job", job_id
                ),
            )
        return job.result

    @router.delete(
        "/graph/extract/jobs/{job_id}",
        status_code=status.HTTP_200_OK,
        response_model=GraphExtractJobStatusResponse,
    )
    def cancel_graph_extract_job(job_id: str) -> GraphExtractJobStatusResponse:
        job = jobs.cancel(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_error("GRAPH_EXTRACT_JOB_NOT_FOUND", f"Job {job_id} was not found", "job", job_id),
            )
        if job.status == GraphExtractJobStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_error(
                    "GRAPH_EXTRACT_JOB_NOT_CANCELLABLE",
                    f"Job {job_id} is already running and cannot be interrupted",
                    "job",
                    job_id,
                ),
            )
        return _job_status_response(job)

    @router.post("/graph/import", status_code=status.HTTP_200_OK, response_model=GraphImportResponse)
    def graph_import_api(req: GraphImportRequest) -> GraphImportResponse:
        if not req.write_to_graph:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_error(
                    "GRAPH_IMPORT_CONFIRMATION_REQUIRED",
                    "write_to_graph=true is required before writing graph data to HugeGraph",
                    "import",
                ),
            )
        try:
            return graph_import_service.import_graph(req)
        except FlowOutputValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error("GRAPH_IMPORT_INVALID_FLOW_OUTPUT", GRAPH_IMPORT_FLOW_OUTPUT_ERROR, "import"),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_error("GRAPH_IMPORT_INVALID_INPUT", str(exc), "import"),
            ) from exc
        except Exception as exc:
            log.error("Unexpected graph import error: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error("GRAPH_IMPORT_FAILED", GRAPH_IMPORT_RUNTIME_ERROR, "import"),
            ) from exc

    @router.post(
        "/graph/extract-and-import",
        status_code=status.HTTP_200_OK,
        response_model=GraphExtractAndImportResponse,
    )
    def graph_extract_and_import_api(req: GraphExtractAndImportRequest) -> GraphExtractAndImportResponse:
        if not req.write_to_graph:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_error(
                    "GRAPH_IMPORT_CONFIRMATION_REQUIRED",
                    "write_to_graph=true is required before writing extraction results to HugeGraph",
                    "import",
                ),
            )
        try:
            extract_response = extract_service.extract_sync(req)
        except FlowOutputValidationError as exc:
            log.error("Extract-and-import extraction flow output is invalid: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error("GRAPH_EXTRACT_INVALID_FLOW_OUTPUT", GRAPH_EXTRACT_FLOW_OUTPUT_ERROR, "extract"),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_error("GRAPH_EXTRACT_INVALID_INPUT", str(exc), "request"),
            ) from exc
        except Exception as exc:
            log.error("Unexpected extract-and-import extraction error: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error("GRAPH_EXTRACT_FAILED", GRAPH_EXTRACT_RUNTIME_ERROR, "extract"),
            ) from exc

        try:
            import_response = graph_import_service.import_graph(
                GraphImportRequest(
                    schema=req.schema,
                    data=extract_response.result,
                    write_to_graph=True,
                    client_config=req.client_config,
                    options=req.import_options,
                )
            )
        except FlowOutputValidationError as exc:
            log.error("Extract-and-import import flow output is invalid: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error("GRAPH_IMPORT_INVALID_FLOW_OUTPUT", GRAPH_IMPORT_FLOW_OUTPUT_ERROR, "import"),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_error("GRAPH_IMPORT_INVALID_INPUT", str(exc), "import"),
            ) from exc
        except Exception as exc:
            log.error("Unexpected extract-and-import import error: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_error("GRAPH_IMPORT_FAILED", GRAPH_IMPORT_RUNTIME_ERROR, "import"),
            ) from exc

        return GraphExtractAndImportResponse(
            status=import_response.status,
            extract_result=extract_response,
            import_result=import_response,
        )

    router.route_class = original_route_class
