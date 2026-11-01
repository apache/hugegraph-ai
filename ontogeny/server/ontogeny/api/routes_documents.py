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

"""Document ingestion surface: corpus, runs, and the review queue.

All routes live on the admin router (``require_admin``): a document corpus is
an ontology input, and an accepted extraction writes ontology rows. The review
detail returns the *original chunk* next to the proposed fields, which is the
only honest way to approve an extraction.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..service import ServiceContext
from .deps import get_principal, get_sc
from .schemas import (
    CandidateAcceptBody,
    CandidateRejectBody,
    DocumentGraphBody,
    DocumentIngestBody,
    DocumentSkillCreateBody,
    DocumentTaskConfigBody,
    DocumentTaskCreateBody,
    DocumentUploadBody,
)


def register(admin_r: APIRouter, sc: ServiceContext) -> None:
    @admin_r.post("/documents/default")
    async def documents_default_source(sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.ensure_default_source()

    @admin_r.get("/documents/status")
    async def documents_status(sc: ServiceContext = Depends(get_sc)):
        return sc.documents.status()

    @admin_r.get("/documents/stores")
    async def document_stores(sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.store_summaries()

    @admin_r.post("/documents/upload")
    async def documents_upload(body: DocumentUploadBody, sc: ServiceContext = Depends(get_sc)):
        import base64

        files = []
        for item in body.files:
            if item.content_b64 is not None:
                files.append({"name": item.name, "content_b64": item.content_b64})
            elif item.content is not None:
                files.append(
                    {"name": item.name, "content_b64": base64.b64encode(item.content.encode("utf-8")).decode("ascii")}
                )
            else:
                from ..documents.engine import DocumentError

                raise DocumentError(f"file {item.name!r} has neither content nor content_b64")
        return await sc.documents.upload(body.store, files)

    @admin_r.get("/documents")
    async def documents_list(store: str, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.list_documents(store)

    @admin_r.delete("/documents/{doc_id}")
    async def documents_remove(doc_id: str, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.remove_document(doc_id)

    @admin_r.post("/documents/ingest")
    async def documents_ingest(body: DocumentIngestBody, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.ingest(body.store, objects=body.objects, dry_run=body.dry_run)

    @admin_r.get("/documents/runs")
    async def documents_runs(store: str | None = None, limit: int = 30, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.list_runs(store, limit=limit)

    @admin_r.get("/documents/runs/{run_id}")
    async def documents_run_detail(run_id: int, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.run_detail(run_id)

    @admin_r.get("/documents/candidates")
    async def documents_candidates(
        status: str = "pending",
        store: str | None = None,
        limit: int = 100,
        sc: ServiceContext = Depends(get_sc),
    ):
        return await sc.documents.list_candidates(status, store, limit=limit)

    @admin_r.get("/documents/candidates/{candidate_id}")
    async def documents_candidate(candidate_id: int, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.candidate_detail(candidate_id)

    @admin_r.post("/documents/candidates/{candidate_id}/accept")
    async def documents_candidate_accept(
        candidate_id: int,
        body: CandidateAcceptBody,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        return await sc.documents.accept_candidate(
            candidate_id, body.overrides or None, principal=str(principal.get("id") or "unknown"), note=body.note
        )

    @admin_r.post("/documents/candidates/{candidate_id}/reject")
    async def documents_candidate_reject(
        candidate_id: int,
        body: CandidateRejectBody,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        return await sc.documents.reject_candidate(
            candidate_id, principal=str(principal.get("id") or "unknown"), reason=body.reason
        )

    # ------------------------------------------------------------- task mode

    @admin_r.get("/documents/schema")
    async def documents_schema(store: str, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.tasks.schema_options(store)

    @admin_r.post("/documents/schema/preview")
    async def documents_schema_preview(body: dict, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.tasks.preview(str(body.get("store") or ""), body.get("scope"))

    @admin_r.get("/documents/skills")
    async def documents_skills(sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.tasks.list_skills()

    @admin_r.post("/documents/skills")
    async def documents_skill_create(
        body: DocumentSkillCreateBody,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        return await sc.documents.tasks.create_skill(body.model_dump(), str(principal.get("id") or "unknown"))

    @admin_r.post("/documents/tasks")
    async def documents_task_create(
        body: DocumentTaskCreateBody,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        import base64

        files = []
        for item in body.files:
            if item.content_b64 is not None:
                files.append({"name": item.name, "content_b64": item.content_b64})
            elif item.content is not None:
                files.append(
                    {"name": item.name, "content_b64": base64.b64encode(item.content.encode("utf-8")).decode("ascii")}
                )
            else:
                from ..documents.engine import DocumentError

                raise DocumentError(f"file {item.name!r} has neither content nor content_b64")
        return await sc.documents.tasks.create_tasks(
            body.store,
            files,
            doc_ids=body.doc_ids,
            scope=body.scope.model_dump() if body.scope is not None else None,
            skill=body.skill.model_dump() if body.skill is not None else None,
            principal=str(principal.get("id") or "unknown"),
        )

    @admin_r.get("/documents/tasks")
    async def documents_task_list(
        store: str | None = None,
        status: str | None = None,
        sc: ServiceContext = Depends(get_sc),
    ):
        return await sc.documents.tasks.list_tasks(store, status)

    @admin_r.get("/documents/tasks/{task_id}")
    async def documents_task_detail(task_id: int, sc: ServiceContext = Depends(get_sc)):
        return await sc.documents.tasks.detail(task_id)

    @admin_r.post("/documents/tasks/{task_id}/run")
    async def documents_task_run(
        task_id: int,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        return await sc.documents.tasks.run(task_id, str(principal.get("id") or "unknown"))

    @admin_r.patch("/documents/tasks/{task_id}")
    async def documents_task_save(
        task_id: int,
        body: DocumentGraphBody,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        return await sc.documents.tasks.save_graph(task_id, body.graph, str(principal.get("id") or "unknown"))

    @admin_r.post("/documents/tasks/{task_id}/confirm")
    async def documents_task_confirm(
        task_id: int,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        return await sc.documents.tasks.confirm(task_id, str(principal.get("id") or "unknown"))

    @admin_r.patch("/documents/tasks/{task_id}/config")
    async def documents_task_config(
        task_id: int,
        body: DocumentTaskConfigBody,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        return await sc.documents.tasks.reconfigure(
            task_id,
            scope=body.scope.model_dump(),
            skill=body.skill.model_dump(),
            principal=str(principal.get("id") or "unknown"),
        )

    @admin_r.post("/documents/tasks/{task_id}/rerun")
    async def documents_task_rerun(
        task_id: int,
        sc: ServiceContext = Depends(get_sc),
        principal: dict = Depends(get_principal),
    ):
        return await sc.documents.tasks.rerun(task_id, str(principal.get("id") or "unknown"))
