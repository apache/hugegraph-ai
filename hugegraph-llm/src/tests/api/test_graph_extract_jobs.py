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

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Full
from unittest.mock import Mock

from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient

from hugegraph_llm.api.graph_extract_api import graph_extract_http_api
from hugegraph_llm.api.models.graph_extract_responses import GraphExtractResponse
from hugegraph_llm.services.graph_extract_jobs import GraphExtractJobStatus, InMemoryGraphExtractJobStore


def _payload():
    return {
        "texts": ["marko knows vadas"],
        "schema": {
            "vertexlabels": [{"name": "person", "properties": ["name"]}],
            "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "person"}],
        },
        "example_prompt": "extract graph",
    }


def _client(service=None, job_store=None, run_jobs_inline=True):
    router = APIRouter()
    graph_extract_http_api(
        router,
        service=service,
        job_store=job_store,
        run_jobs_inline=run_jobs_inline,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _success_response():
    return GraphExtractResponse(
        status="succeeded",
        result={"vertices": [{"label": "person"}], "edges": []},
        warnings=[],
        meta={
            "extract_type": "property_graph",
            "language": "zh",
            "split_type": "document",
            "text_count": 1,
            "vertex_count": 1,
            "edge_count": 0,
            "call_count": 1,
            "duration_ms": 1,
        },
    )


def test_job_creation_returns_pending_status_and_result_url_without_running_inline():
    client = _client(Mock(), InMemoryGraphExtractJobStore(), run_jobs_inline=False)

    response = client.post("/graph/extract/jobs", json=_payload())

    assert response.status_code == status.HTTP_202_ACCEPTED
    body = response.json()
    assert body["job_id"]
    assert body["status"] == GraphExtractJobStatus.PENDING
    assert body["result_url"] == f"/graph/extract/jobs/{body['job_id']}/result"


def test_successful_job_reaches_succeeded_and_exposes_result():
    service = Mock()
    service.extract_sync.return_value = _success_response()
    store = InMemoryGraphExtractJobStore()
    client = _client(service, store, run_jobs_inline=True)

    created = client.post("/graph/extract/jobs", json=_payload()).json()
    status_response = client.get(f"/graph/extract/jobs/{created['job_id']}")
    result_response = client.get(f"/graph/extract/jobs/{created['job_id']}/result")

    assert status_response.status_code == status.HTTP_200_OK
    assert status_response.json()["status"] == GraphExtractJobStatus.SUCCEEDED
    assert result_response.status_code == status.HTTP_200_OK
    assert result_response.json()["result"]["vertices"] == [{"label": "person"}]


def test_default_job_route_runs_through_background_worker_and_exposes_result():
    service = Mock()
    service.extract_sync.return_value = _success_response()
    store = InMemoryGraphExtractJobStore()
    client = _client(service, store, run_jobs_inline=None)

    created = client.post("/graph/extract/jobs", json=_payload()).json()

    status_body = {}
    for _ in range(50):
        status_response = client.get(f"/graph/extract/jobs/{created['job_id']}")
        status_body = status_response.json()
        if status_body["status"] == GraphExtractJobStatus.SUCCEEDED:
            break
        time.sleep(0.02)

    assert status_body["status"] == GraphExtractJobStatus.SUCCEEDED
    result_response = client.get(f"/graph/extract/jobs/{created['job_id']}/result")
    assert result_response.status_code == status.HTTP_200_OK
    assert result_response.json()["status"] == "succeeded"
    service.extract_sync.assert_called_once()


def test_failed_job_stores_error_details():
    service = Mock()
    service.extract_sync.side_effect = RuntimeError("llm failed with sensitive raw document")
    client = _client(service, InMemoryGraphExtractJobStore(), run_jobs_inline=True)

    created = client.post("/graph/extract/jobs", json=_payload()).json()
    result_response = client.get(f"/graph/extract/jobs/{created['job_id']}/result")

    assert result_response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert result_response.json()["detail"]["code"] == "GRAPH_EXTRACT_JOB_FAILED"
    assert result_response.json()["detail"]["message"] == "Graph extraction job failed during execution"
    assert result_response.json()["detail"]["phase"] == "extract"
    assert "sensitive raw document" not in str(result_response.json())


def test_pending_job_result_returns_not_complete_semantics_and_can_be_cancelled():
    store = InMemoryGraphExtractJobStore()
    client = _client(Mock(), store, run_jobs_inline=False)

    created = client.post("/graph/extract/jobs", json=_payload()).json()
    pending_result = client.get(f"/graph/extract/jobs/{created['job_id']}/result")
    delete_response = client.delete(f"/graph/extract/jobs/{created['job_id']}")
    status_response = client.get(f"/graph/extract/jobs/{created['job_id']}")

    assert pending_result.status_code == status.HTTP_202_ACCEPTED
    assert pending_result.json()["detail"]["code"] == "GRAPH_EXTRACT_JOB_NOT_COMPLETE"
    assert delete_response.status_code == status.HTTP_200_OK
    assert status_response.json()["status"] == GraphExtractJobStatus.CANCELLED


def test_cancelled_pending_job_gets_retention_ttl_and_can_release_capacity():
    store = InMemoryGraphExtractJobStore(max_jobs=1)
    job = store.create(_payload())

    cancelled = store.cancel(job.job_id)

    assert cancelled.status == GraphExtractJobStatus.CANCELLED
    assert cancelled.expires_at is not None
    cancelled.expires_at = cancelled.finished_at - timedelta(seconds=1)
    store.cleanup()
    replacement = store.create(_payload())
    assert replacement.job_id != job.job_id
    assert len(store.list_jobs()) == 1


def test_unknown_and_expired_jobs_return_explicit_semantics():
    store = InMemoryGraphExtractJobStore(result_ttl_seconds=0)
    client = _client(Mock(), store, run_jobs_inline=False)

    created = client.post("/graph/extract/jobs", json=_payload()).json()
    store.expire_jobs()
    unknown_response = client.get("/graph/extract/jobs/missing")
    expired_result = client.get(f"/graph/extract/jobs/{created['job_id']}/result")

    assert unknown_response.status_code == status.HTTP_404_NOT_FOUND
    assert unknown_response.json()["detail"]["code"] == "GRAPH_EXTRACT_JOB_NOT_FOUND"
    assert expired_result.status_code == status.HTTP_410_GONE
    assert expired_result.json()["detail"]["code"] == "GRAPH_EXTRACT_JOB_EXPIRED"


def test_expiring_job_clears_result_payload():
    store = InMemoryGraphExtractJobStore(result_ttl_seconds=0)
    job = store.create(_payload())
    store.mark_running(job.job_id)
    store.mark_succeeded(job.job_id, _success_response())

    store.expire_jobs()

    expired_job = store.get(job.job_id)
    assert expired_job.status == GraphExtractJobStatus.EXPIRED
    assert expired_job.result is None


def test_expired_jobs_do_not_count_against_capacity_after_cleanup():
    store = InMemoryGraphExtractJobStore(max_jobs=1, result_ttl_seconds=0)

    first_job = store.create(_payload())
    store.expire_jobs()
    second_job = store.create(_payload())

    assert first_job.status == GraphExtractJobStatus.EXPIRED
    assert second_job.job_id != first_job.job_id
    assert len(store.list_jobs()) == 1


def test_queue_full_rolls_back_pending_job(monkeypatch):
    store = InMemoryGraphExtractJobStore(max_jobs=1)
    job = store.create(_payload())
    monkeypatch.setattr(store._queue, "put_nowait", Mock(side_effect=Full))

    try:
        store.submit_job(job.job_id, Mock())
    except ValueError as exc:
        assert "queue is full" in str(exc)
    else:
        raise AssertionError("queue.Full should fail job submission")

    assert store.get(job.job_id) is None
    replacement = store.create(_payload())
    assert replacement.job_id != job.job_id


def test_running_job_cancellation_does_not_claim_task_was_stopped():
    store = InMemoryGraphExtractJobStore()
    job = store.create(_payload())
    store.mark_running(job.job_id)

    cancelled = store.cancel(job.job_id)

    assert cancelled.status == GraphExtractJobStatus.RUNNING


def test_delete_running_job_returns_explicit_not_cancellable_error():
    store = InMemoryGraphExtractJobStore()
    job = store.create(_payload())
    store.mark_running(job.job_id)
    client = _client(Mock(), store, run_jobs_inline=False)

    response = client.delete(f"/graph/extract/jobs/{job.job_id}")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"]["code"] == "GRAPH_EXTRACT_JOB_NOT_CANCELLABLE"
    assert store.get(job.job_id).status == GraphExtractJobStatus.RUNNING


def test_zero_ttl_does_not_expire_running_job():
    store = InMemoryGraphExtractJobStore(result_ttl_seconds=0)
    job = store.create(_payload())
    store.mark_running(job.job_id)

    store.expire_jobs()

    assert store.get(job.job_id).status == GraphExtractJobStatus.RUNNING


def test_concurrent_job_creation_preserves_store_state():
    store = InMemoryGraphExtractJobStore(max_jobs=20)

    with ThreadPoolExecutor(max_workers=5) as executor:
        job_ids = list(executor.map(lambda _: store.create(_payload()).job_id, range(10)))

    assert len(set(job_ids)) == 10
    assert len(store.list_jobs()) == 10
