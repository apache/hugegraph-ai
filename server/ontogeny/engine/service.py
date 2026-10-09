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
"""Query service: object assembly (derived properties + masking), link
expansion, aggregation and multi-hop graph traversal (SQL-recursive default;
the HugeGraph projection is an accelerator behind the same API).
"""
from __future__ import annotations

import time
from typing import Any

from ..core import expr as _expr
from ..core.models import ForeignKeyJoin
from ..errors import NotFoundError, StoreError
from ..policy.engine import PolicyEngine
from ..stores.repo import ObjectRepository


def assemble_row(compiled, object_type: str, props: dict) -> dict:
    """Row props -> object props with derived values computed.

    Shared by the query API and the function sandbox: functions read the same
    shape of object a human would, so a derived property is never invisible to
    business logic (it used to read as None/0 inside the sandbox).
    """
    obj = compiled.objects.get(object_type)
    if obj is None:
        raise NotFoundError(f"unknown object type {object_type!r}")
    out = dict(props)
    ctx = _expr.ExprContext(target=props)
    for prop, pdef in obj.spec.properties.items():
        # only expression deriveds are computed at read time; function deriveds
        # are materialized columns maintained by the derivation worker
        if pdef.derived_kind() == "expr":
            try:
                out[prop] = _expr.evaluate(pdef.derived, ctx)
            except _expr.ExpressionError:
                out[prop] = None
    return out


