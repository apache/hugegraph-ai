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
"""Read/model surfaces: meta, objects, actions, functions, graph."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from ..errors import OOError
from ..service import ServiceContext
from .deps import get_principal, get_sc, require_admin
from .schemas import (ActionBody, AggregateBody, ExploreBody, FunctionBody,
                      FunctionSourceBody, FunctionTestBody, QueryBody, TraverseBody)


def register(r: APIRouter, sc: ServiceContext) -> None:
    @r.get("/meta/ontology")
    async def meta(sc: ServiceContext = Depends(get_sc)):
        return sc.compiled.to_meta()

    @r.get("/meta/storage")
    async def meta_storage(sc: ServiceContext = Depends(get_sc)):
        """Where materialized object data physically lives: the platform's own
        database (kind + file/DSN, credentials redacted), each object's
        ``ontogeny_obj_<type>`` table, its backing store / source table / sync
        strategy, and a best-effort live row count. This is what lets the
        console say exactly where the data landed, next to every
        "materialized" label."""
        summary = sc.storage_summary()
        # HugeGraph is a derived, optional projection layer — reported as its
        # own "current storage" line when a projection is declared AND the
        # graph extension/endpoint are actually wired (otherwise SQL-only).
        first_prj = next(iter(sc.compiled.projections.values()), None) if sc.compiled else None
        summary["graph"] = {
            "declared": first_prj is not None,
            "wired": sc.projection_worker is not None,
            "engine": (first_prj.spec.engine if first_prj is not None else None),
            "graph": (first_prj.spec.graph if first_prj is not None else None),
            "endpoint_configured": bool(sc.settings.env.get("HUGEGRAPH_URL") or os.environ.get("HUGEGRAPH_URL")),
            "endpoint": (sc._graph_endpoint() or None),
            # WHY the graph layer is not wired (None = it is): lets the console
            # say "pick HugeGraph as provider" / "fix the URL" / "load the
            # extension" instead of a generic "not configured".
            "provider": sc._storage_provider(),
            "blocked_by": sc.projection_blocked_by,
        }
        if sc.engine is not None:
            from sqlalchemy import text

            for name, info in summary["objects"].items():
                try:
                    async with sc.sessionmaker() as s:
                        row = await s.execute(text(f'SELECT COUNT(*) FROM "{info["table"]}"'))
                        info["rows"] = int(row.scalar_one())
                except Exception:  # noqa: BLE001 -- table may not exist yet (never synced)
                    info["rows"] = None
        return summary

    @r.get("/meta/lineage")
    async def lineage(sc: ServiceContext = Depends(get_sc)):
        async with sc.sessionmaker() as s:
            return await sc.registry.lineage(s)

    # ---- objects ----------------------------------------------------------

    @r.post("/objects/{object_type}/query")
    async def query_objects(object_type: str, body: QueryBody,
                            sc: ServiceContext = Depends(get_sc), principal: dict = Depends(get_principal)):
        import time

        started = time.perf_counter()
        try:
            async with sc.sessionmaker() as s:
                out = await sc.query.query(
                    s, object_type, principal, filt=body.filter, sort=body.sort,
                    limit=body.limit, offset=body.offset, links=body.links,
                )
                await sc.telemetry.record_query(
                    s, object_type, principal, body.filter, out["latency_ms"], out["total"],
                )
                await s.commit()
            return out
        except OOError:
            # failed queries are fitness signal too (unmapped fields, bad shapes)
            async with sc.sessionmaker() as s:
                await sc.telemetry.record_query(
                    s, object_type, principal, body.filter,
                    (time.perf_counter() - started) * 1000, 0, error=True,
                )
                await s.commit()
            raise

    @r.get("/objects/{object_type}/{object_id}")
    async def get_object(object_type: str, object_id: str,
                         sc: ServiceContext = Depends(get_sc), principal: dict = Depends(get_principal)):
        async with sc.sessionmaker() as s:
            return await sc.query.get(s, object_type, object_id, principal)

    @r.get("/objects/{object_type}/{object_id}/links/{link_name}")
    async def get_links(object_type: str, object_id: str, link_name: str,
                        sc: ServiceContext = Depends(get_sc), principal: dict = Depends(get_principal)):
        async with sc.sessionmaker() as s:
            return await sc.query.links(s, object_type, object_id, link_name, principal)

    @r.post("/objects/{object_type}/aggregate")
    async def aggregate(object_type: str, body: AggregateBody,
                        sc: ServiceContext = Depends(get_sc), principal: dict = Depends(get_principal)):
        async with sc.sessionmaker() as s:
            return {"value": await sc.query.aggregate(s, object_type, principal, body.fn, body.field, filt=body.filter)}

    @r.get("/objects/{object_type}/{object_id}/history")
    async def history(object_type: str, object_id: str,
                      sc: ServiceContext = Depends(get_sc), principal: dict = Depends(get_principal)):
        async with sc.sessionmaker() as s:
            rows = await sc.repo.history(s, object_type, object_id)
        # Historical versions are reads like any other: the masking the query
        # path applies used to be skipped here, so a marked property's value
        # leaked verbatim through its own version trail.
        versions = [sc.policy.mask(object_type, row, principal) for row in rows]
        return {"versions": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()} for row in versions
        ]}

    # ---- actions ----------------------------------------------------------

    @r.post("/actions/{action_name}/validate")
    async def validate_action(action_name: str, body: ActionBody,
                              sc: ServiceContext = Depends(get_sc), principal: dict = Depends(get_principal)):
        async with sc.sessionmaker() as s:
            return await sc.runtime.validate(s, action_name, principal, body.parameters, body.target_id)

    @r.post("/actions/{action_name}/execute")
    async def execute_action(action_name: str, body: ActionBody,
                             sc: ServiceContext = Depends(get_sc), principal: dict = Depends(get_principal)):
        import time

        started = time.perf_counter()
        from ..errors import PolicyDeniedError, RuleRejectedError

        async with sc.sessionmaker() as s:
            try:
                rev = await sc.runtime.execute(
                    s, action_name, principal, body.parameters, body.target_id,
                    expected_revision=body.expected_revision, idempotency_key=body.idempotency_key,
                )
                await s.commit()
                await sc.telemetry.record_action(
                    s, action_name, rev.outcome, duration_ms=(time.perf_counter() - started) * 1000,
                )
                await s.commit()
                return {"revision_id": rev.id, "outcome": rev.outcome, "object_id": rev.object_id,
                        "after": rev.after, "message": rev.message}
            except RuleRejectedError:
                # the runtime already committed the rejection revision; record the
                # outcome for the evolution loop and surface the error. The two
                # rejection classes are different findings downstream (the
                # rule-reject detector counts `rejected_rule` specifically), and
                # both were collapsed into "rejected" here, which starved it.
                await sc.telemetry.record_action(s, action_name, "rejected_rule", duration_ms=(time.perf_counter() - started) * 1000)
                await s.commit()
                raise
            except PolicyDeniedError:
                await sc.telemetry.record_action(s, action_name, "denied_policy", duration_ms=(time.perf_counter() - started) * 1000)
                await s.commit()
                raise

    # ---- functions --------------------------------------------------------

    @r.post("/functions/{name}/invoke")
    async def invoke_function(name: str, body: FunctionBody,
                              sc: ServiceContext = Depends(get_sc), principal: dict = Depends(get_principal)):
        fn = sc.compiled.functions.get(name)
        if fn is None:
            raise HTTPException(404, f"unknown function {name!r}")
        if body.version is not None:
            current = sc.compiled.function_versions.get(name)
            if current is not None and body.version != current:
                from ..errors import ConflictError

                raise ConflictError(
                    f"pinned version {body.version!r} no longer matches the deployed logic ({current!r})",
                    details={"pinned": body.version, "current": current},
                )
        async with sc.sessionmaker() as s:
            value = await sc.functions.run(s, fn, body.parameters)
        return {"value": value}

    @r.get("/functions/{name}/source")
    async def function_source(name: str, sc: ServiceContext = Depends(get_sc)):
        """What actually runs for this function — read-only.

        A **code** function's DSL only *names* its file (``spec.entry``:
        ``file.py:function``); the code lives in the package
        (``<package_root>/functions/``). The console asks this to answer "what
        runs here?", and ``exists`` matters as much as the text: a function
        created on the canvas points at a file nobody has written yet, and
        without this the only symptom was an opaque sandbox failure at invoke
        time.

        A **declarative** function has no file at all — its body is the spec — so
        this reports ``runtime: declarative`` and no path, which is the honest
        answer to the same question.
        """
        from ..functions.sandbox import function_source_path

        fn = sc.compiled.functions.get(name)
        if fn is None:
            raise HTTPException(404, f"unknown function {name!r}")
        common = {
            "name": name,
            "runtime": fn.spec.runtime,
            "entry": fn.spec.entry,
            "capabilities": [c.model_dump(exclude_none=True) for c in fn.spec.capabilities],
        }
        if fn.spec.runtime == "declarative":
            return {**common, "path": None, "exists": True, "source": None,
                    "steps": [s.model_dump(exclude_none=True) for s in fn.spec.steps],
                    "returns_step": fn.spec.returns_step}
        path = function_source_path(sc.compiled, fn)
        exists = path.is_file()
        source = path.read_text(encoding="utf-8") if exists else None
        # who changed it, when, and from which version — the same audit trail the
        # Audit page reads, filtered to this function's source edits
        revisions = await sc.function_source_revisions(name, limit=10)
        return {**common, "path": str(path), "exists": exists, "source": source,
                "revisions": revisions}

    @r.put("/functions/{name}/source")
    async def function_source_save(body: FunctionSourceBody, name: str,
                                   principal: dict = Depends(require_admin),
                                   sc: ServiceContext = Depends(get_sc)):
        """Write a function's code from the console, check it, publish it.

        Administrator-only, and deliberately so: this is the one endpoint that
        turns "can reach the console" into "can run arbitrary code on the
        platform". The sandbox and the declared capabilities still bound what
        that code can DO — this only widens who may write it, which is why the
        gate is the platform-admin flag rather than an ordinary role.

        Order matters: syntax is checked *before* anything is written, so a typo
        can never leave the package in a state that will not import; the publish
        that follows is the same validate-then-compile every other edit goes
        through, and it is what makes the change real.
        """
        return await sc.save_function_source(
            name, body.source, principal=principal,
        )

    @r.post("/functions/{name}/test")
    async def function_source_test(body: FunctionTestBody, name: str,
                                   principal: dict = Depends(require_admin),
                                   sc: ServiceContext = Depends(get_sc)):
        """Run the editor's code once — no file write, no publish, no revision.

        Administrator-only for the same reason the save endpoint is: this
        executes arbitrary code, and the fact that nothing persists does not
        make it safer to run. Errors come back as ``ok: false`` with the
        function's own failure message, plus the inputs the run invented, so
        the result is readable without guessing what was passed in.
        """
        return await sc.test_function_source(name, body.source)

    @r.get("/functions/{name}/versions")
    async def function_versions(name: str, sc: ServiceContext = Depends(get_sc)):
        current = sc.compiled.function_versions.get(name)
        if current is None:
            raise HTTPException(404, f"no deployed version for {name!r} (package not on disk?)")
        return {"name": name, "current": current}

    # ---- graph ------------------------------------------------------------

    @r.post("/graph/traverse")
    async def traverse(body: TraverseBody, sc: ServiceContext = Depends(get_sc),
                       principal: dict = Depends(get_principal)):
        async with sc.sessionmaker() as s:
            return await sc.query.traverse(
                s, body.start_type, body.start_ids, principal, body.path, max_depth=body.max_depth,
            )

    @r.post("/graph/explore")
    async def graph_explore(body: ExploreBody, sc: ServiceContext = Depends(get_sc),
                            principal: dict = Depends(get_principal)):
        """One node plus N neighbours, depth-first expansion. Omit start to pick
        a uniformly random live node (pass `seed` for a reproducible pick)."""
        start = (body.start_type, body.start_id) if body.start_type and body.start_id else None
        async with sc.sessionmaker() as s:
            return await sc.query.explore(s, start, principal,
                                          n=body.n, max_depth=body.max_depth, seed=body.seed)

    @r.post("/graph/algorithm")
    async def algorithm(body: dict, sc: ServiceContext = Depends(get_sc)):
        if sc.projection_client is None:
            raise HTTPException(501, "graph algorithms require the HugeGraph projection (not declared)")
