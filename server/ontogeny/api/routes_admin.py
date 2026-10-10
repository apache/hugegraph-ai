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
"""Platform administration: roles, assistant, domains, publish, builder."""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..builder_ops import builder_save
from ..errors import DSLValidationError, OOError
from ..llm import extract_json
from ..service import ServiceContext
from .deps import get_sc, require_admin, require_authenticated
from .schemas import (AssistantBody, BuilderSaveBody, DomainActivateBody,
                      DomainCreateBody, MountBody, ProjectionScaffoldBody,
                      PublishBody, RoleBody, RoleDeleteBody)


def register(r: APIRouter, admin_r: APIRouter, sc: ServiceContext) -> None:
    from fastapi.responses import JSONResponse as _JR

    # ---- roles & permissions (compiled INTO the policy plane) -------------

    def _role_context(sc: ServiceContext):
        """Everything the matrix needs: what the policies grant, which roles
        exist, and which actions can be granted at all."""
        from ..auth import parse_grants

        c = sc.compiled
        grants = parse_grants(dict(c.cedar_texts)) if c else []
        actions = sorted(c.actions) if c else []
        declared = sorted({r for text in (c.cedar_texts.values() if c else [])
                           for r in re.findall(r'Role::"([A-Za-z0-9_-]+)"', text)})
        return grants, actions, declared

    @r.get("/admin/roles")
    async def admin_roles(principal: dict = Depends(require_admin),
                          sc: ServiceContext = Depends(get_sc)):
        """The role × action matrix, read out of the compiled Cedar."""
        from ..auth import effective_matrix, role_catalogue

        grants, actions, declared = _role_context(sc)
        user_roles = await sc.auth.user_roles()
        catalogue = role_catalogue(grants, user_roles=user_roles, declared_roles=declared)
        current_roles = set(principal.get("Role") or principal.get("roles") or [])
        for role in catalogue:
            role["members"] = await sc.auth.users_with_role(role["name"])
            role["current"] = role["name"] in current_roles
            # A hand-written Cedar permit cannot be revoked from here; deleting
            # a non-managed policy role would only remove it from accounts while
            # the permit silently keeps granting it. Preset/admin roles are
            # protected because they anchor the deployment.
            role["deletable"] = bool(
                role["name"] != "admin"
                and (role["hasManagedPolicy"] or "policy" not in role["sources"])
            )
        return {
            "roles": catalogue,
            "actions": actions,
            "matrix": effective_matrix(grants, [r["name"] for r in catalogue], actions),
            # a role may also be granted by a hand-written policy, which this
            # surface can show but must never claim to revoke
            "grants": [
                {"policy": g.policy, "roles": g.roles, "actions": g.actions,
                 "conditional": g.conditional, "managed": g.managed}
                for g in grants
            ],
        }

    @r.put("/admin/roles/{name}")
    async def admin_role_save(name: str, body: RoleBody, _: dict = Depends(require_admin),
                              sc: ServiceContext = Depends(get_sc)):
        """Write a role's grants as its managed Cedar policy set.

        Goes through the ordinary builder save: same YAML on disk, same
        validation, same publish, same audit. The engine then enforces it like
        any other policy — there is no second permission table to consult.
        """
        from ..auth import compile_role_policy, managed_policy_name, slug_conflicts

        grants, _actions, declared = _role_context(sc)
        known = sorted({*declared, *(r["name"] for r in
                        (await admin_roles(_, sc))["roles"])} - {name})
        clashes = [pair for pair in slug_conflicts([name, *known]) if name in pair]
        if clashes:
            raise DSLValidationError(
                f"role name {name!r} would share a policy file with {clashes[0][0]!r}; "
                "rename one of them (underscores and dashes must not collide)")

        resources = [{
            "apiVersion": "ontogeny/v1",
            "kind": "PolicySet",
            "metadata": {"name": managed_policy_name(body.name),
                         "display": f"{body.name} 角色授权"},
            "spec": {"language": "cedar",
                     "source": compile_role_policy(body.name, body.actions, site=body.site)},
        }]
        result = await builder_save(sc, resources)
        return {"saved": managed_policy_name(body.name), "actions": sorted(set(body.actions)),
                "publish": result}

    @r.delete("/admin/roles/{name}")
    async def admin_role_delete(name: str, body: RoleDeleteBody, _: dict = Depends(require_admin),
                                sc: ServiceContext = Depends(get_sc)):
        """Drop a role: delete its managed policy set and move its holders on.

        The accounts that carried it are reassigned (or cleared) in the same
        call, because a role that no longer exists but is still listed on a user
        is exactly the state that makes "why can't this person do anything?"
        unanswerable.
        """
        from ..auth import managed_policy_name

        catalogue = (await admin_roles(_, sc))["roles"]
        info = next((r for r in catalogue if r["name"] == name), None)
        if info is not None and not info.get("deletable", True):
            raise DSLValidationError(
                f"role {name!r} is preset or granted by a hand-written policy; it cannot be deleted here"
            )
        holders = await sc.auth.users_with_role(name)
        for username in holders:
            user = next((u for u in await sc.auth.list_users() if u["username"] == username), None)
            roles = [r for r in (user or {}).get("roles", []) if r != name]
            if body.reassign_to and body.reassign_to not in roles:
                roles.append(body.reassign_to)
            await sc.auth.update_user(username, {"roles": roles})
        result = await builder_save(
            sc, [], deletes=[f"PolicySet/{managed_policy_name(name)}"])
        return {"deleted": name, "reassigned": holders, "publish": result}
    # ---- assistant (Ollama-backed, ontology-grounded) ----------------------

    @r.post("/assistant/chat")
    async def assistant_chat(body: AssistantBody, sc: ServiceContext = Depends(get_sc),
                             _: dict = Depends(require_authenticated)):
        if sc.llm is None or sc.compiled is None:
            raise HTTPException(503, "assistant requires ONTOGENY_LLM_BASE_URL (Ollama) to be configured")
        meta = sc.compiled.to_meta()
        grounding = (
            "You are the assistant of an operational ontology platform. Answer using ONLY this "
            f"ontology snapshot for facts (package {meta['package']}):\n"
            + json.dumps(meta, ensure_ascii=False, default=str)
        )
        messages = [{"role": "system", "content": grounding}, *body.messages]
        if body.propose:
            messages.append({
                "role": "system",
                "content": (
                    "PROPOSE MODE: end your answer with strict JSON describing ONE mutation: "
                    '{"mutations": [{"mutation": "add-optional-property"|"enum-widen", "object": "...", '
                    '"prop": "...", "type"|"value": "..."}], "rationale": "..."}'
                ),
            })
        out = await sc.llm.chat(messages)
        result: dict[str, Any] = {"content": out["content"]}
        if out.get("thinking"):
            result["thinking"] = out["thinking"]
        if body.propose:
            from ..llm import LLMError

            try:
                payload = extract_json(out["content"])
                if isinstance(payload, dict) and isinstance(payload.get("mutations"), list):
                    result["proposals"] = payload["mutations"]
                    result["rationale"] = payload.get("rationale")
            except LLMError:
                result["proposals"] = None
        return result

    @admin_r.get("/extensions")
    async def admin_extensions(sc: ServiceContext = Depends(get_sc)):
        """Extension inventory: what loaded, what each provides/requires, and
        which capabilities (llm, graph-store, engines) are live."""
        if sc.ext is None:
            return {"extensions": [], "capabilities": {}, "dirs": []}
        return sc.ext.records_meta()

    @admin_r.get("/llm/status")
    async def llm_status(sc: ServiceContext = Depends(get_sc)):
        if sc.llm is None:
            return {"configured": False}
        health = await sc.llm.health()
        return {"configured": True, "base_url": sc.llm.base_url, "model": sc.llm.model, **health}

    @admin_r.get("/metrics")
    async def admin_metrics(sc: ServiceContext = Depends(get_sc)):
        """Operational counters, aggregated from the platform's own tables --
        zero extra dependencies, scrape-ready for a cron/uptime check."""
        from ..metrics import collect

        return await collect(sc)

    # ---- admin ------------------------------------------------------------

    @admin_r.get("/domains")
    async def admin_domains(sc: ServiceContext = Depends(get_sc)):
        """Every switchable domain (ontology package), active one first."""
        return {
            "domains": sc.list_domains(),
            "active": sc.compiled.package_name if sc.compiled else None,
        }

    @admin_r.post("/domains")
    async def admin_domain_create(body: DomainCreateBody, sc: ServiceContext = Depends(get_sc)):
        """Create a domain (an empty ontology package scaffolded on disk); the
        console activates it right away by default, so "new domain" lands you
        inside it."""
        dom = sc.create_domain(body.name, display=body.display, description=body.description)
        if body.activate:
            compiled = await sc.activate_domain(dom["path"])
            dom["active"] = True
            dom["content_hash"] = compiled.content_hash
        return dom

    @admin_r.post("/domains/import")
    async def admin_domain_import(request: Request, activate: bool = True,
                                  principal: dict = Depends(require_admin),
                                  sc: ServiceContext = Depends(get_sc)):
        """Import a domain-package zip: validate, install, (optionally) activate.

        Administrator-only, like every domain mutation. The body is the raw zip
        (``application/zip`` / ``application/octet-stream``) rather than a
        multipart form, so no extra server dependency is needed; the frontend
        sends the picked ``File`` as the request body directly. A package that
        fails validation is refused with the validator's issue list and leaves
        nothing behind in the domains root.
        """
        data = await request.body()
        if not data:
            raise HTTPException(400, "empty body: expected a domain-package zip")
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype not in ("", "application/zip", "application/octet-stream",
                         "application/x-zip-compressed"):
            raise HTTPException(415, f"unsupported content type {ctype!r}: send the zip as the body")
        return await sc.import_domain(data, activate=activate)

    @admin_r.post("/domains/activate")
    async def admin_domain_activate(body: DomainActivateBody, sc: ServiceContext = Depends(get_sc)):
        path = sc.resolve_domain(body.name)
        compiled = await sc.activate_domain(path)
        return {"activated": True, "name": body.name, "content_hash": compiled.content_hash}

    @admin_r.post("/publish")
    async def admin_publish(body: PublishBody, sc: ServiceContext = Depends(get_sc)):
        path = body.path or sc.package_root
        if path is None:
            raise HTTPException(400, "path required")
        compiled = await sc.publish(path)
        return {"content_hash": compiled.content_hash}

    @admin_r.post("/sync/{object_type}")
    async def admin_sync(object_type: str, sc: ServiceContext = Depends(get_sc)):
        return await sc.sync(object_type)

    @admin_r.post("/outbox/dispatch")
    async def admin_dispatch(sc: ServiceContext = Depends(get_sc)):
        return await sc.outbox.dispatch_pending()

    @admin_r.post("/derive")
    async def admin_derive(sc: ServiceContext = Depends(get_sc)):
        """Force a derivation pass: deliver pending outbox events (the consumer
        queues ids), then materialize function-backed properties now."""
        await sc.outbox.dispatch_pending()
        return await sc.derivation.drain()

    # Which kinds the resource editors may load/save. Stores own connection
    # strings and AgentPlugins own plugin code, so neither is hand-edited here;
    # EvalSuites/EvolutionPolicy/Ontology have their own surfaces.
    _EDITABLE_KINDS = ("ObjectType", "LinkType", "Projection", "Action", "Function", "PolicySet")

    @admin_r.get("/builder/resources")
    async def builder_resources(sc: ServiceContext = Depends(get_sc)):
        """Raw DSL resources, for the editors.

        `/meta/ontology` is a *consumer* view and is lossy by design: it reports
        a function's capability *names* but not their values, a projection's graph
        but not its endpoint/includes/indexes, and a policy's Cedar file name but
        not its text. An editor seeded from it would silently strip those on the
        next save. This returns the compiled resources as the same
        ``{apiVersion, kind, metadata, spec}`` JSON that ``/admin/builder/save``
        accepts, so load → edit → save round-trips without loss.

        PolicySets carry their Cedar text inline under ``spec.source``; the save
        endpoint materializes it back into ``policies/<name>.cedar`` for us.
        """
        c = sc.compiled
        if c is None:
            return {"resources": [], "content_hash": None, "layout": sc.read_layout(),
                    "stores": []}
        groups = {
            "ObjectType": c.objects, "LinkType": c.links, "Action": c.actions,
            "Function": c.functions, "PolicySet": c.policies, "Projection": c.projections,
        }
        out: list[dict[str, Any]] = []
        for kind in _EDITABLE_KINDS:
            for name, res in sorted(groups[kind].items()):
                payload = res.model_dump(mode="json", by_alias=True, exclude_none=True)
                if kind == "PolicySet":
                    payload["spec"]["source"] = c.cedar_texts.get(name, res.spec.source)
                out.append(payload)
        return {"resources": out, "content_hash": c.content_hash, "layout": sc.read_layout(),
                "stores": sorted(c.stores)}

    @admin_r.post("/builder/save")
    async def builder_save_route(body: BuilderSaveBody, sc: ServiceContext = Depends(get_sc)):
        """Scenario Builder: accept resource JSON → write YAML to pkg dir → publish.

        The heavy lifting lives in ``ontogeny.builder_ops`` (shared with the role
        manager); this shell only preserves the console's legacy 422 shape for
        per-resource validation errors."""
        try:
            return await builder_save(sc, body.resources, deletes=body.deletes,
                                      layout=body.layout, story=body.story)
        except DSLValidationError as exc:
            errors = (exc.details or {}).get("errors")
            if errors:
                return _JR(status_code=422, content={"code": "BUILDER_INVALID", "errors": errors})
            raise

    @admin_r.post("/builder/mount")
    async def builder_mount(body: MountBody, sc: ServiceContext = Depends(get_sc)):
        """Scenario Builder data mounting: store resource + object backing +
        publish + sync, in one confirmed step. The core lives in
        ontogeny.demo.mounting so the demo orchestrator shares the exact path."""
        from ..demo.mounting import MountRequest, mount_source

        req = MountRequest(
            object_type=body.object,
            source_kind=body.source.kind,
            store_name=body.store,
            filename=body.source.filename,
            content=body.source.content,
            dsn=body.source.dsn,
            table=body.source.table,
            mapping=body.mapping or {},
        )
        try:
            return await mount_source(sc, req)
        except OOError as exc:
            return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    # ---- guided demo (one linear narrative, real doors only) ----------------

    @admin_r.post("/projection/rebuild")
    async def admin_projection_rebuild(sc: ServiceContext = Depends(get_sc)):
        return await sc.projection_rebuild()

    @admin_r.post("/projection/scaffold")
    async def admin_projection_scaffold(body: ProjectionScaffoldBody | None = None,
                                       sc: ServiceContext = Depends(get_sc)):
        """Declare this domain's projection, then load or build its graph.

        The console's storage card calls this when HugeGraph is selected but the
        active package declares no projection. If the domain's graph already
        exists on the server it is *loaded* (contents untouched); if it does not,
        schema is created and the object tables are backfilled.
        """
        return await sc.scaffold_projection(
            name=(body.name if body else None),
            graphspace=(body.graphspace if body else "DEFAULT"),
        )