class QueryService:
    def __init__(self, compiled, repo: ObjectRepository, policy: PolicyEngine) -> None:
        self.compiled = compiled
        self.repo = repo
        self.policy = policy

    # -------------------------------------------------------------- assembly

    def assemble(self, object_type: str, props: dict, principal: dict) -> dict:
        """Row props -> API object: derived values computed, markings applied."""
        out = assemble_row(self.compiled, object_type, props)
        return self.policy.mask(object_type, out, principal)

    async def _assemble_many(self, session, object_type: str, ids: list[str], principal: dict) -> list[dict]:
        rows = await self.repo.get_many(session, object_type, ids)
        by_pk = {}
        pk = self.compiled.objects[object_type].spec.primaryKey[0]
        for r in rows:
            by_pk[str(r.get(pk))] = r
        return [self.assemble(object_type, by_pk[i], principal) for i in ids if i in by_pk]

    # ----------------------------------------------------------------- query

    async def query(
        self, session, object_type: str, principal: dict, *,
        filt: Any = None, sort: list | None = None, limit: int = 100, offset: int = 0,
        links: list[str] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        rows, total = await self.repo.query(
            session, object_type, filt=filt, sort=sort, limit=limit, offset=offset,
        )
        objects = [self.assemble(object_type, r, principal) for r in rows]
        result: dict[str, Any] = {
            "objects": objects, "total": total,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if links:
            pk = self.compiled.objects[object_type].spec.primaryKey[0]
            expanded = {}
            for link_name in links:
                if link_name not in self.compiled.links:
                    raise NotFoundError(f"unknown link {link_name!r}")
                lnk = self.compiled.links[link_name]
                other = lnk.spec.target if lnk.spec.source == object_type else lnk.spec.source
                bucket: dict[str, list[dict]] = {}
                for obj in objects:
                    ids = await self._linked_ids(session, link_name, str(obj[pk]), from_source=lnk.spec.source == object_type)
                    bucket[str(obj[pk])] = await self._assemble_many(session, other, ids, principal)
                expanded[link_name] = bucket
            result["links"] = expanded
        return result

    async def get(self, session, object_type: str, obj_id: str, principal: dict) -> dict[str, Any]:
        row = await self.repo.get(session, object_type, obj_id)
        if row is None:
            raise NotFoundError(f"{object_type}/{obj_id} not found")
        return self.assemble(object_type, row, principal)

    async def aggregate(
        self, session, object_type: str, principal: dict, fn: str, field: str | None, *, filt: Any = None,
    ) -> float:
        if fn not in ("count", "sum", "avg", "min", "max"):
            raise StoreError(f"unknown aggregate {fn!r}")
        if field is not None:
            # Aggregation is a read of the field's values: allowing it on a
            # marked property let an anonymous caller reconstruct the masked
            # value exactly (avg/min/max answer to arbitrary precision).
            obj = self.compiled.objects.get(object_type)
            pdef = obj.spec.properties.get(field) if obj is not None else None
            if pdef is not None and pdef.marking:
                claims = set(principal.get("markings") or ())
                if pdef.marking not in claims:
                    from ..errors import PolicyDeniedError

                    raise PolicyDeniedError(
                        f"cannot aggregate {object_type}.{field}: property carries marking "
                        f"{pdef.marking!r} the principal does not hold",
                        details={"object_type": object_type, "field": field, "marking": pdef.marking},
                    )
        return float(await self.repo.aggregate(session, object_type, fn, field, filt=filt))

    # ----------------------------------------------------------------- links

    async def _linked_ids(self, session, link_name: str, obj_id: str, *, from_source: bool) -> list[str]:
        lnk = self.compiled.links[link_name]
        join = lnk.spec.join
        if isinstance(join, ForeignKeyJoin):
            return await self.repo.fk_linked_ids(session, link_name, obj_id, from_source=from_source)
        members = await self.repo.link_members(
            session, link_name, src_id=obj_id if from_source else None, dst_id=obj_id if not from_source else None,
        )
        return [dst if from_source else src for src, dst in members]

    async def links(
        self, session, object_type: str, obj_id: str, link_name: str, principal: dict,
    ) -> list[dict]:
        lnk = self.compiled.links.get(link_name)
        if lnk is None:
            raise NotFoundError(f"unknown link {link_name!r}")
        if object_type not in (lnk.spec.source, lnk.spec.target):
            raise NotFoundError(f"link {link_name!r} is not attached to {object_type}")
        other = lnk.spec.target if lnk.spec.source == object_type else lnk.spec.source
        ids = await self._linked_ids(session, link_name, obj_id, from_source=lnk.spec.source == object_type)
        return await self._assemble_many(session, other, ids, principal)

    # --------------------------------------------------------------- traverse

    # ------------------------------------------------------------ explore

    async def explore(
        self, session, start: tuple[str, str] | None, principal: dict,
        *, n: int = 12, max_depth: int = 3, seed: int | None = None,
    ) -> dict[str, Any]:
        """Neighbourhood exploration: one start node plus N nodes around it.

        ``start`` is (object_type, id); None picks a uniformly random live node
        from a random object type (seeded when ``seed`` is given, so a demo is
        reproducible). Expansion is DEPTH-FIRST: we follow one link chain as
        far as it goes before backtracking to the next branch, until ``n``
        distinct nodes are collected or the frontier is exhausted. Links are
        followed in both directions and never revisit a node.

        Returns nodes + edges (an adjacency the UI can lay out directly);
        masked properties still follow the marking rules of ``assemble``.
        """
        import random as _random

        rng = _random.Random(seed)
        if start is None:
            types = sorted(self.compiled.objects)
            if not types:
                raise StoreError("ontology has no object types")
            for _ in range(len(types) * 3):
                object_type = rng.choice(types)
                ids = await self.repo.alive_ids(session, object_type)
                if ids:
                    start = (object_type, rng.choice(sorted(ids)))
                    break
            else:
                raise StoreError("no live objects to explore (sync first?)")
        start_type, start_id = start
        n = max(1, min(int(n), 200))
        max_depth = max(1, min(int(max_depth), 6))

        pk_of = {name: obj.spec.primaryKey[0] for name, obj in self.compiled.objects.items()}
        nodes: dict[tuple[str, str], dict[str, Any]] = {}
        edges: list[dict[str, str]] = []
        seen_edge: set[tuple[str, str, str, str]] = set()

        async def add_node(object_type: str, obj_id: str) -> dict[str, Any] | None:
            key = (object_type, obj_id)
            if key in nodes:
                return nodes[key]
            row = await self.repo.get(session, object_type, obj_id)
            if row is None:
                return None
            obj = self.assemble(object_type, row, principal)
            obj["_type"] = object_type
            obj["_id"] = str(row[pk_of[object_type]])
            nodes[key] = obj
            return obj

        await add_node(start_type, start_id)

        # Depth-first with explicit frames. Each frame remembers how far through
        # its neighbour list it got: backtracking must RESUME a parent, not skip
        # it. (An "already expanded" set pops the parent on the way back up,
        # which silently truncates the walk to the first branch -- the bug this
        # replaces.)
        frames: list[dict[str, Any]] = [
            {"type": start_type, "id": start_id, "depth": 0, "neighbours": None, "cursor": 0}
        ]
        on_path: set[tuple[str, str]] = {(start_type, start_id)}

        while frames and len(nodes) < n:
            frame = frames[-1]
            key = (frame["type"], frame["id"])

            if frame["depth"] >= max_depth:
                frames.pop()
                on_path.discard(key)
                continue

            if frame["neighbours"] is None:
                found: list[tuple[str, str]] = []
                for lnk in self.compiled.links_of(frame["type"]):
                    from_source = lnk.spec.source == frame["type"]
                    other = lnk.spec.target if from_source else lnk.spec.source
                    for nid in await self._linked_ids(session, lnk.metadata.name, frame["id"], from_source=from_source):
                        okey = (other, nid)
                        edge_key = tuple(sorted((frame["id"], nid))) + (lnk.metadata.name,)
                        if edge_key not in seen_edge:
                            seen_edge.add(edge_key)
                            edges.append({
                                "link": lnk.metadata.name,
                                "source": {"type": frame["type"], "id": frame["id"]} if from_source else {"type": other, "id": nid},
                                "target": {"type": other, "id": nid} if from_source else {"type": frame["type"], "id": frame["id"]},
                            })
                        if okey not in nodes:
                            found.append(okey)
                rng.shuffle(found)  # branch ORDER is randomized; the walk is still DFS
                frame["neighbours"] = found

            advanced = False
            neighbours = frame["neighbours"] or []
            while frame["cursor"] < len(neighbours) and len(nodes) < n:
                other_type, nid = neighbours[frame["cursor"]]
                frame["cursor"] += 1
                okey = (other_type, nid)
                if okey in on_path or okey in nodes:
                    continue
                if await add_node(other_type, nid) is not None:
                    frames.append({"type": other_type, "id": nid, "depth": frame["depth"] + 1,
                                   "neighbours": None, "cursor": 0})
                    on_path.add(okey)
                    advanced = True
                    break  # descend immediately: that is what makes it depth-first

            if not advanced and frame["cursor"] >= len(neighbours):
                frames.pop()
                on_path.discard(key)

        # add_node may have raced past n; trim edges to retained nodes
        kept = set(nodes)
        edges = [e for e in edges
                 if (e["source"]["type"], e["source"]["id"]) in kept
                 and (e["target"]["type"], e["target"]["id"]) in kept]

        order = [(start_type, start_id)] + [k for k in nodes if k != (start_type, start_id)]
        return {
            "start": {"type": start_type, "id": start_id},
            "n_requested": n,
            "depth": max_depth,
            "nodes": [nodes[k] for k in order if k in nodes],
            "edges": edges,
            "truncated": len(nodes) >= n and bool(frames),
        }

    async def traverse(
        self, session, start_type: str, start_ids: list[str], principal: dict,
        path: list[dict], *, max_depth: int = 3,
    ) -> dict[str, Any]:
        """Multi-hop traversal. path = [{"link": name, "direction": "out"|"in"}, ...]
        Executed via SQL/link tables (the projection accelerates the same API).
        Returns per-step objects AND the edges between consecutive steps, so a
        UI can lay the walk out as a graph without re-deriving adjacency."""
        if len(path) > max_depth:
            raise StoreError(f"traversal depth {len(path)} exceeds max_depth {max_depth}")
        current_type = start_type
        current_ids = list(dict.fromkeys(str(i) for i in start_ids))
        steps: list[dict[str, Any]] = [{
            "type": current_type, "ids": current_ids,
            "objects": await self._assemble_many(session, current_type, current_ids, principal),
        }]
        edges: list[dict[str, Any]] = []
        for hop in path:
            link_name = hop.get("link")
            direction = hop.get("direction", "out")
            lnk = self.compiled.links.get(str(link_name))
            if lnk is None:
                raise NotFoundError(f"unknown link {link_name!r}")
            if current_type not in (lnk.spec.source, lnk.spec.target):
                raise StoreError(f"link {link_name!r} not attached to {current_type}")
            # side is determined by which endpoint current_type is; `direction`
            # is a consistency assertion, not the source of truth
            from_source = lnk.spec.source == current_type
            if (direction == "out") != from_source:
                raise StoreError(
                    f"link {link_name!r}: direction {direction!r} contradicts the endpoint side of {current_type!r}"
                )
            nxt: list[str] = []
            for oid in current_ids:
                targets = await self._linked_ids(session, str(link_name), oid, from_source=from_source)
                for tid in targets:
                    edges.append({
                        "link": str(link_name),
                        "source": {"type": current_type, "id": oid},
                        "target": {"type": lnk.spec.target if from_source else lnk.spec.source, "id": tid},
                    })
                nxt.extend(targets)
            current_type = lnk.spec.target if from_source else lnk.spec.source
            current_ids = list(dict.fromkeys(nxt))
            steps.append({
                "type": current_type, "ids": current_ids,
                "objects": await self._assemble_many(session, current_type, current_ids, principal),
            })
        # keep only edges whose both ends are assembled (targets may fall off
        # the returned step objects when filtering removes readability)
        returned = {(st["type"], str(o[pk])) for st, pk in
                    ((st, self.compiled.objects[st["type"]].spec.primaryKey[0]) for st in steps)
                    for o in st["objects"]}
        edges = [e for e in edges
                 if (e["source"]["type"], e["source"]["id"]) in returned
                 and (e["target"]["type"], e["target"]["id"]) in returned]
        return {"steps": steps, "edges": edges, "final_ids": current_ids}
