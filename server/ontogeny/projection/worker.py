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
"""Projection worker: outbox consumer + full rebuild, engine-agnostic.

The worker encodes the *policy* of graph projection (whitelists, event
handling, link re-emission, backfill) against a narrow ``GraphStore``
interface. Concrete stores live in ``extensions/`` (``graph-hugegraph``
ships with the repo) and are injected via ``sc.graph_store_factory``; with no
graph extension loaded the platform degrades to SQL-only by design.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from ..action.models import OutboxRow

log = logging.getLogger("ontogeny.projection")


class GraphStore(Protocol):
    """Structural contract for a projected-graph backend.

    Implemented by the graph extension's client; the worker and the preview
    endpoints call exactly this surface, so a new graph engine is a new
    extension rather than a core change.
    """

    async def ensure_graph(self) -> bool:
        """Create this domain's graph on the server if it is absent. True = created.

        HugeGraph does not create a graph on first write, so a build must ask for
        it explicitly — the difference between "no graph yet" and "cannot build"
        is exactly this call.
        """
        ...

    async def ensure_schema(self, schema: dict[str, Any]) -> None: ...

    async def exists(self) -> bool | None:
        """Whether this graph exists on the server yet (``None`` = cannot tell).

        The load-vs-build decision: an existing graph is *loaded* (its contents
        are the answer, and rebuilding would throw them away), a missing one is
        built. ``None`` must not be treated as "absent" — offering a destructive
        build because a probe failed is worse than saying "unknown".
        """
        ...

    async def clear(self) -> None:
        """Drop every vertex and edge in the graph, keeping its schema.

        A rebuild's first step. Without it a rebuild only ever *adds*: rows that
        the previous package projected stay in the graph forever, so the graph
        keeps answering with objects the platform no longer has.
        """
        ...

    async def dialect(self) -> str: ...

    async def labels(self) -> dict[str, list[dict[str, Any]]]: ...

    async def counts(self) -> dict[str, dict[str, int]]: ...

    async def sample_vertices(self, label: str, limit: int = 20) -> list[dict[str, Any]]: ...

    async def sample_edges(self, label: str, limit: int = 20) -> list[dict[str, Any]]: ...

    async def upsert_vertices(self, label: str, pk_prop: str, items: list[dict[str, Any]]) -> None: ...

    async def upsert_edges(self, link_name: str, src_label: str, dst_label: str,
                           pairs: list[tuple[str, str]]) -> None: ...

    async def delete_vertex(self, label: str, vertex_id: str) -> None: ...


class ProjectionWorker:
    """Outbox consumer: object rows -> graph vertices/edges (eventual consistency).

    Same-object events are processed strictly in outbox-id order; failures are
    retried by cursor rewind rather than skipped (at-least-once, idempotent upserts).
    """

    def __init__(self, compiled, projection, client: GraphStore) -> None:
        self.compiled = compiled
        self.projection = projection
        self.client = client

    def _whitelist(self, object_type: str) -> tuple[list[str], str]:
        cfg = self.projection.spec.include.objects[object_type]
        obj = self.compiled.objects[object_type]
        return cfg.properties, obj.spec.primaryKey[0]

    async def project_object(self, repo, session, object_type: str, obj_id: str) -> None:
        props_whitelist, pk = self._whitelist(object_type)
        row = await repo.get(session, object_type, obj_id)
        if row is None:
            await self.client.delete_vertex(object_type, str(obj_id))
            return
        item = {p: row.get(p) for p in props_whitelist}
        item[pk] = row.get(pk)
        await self.client.upsert_vertices(object_type, pk, [item])

    async def _link_pairs(self, repo, session, link_name: str,
                          *, src_id: str | None = None,
                          dst_id: str | None = None) -> list[tuple[str, str]]:
        """Edges of a projected link, from whichever store backs its join.

        Both join kinds must reach the graph: a join-table link is read from its
        relation table, an FK link from the target-side table's foreign key
        column. Returns every pair when neither side is given (full backfill).
        """
        from ..core.models import JoinTableJoin

        lnk = self.compiled.links[link_name]
        if isinstance(lnk.spec.join, JoinTableJoin):
            return await repo.link_members(session, link_name, src_id=src_id, dst_id=dst_id)
        if src_id is None and dst_id is None:
            return await repo.fk_link_pairs(session, link_name)
        if src_id is not None:
            targets = await repo.fk_linked_ids(session, link_name, src_id, from_source=True)
            return [(src_id, t) for t in targets]
        sources = await repo.fk_linked_ids(session, link_name, dst_id, from_source=False)
        return [(s, dst_id) for s in sources]

    async def _reproject_links(self, repo, session, object_type: str, obj_id: str) -> None:
        """Re-emit the edges this object participates in, either side of the link.

        An FK link whose value *moved* leaves the previous edge behind (the old
        value is not in the event); the projection is derived and rebuildable, so
        a full rebuild is the consistency backstop for that case.
        """
        for link_name in self.projection.spec.include.links:
            lnk = self.compiled.links[link_name]
            pairs: list[tuple[str, str]] = []
            if object_type == lnk.spec.source:
                pairs += await self._link_pairs(repo, session, link_name, src_id=obj_id)
            if object_type == lnk.spec.target:
                pairs += await self._link_pairs(repo, session, link_name, dst_id=obj_id)
            if pairs:
                await self.client.upsert_edges(
                    link_name, lnk.spec.source, lnk.spec.target, pairs,
                )

    async def handle_event(self, repo, session, event: OutboxRow) -> bool:
        object_type = event.object_type
        if object_type not in self.projection.spec.include.objects:
            return True  # not projected: consumed silently
        try:
            if event.op == "archive":
                await self.client.delete_vertex(object_type, str(event.object_id))
                return True
            await self.project_object(repo, session, object_type, str(event.object_id))
            await self._reproject_links(repo, session, object_type, str(event.object_id))
            return True
        except Exception as exc:  # noqa: BLE001 -- worker must never crash the pipeline
            log.warning("projection failed for %s/%s: %s", object_type, event.object_id, exc)
            return False

    async def rebuild(self, repo, session, sync_engine=None) -> dict[str, int]:
        """Full backfill from the authoritative object tables (drop-and-rebuild)."""
        counts = {"vertices": 0, "edges": 0}
        for object_type in self.projection.spec.include.objects:
            props_whitelist, pk = self._whitelist(object_type)
            rows, total = await repo.query(session, object_type, limit=10000)
            items = []
            for row in rows:
                item = {p: row.get(p) for p in props_whitelist}
                item[pk] = row.get(pk)
                items.append(item)
            await self.client.upsert_vertices(object_type, pk, items)
            counts["vertices"] += len(items)
        for link_name in self.projection.spec.include.links:
            lnk = self.compiled.links[link_name]
            pairs = await self._link_pairs(repo, session, link_name)
            if not pairs:
                continue
            await self.client.upsert_edges(link_name, lnk.spec.source, lnk.spec.target, pairs)
            counts["edges"] += len(pairs)
        return counts
