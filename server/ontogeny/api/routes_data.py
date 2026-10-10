# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Data preview, graph projection views, audit trail and SSE subscriptions."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..action.models import RevisionRow
from ..service import ServiceContext
from .deps import get_principal, get_sc, require_authenticated


def register(app: FastAPI, r: APIRouter, sc: ServiceContext) -> None:
    # ---- data preview -----------------------------------------------------
    # The graph is a derived index, so nothing here bypasses the query engine:
    # object rows come straight from it, and graph rows are ids re-assembled
    # through it (marking masks and derived properties apply as everywhere else).

    @r.get("/data/preview")
    async def data_preview(limit: int = 3, sc: ServiceContext = Depends(get_sc),
                           principal: dict = Depends(get_principal)):
        return await sc.data_preview(principal, limit=max(1, min(limit, 50)))

    @r.get("/graph/projection")
    async def projection_summary(sc: ServiceContext = Depends(get_sc)):
        return await sc.projection_summary()

    @r.get("/graph/projection/vertices")
    async def projection_vertices(label: str, limit: int = 20, sc: ServiceContext = Depends(get_sc),
                                  principal: dict = Depends(get_principal)):
        return await sc.projection_vertices(label, principal, limit=max(1, min(limit, 200)))

    @r.get("/graph/projection/edges")
    async def projection_edges(label: str, limit: int = 20, sc: ServiceContext = Depends(get_sc),
                               principal: dict = Depends(get_principal)):
        return await sc.projection_edges(label, principal, limit=max(1, min(limit, 200)))

    # ---- audit ------------------------------------------------------------


    @r.get("/audit/revisions")
    async def audit(object_type: str | None = None, object_id: str | None = None,
                    action: str | None = None, limit: int = 50,
                    sc: ServiceContext = Depends(get_sc),
                    _: dict = Depends(require_authenticated)):
        async with sc.sessionmaker() as s:
            stmt = select(RevisionRow).order_by(RevisionRow.id.desc()).limit(limit)
            if object_type:
                stmt = stmt.where(RevisionRow.object_type == object_type)
            if object_id:
                stmt = stmt.where(RevisionRow.object_id == object_id)
            if action:
                stmt = stmt.where(RevisionRow.action == action)
            rows = (await s.execute(stmt)).scalars().all()
        return {"revisions": [{
            "id": x.id, "action": x.action, "object_type": x.object_type, "object_id": x.object_id,
            "principal": x.principal, "outcome": x.outcome, "message": x.message,
            "created_at": x.created_at.isoformat() if x.created_at else None,
        } for x in rows]}

    # ---- subscriptions (SSE) ----------------------------------------------

    @app.get("/api/v1/subscriptions/objects/{object_type}")
    async def subscribe(object_type: str, _: dict = Depends(require_authenticated)):
        """Live change feed. Authenticated like every non-public surface, and
        carrying only identifiers: the outbox payload holds full property
        values, which would bypass the read path's masking."""

        q = sc.sse.subscribe()

        async def stream():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event.get("object_type") == object_type:
                        yield f"data: {json.dumps(event, default=str)}\n\n"
            finally:
                sc.sse.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream")
