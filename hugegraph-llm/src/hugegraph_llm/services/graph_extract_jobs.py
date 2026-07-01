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

import queue
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from hugegraph_llm.api.models.graph_extract_requests import GraphExtractRequest
from hugegraph_llm.api.models.graph_extract_responses import GraphExtractError, GraphExtractResponse
from hugegraph_llm.utils.log import log

JOB_RUNTIME_ERROR = "Graph extraction job failed during execution"


class GraphExtractJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class GraphExtractJob:
    job_id: str
    request: Any
    status: GraphExtractJobStatus
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    result: Optional[GraphExtractResponse] = None
    error: Optional[GraphExtractError] = None


class InMemoryGraphExtractJobStore:
    def __init__(self, max_jobs: int = 100, result_ttl_seconds: int = 3600, max_running_jobs: int = 2):
        self.max_jobs = max_jobs
        self.result_ttl_seconds = result_ttl_seconds
        self.max_running_jobs = max(1, max_running_jobs)
        self._jobs: Dict[str, GraphExtractJob] = {}
        self._lock = threading.RLock()
        self._queue = queue.Queue(maxsize=max_jobs)
        self._workers_started = False

    def create(self, request: Any) -> GraphExtractJob:
        with self._lock:
            self.cleanup()
            if len(self._jobs) >= self.max_jobs:
                raise ValueError("graph extraction job store is full")
            now = self._now()
            job = GraphExtractJob(
                job_id=f"gex_{uuid.uuid4().hex}",
                request=request,
                status=GraphExtractJobStatus.PENDING,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> Optional[GraphExtractJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[GraphExtractJob]:
        with self._lock:
            return list(self._jobs.values())

    def mark_running(self, job_id: str) -> Optional[GraphExtractJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != GraphExtractJobStatus.PENDING:
                return job
            now = self._now()
            job.status = GraphExtractJobStatus.RUNNING
            job.started_at = now
            job.updated_at = now
            return job

    def mark_succeeded(self, job_id: str, result: GraphExtractResponse) -> Optional[GraphExtractJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == GraphExtractJobStatus.CANCELLED:
                return job
            now = self._now()
            job.status = GraphExtractJobStatus.SUCCEEDED
            job.result = result
            job.finished_at = now
            job.expires_at = now + timedelta(seconds=self.result_ttl_seconds)
            job.updated_at = now
            return job

    def mark_failed(self, job_id: str, error: GraphExtractError) -> Optional[GraphExtractJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == GraphExtractJobStatus.CANCELLED:
                return job
            now = self._now()
            job.status = GraphExtractJobStatus.FAILED
            job.error = error
            job.finished_at = now
            job.expires_at = now + timedelta(seconds=self.result_ttl_seconds)
            job.updated_at = now
            return job

    def cancel(self, job_id: str) -> Optional[GraphExtractJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status == GraphExtractJobStatus.PENDING:
                now = self._now()
                job.status = GraphExtractJobStatus.CANCELLED
                job.finished_at = now
                job.expires_at = now + timedelta(seconds=self.result_ttl_seconds)
                job.updated_at = now
            return job

    def expire_jobs(self) -> None:
        with self._lock:
            self._expire_jobs_locked()

    def cleanup(self) -> None:
        with self._lock:
            self._expire_jobs_locked()
            expired_job_ids = [
                job_id for job_id, job in self._jobs.items() if job.status == GraphExtractJobStatus.EXPIRED
            ]
            for job_id in expired_job_ids:
                del self._jobs[job_id]

    def submit_job(self, job_id: str, service) -> Optional[GraphExtractJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status != GraphExtractJobStatus.PENDING:
                return job
            self._start_workers_locked()
            try:
                self._queue.put_nowait((job_id, service))
            except queue.Full as exc:
                self._jobs.pop(job_id, None)
                raise ValueError("graph extraction job queue is full") from exc
            return job

    def _expire_jobs_locked(self) -> None:
        now = self._now()
        for job in self._jobs.values():
            expired_by_result_ttl = job.expires_at is not None and job.expires_at <= now
            expired_by_pending_ttl = (
                job.status == GraphExtractJobStatus.PENDING and self.result_ttl_seconds == 0 and job.created_at <= now
            )
            if job.status != GraphExtractJobStatus.EXPIRED and (expired_by_result_ttl or expired_by_pending_ttl):
                job.status = GraphExtractJobStatus.EXPIRED
                job.result = None
                job.updated_at = now

    def _start_workers_locked(self) -> None:
        if self._workers_started:
            return
        for index in range(self.max_running_jobs):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"graph-extract-job-worker-{index}",
                daemon=True,
            )
            thread.start()
        self._workers_started = True

    def _worker_loop(self) -> None:
        while True:
            job_id, service = self._queue.get()
            try:
                self.run_job(job_id, service)
            finally:
                self._queue.task_done()

    def run_job(self, job_id: str, service) -> None:
        job = self.mark_running(job_id)
        if job is None or job.status != GraphExtractJobStatus.RUNNING:
            return
        try:
            request = job.request
            if isinstance(request, dict):
                request = GraphExtractRequest(**request)
            result = service.extract_sync(request)
            self.mark_succeeded(job_id, result)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Graph extraction job %s failed", job_id)
            self.mark_failed(
                job_id,
                GraphExtractError(
                    code="GRAPH_EXTRACT_JOB_FAILED",
                    message=JOB_RUNTIME_ERROR,
                    phase="extract",
                    job_id=job_id,
                ),
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
