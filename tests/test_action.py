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
"""Kinetic layer end-to-end: rules, policy, effects, audit, idempotency,
optimistic locking, outbox webhook delivery -- exercised against the
product-manufacturing domain (release a production order as the planner)."""
from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
import pytest_asyncio
import httpx

from ontogeny.action import ActionRuntime, OutboxDispatcher, SseBroker
from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.db import init_schema, make_engine, make_sessionmaker
from ontogeny.errors import ConflictError, PolicyDeniedError, RuleRejectedError, TypeMismatchError
from ontogeny.policy import PolicyEngine
from ontogeny.registry import RegistryService
from ontogeny.stores import ObjectRepository, SyncEngine
from ontogeny.stores.sources import make_source

PLANNER = {"id": "u-planner", "Role": {"planner"}, "site": "plant-north"}
OUTSIDER = {"id": "u-out", "Role": {"visitor"}, "site": "south"}


@pytest_asyncio.fixture()
async def env(golden_pkg_path, tmp_path):
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL (same path the
    # demo bootstrap uses), so tests always agree with the shipped example
    from ontogeny.demo.bootstrap import seed_from_package

    seed_from_package(golden_pkg_path, src, force=True)

    settings = Settings(
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}", "WMS_WEBHOOK": "https://wms.example.test/hook"},
        webhook_allowlist=("wms.example.test",),
    )
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    maker = make_sessionmaker(engine)
    pkg = load_package(golden_pkg_path)
    async with maker() as s:
        compiled = await RegistryService().publish(s, pkg)
        await s.commit()
    repo = ObjectRepository(compiled)
    sync = SyncEngine(compiled, settings, repo,
                      lambda st: make_source(st, settings.resolve_env_ref(st.spec.connection)))
    async with maker() as s:
        await repo.ensure(s)
        for object_type in compiled.objects:
            await sync.sync(s, object_type)
        await s.commit()
    policy = PolicyEngine(compiled)
    runtime = ActionRuntime(compiled, repo, policy, settings)
    yield {"maker": maker, "compiled": compiled, "repo": repo, "policy": policy,
           "runtime": runtime, "settings": settings}
    await engine.dispose()


@pytest_asyncio.fixture()
async def link_env(tmp_path):
    """A minimal package for the one effect product-manufacturing does not
    exercise: set-link over an ontology-owned join table."""

    root = tmp_path / "link-pkg"
    root.mkdir()
    (root / "ontology.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Ontology\nmetadata: {name: link-join-demo}\n"
        "spec: {imports: []}\n",
        encoding="utf-8",
    )
    (root / "stores").mkdir()
    (root / "stores" / "mes.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Store\nmetadata: {name: mes}\n"
        "spec: {type: sqlite, connection: '${ERP_DSN}', access: read-write}\n",
        encoding="utf-8",
    )
    (root / "objects").mkdir()
    for name, table in (("container", "containers"), ("item", "items")):
        (root / "objects" / f"{name}.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: ObjectType\n"
            f"metadata: {{name: {name}}}\n"
            "spec:\n"
            f"  primaryKey: [{name}_id]\n"
            "  properties:\n"
            f"    {name}_id: {{type: string, required: true}}\n"
            "    name: {type: string}\n"
            "  backing:\n"
            "    store: mes\n"
            "    mode: materialized\n"
            "    source: {schema: mes, table: " + table + "}\n"
            "    mapping: {}\n",
            encoding="utf-8",
        )
    (root / "links").mkdir()
    (root / "links" / "container-items.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: LinkType\nmetadata: {name: container-items}\n"
        "spec:\n"
        "  source: container\n"
        "  target: item\n"
        "  cardinality: MANY_TO_MANY\n"
        "  join:\n"
        "    kind: join-table\n"
        "    store: mes\n"
        "    relation: {schema: mes, table: container_items}\n"
        "    keys:\n"
        "      source: {container_id: container_id}\n"
        "      target: {item_id: item_id}\n",
        encoding="utf-8",
    )
    (root / "actions").mkdir()
    (root / "actions" / "attach-item.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Action\nmetadata: {name: attach-item}\n"
        "spec:\n"
        "  target: container\n"
        "  parameters:\n"
        "    item_id: {type: string, required: true}\n"
        "  effects:\n"
        "  - kind: set-link\n"
        "    link: container-items\n"
        "    add:\n"
        "    - item_id: parameters.item_id\n"
        "    remove: []\n",
        encoding="utf-8",
    )
    (root / "policies").mkdir()
    (root / "policies" / "default.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: PolicySet\nmetadata: {name: default}\n"
        "spec: {language: cedar, source: default.cedar}\n",
        encoding="utf-8",
    )
    (root / "policies" / "default.cedar").write_text(
        'permit(principal, action == Action::"attach-item", resource);\n',
        encoding="utf-8",
    )

    src = tmp_path / "link.db"
    con = sqlite3.connect(str(src))
    con.executescript(
        """
        CREATE TABLE containers (container_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE items (item_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE container_items (container_id TEXT, item_id TEXT);
        INSERT INTO containers VALUES ('C-1', 'Crate');
        INSERT INTO items VALUES ('I-1', 'Bolt');
        INSERT INTO items VALUES ('I-2', 'Nut');
        """
    )
    con.commit()
    con.close()

    settings = Settings(env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"})
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    maker = make_sessionmaker(engine)
    pkg = load_package(str(root))
    async with maker() as s:
        compiled = await RegistryService().publish(s, pkg)
        await s.commit()
    repo = ObjectRepository(compiled)
    sync = SyncEngine(compiled, settings, repo,
                      lambda st: make_source(st, settings.resolve_env_ref(st.spec.connection)))
    async with maker() as s:
        await repo.ensure(s)
        await sync.sync(s, "container")
        await sync.sync(s, "item")
        await s.commit()
    policy = PolicyEngine(compiled)
    runtime = ActionRuntime(compiled, repo, policy, settings)
    yield {"maker": maker, "compiled": compiled, "repo": repo,
           "runtime": runtime, "settings": settings}
    await engine.dispose()


async def _release_high_priority_order(env) -> str:
    """Create and release a HIGH priority order: the release action carries a
    conditional webhook effect for exactly that case, so this is how a webhook
    lands in the outbox."""
    async with env["maker"]() as s:
        created = await env["runtime"].execute(
            s, "create-production-order", PLANNER,
            {"product_id": "P-100", "qty": 1, "priority": "HIGH"})
        await env["runtime"].execute(s, "release-production-order", PLANNER, {},
                                     created.object_id)
        await s.commit()
    return created.object_id


class TestPolicyEngine:
    def test_parse_and_decide(self, env):
        pol = env["policy"]
        d1 = pol.decide(PLANNER, "release-production-order", {"status": "PLANNED"})
        assert d1.allow
        d2 = pol.decide(PLANNER, "release-production-order", {"status": "RELEASED"})
        assert not d2.allow  # when-clause fails -> default deny
        d3 = pol.decide(OUTSIDER, "release-production-order", {"status": "PLANNED"})
        assert not d3.allow  # role mismatch

    def test_the_package_default_policy_is_explicit_deny(self, golden_pkg_path, tmp_path):
        """An action that names no policy set falls through to the package
        default -- which product-manufacturing ships as explicit DENY (safe
        production default), not as an implicit permit."""
        import shutil
        from pathlib import Path

        from ontogeny.registry.compiled import compile_package

        root = tmp_path / "p"
        shutil.rmtree(root, ignore_errors=True)
        shutil.copytree(golden_pkg_path, root)
        (Path(root) / "actions" / "adhoc-note.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Action\nmetadata: {name: adhoc-note}\n"
            "spec:\n  target: production-order\n"
            "  effects:\n  - {kind: webhook, url: 'https://notes.example.test/hook'}\n",
            encoding="utf-8",
        )
        pol = PolicyEngine(compile_package(load_package(str(root))))
        assert not pol.decide(PLANNER, "adhoc-note", None).allow
        assert not pol.decide(OUTSIDER, "adhoc-note", None).allow

    def test_a_permit_in_any_policy_set_grants(self, env):
        """Cedar: the policy store is a SET of policies and any permit grants.

        The engine used to consult only the set an action names in
        ``spec.policy``, so a permit written anywhere else was compiled,
        published and then never read. The role manager generates exactly such a
        set (one per role), which is how this surfaced.
        """
        compiled = env["compiled"]
        compiled.cedar_texts["role-visitor"] = (
            'permit(principal in Role::"visitor", '
            'action == Action::"release-production-order", resource);'
        )
        pol = PolicyEngine(compiled)
        # the action still names its own policy set, and that set still applies
        assert pol.decide(PLANNER, "release-production-order",
                          {"status": "PLANNED"}).allow
        # ...but a permit from an unrelated set is now consulted too
        assert pol.decide(OUTSIDER, "release-production-order", None).allow
        # and the action's own set is still reported first when it permits
        assert "production" in pol.decide(
            PLANNER, "release-production-order", {"status": "PLANNED"}).reason
        # a principal the extra permit does not name is still denied
        assert not pol.decide({"id": "nobody", "Role": ["other"]},
                              "release-production-order", None).allow

    def test_masking_honors_claims(self, env):
        pol = env["policy"]
        props = {"name": "Steel Plate S45C", "unit_cost": 210.0}
        assert pol.mask("material", props, OUTSIDER)["unit_cost"] == "__masked__"
        assert pol.mask("material", props, {"id": "x", "markings": ["internal"]})["unit_cost"] == 210.0
        assert pol.mask("material", props, OUTSIDER)["name"] == "Steel Plate S45C"


class TestExecute:
    async def test_release_production_order_happy_path(self, env):
        rt, repo = env["runtime"], env["repo"]
        async with env["maker"]() as s:
            rev = await rt.execute(s, "release-production-order", PLANNER, {}, "PO-1002")
            await s.commit()
        assert rev.outcome == "executed"
        assert rev.policy_decision["allow"] is True
        async with env["maker"]() as s:
            order = await repo.get(s, "production-order", "PO-1002")
            assert order["status"] == "RELEASED"
            assert isinstance(order["released_at"], dt.datetime)
            # derived property is computed, not stored
            assert "_derived" not in order

    async def test_rule_rejection_records_revision(self, env):
        rt = env["runtime"]
        async with env["maker"]() as s:
            await rt.execute(s, "release-production-order", PLANNER, {}, "PO-1002")
            await s.commit()
        async with env["maker"]() as s:
            with pytest.raises(RuleRejectedError) as ei:
                await rt.execute(s, "release-production-order", PLANNER, {}, "PO-1002")
            await s.commit()  # rejection revision persists
        assert ei.value.details["revision_id"]

    async def test_policy_denial(self, env):
        rt = env["runtime"]
        async with env["maker"]() as s:
            with pytest.raises(PolicyDeniedError):
                await rt.execute(s, "release-production-order", OUTSIDER, {}, "PO-1002")
            await s.commit()

    async def test_double_release_blocked_by_rule_on_latest_state(self, env):
        rt = env["runtime"]
        async with env["maker"]() as s:
            await rt.execute(s, "release-production-order", PLANNER, {}, "PO-1002")
            with pytest.raises(RuleRejectedError):
                await rt.execute(s, "release-production-order", PLANNER, {}, "PO-1002")
            await s.commit()

    async def test_idempotency_replay(self, env):
        rt = env["runtime"]
        async with env["maker"]() as s:
            rev1 = await rt.execute(s, "release-production-order", PLANNER, {}, "PO-1002",
                                    idempotency_key="op-123")
            await s.commit()
        async with env["maker"]() as s:
            rev2 = await rt.execute(s, "release-production-order", PLANNER, {}, "PO-1002",
                                    idempotency_key="op-123")
        assert rev2.id == rev1.id

    async def test_optimistic_locking(self, env):
        rt = env["runtime"]
        async with env["maker"]() as s:
            with pytest.raises(ConflictError):
                await rt.execute(s, "release-production-order", PLANNER, {}, "PO-1002",
                                 expected_revision=42)
            await s.commit()

    async def test_parameter_validation(self, env):
        rt = env["runtime"]
        async with env["maker"]() as s:
            with pytest.raises(TypeMismatchError):
                await rt.execute(s, "receive-material", PLANNER, {}, "M-101")
            with pytest.raises(TypeMismatchError):
                await rt.execute(s, "receive-material", PLANNER,
                                 {"counted_qty": 5, "bogus": 1}, "M-101")

    async def test_create_production_order_generates_id(self, env):
        rt, repo = env["runtime"], env["repo"]
        async with env["maker"]() as s:
            rev = await rt.execute(s, "create-production-order", PLANNER, {
                "product_id": "P-100", "qty": 5, "priority": "HIGH",
            })
            await s.commit()
        assert rev.outcome == "executed"
        assert rev.object_id.startswith("PO-")
        async with env["maker"]() as s:
            order = await repo.get(s, "production-order", rev.object_id)
            assert order["status"] == "PLANNED" and order["priority"] == "HIGH"

    async def test_set_link_action(self, link_env):
        rt, repo = link_env["runtime"], link_env["repo"]
        async with link_env["maker"]() as s:
            await rt.execute(s, "attach-item", {"id": "u"}, {"item_id": "I-2"}, "C-1")
            await s.commit()
            members = await repo.link_members(s, "container-items", src_id="C-1")
        assert members == [("C-1", "I-2")]

    async def test_validate_dry_run(self, env):
        rt = env["runtime"]
        async with env["maker"]() as s:
            out = await rt.validate(s, "release-production-order", PLANNER, {}, "PO-1002")
        assert out["policy"]["allow"] is True
        assert all(r["ok"] for r in out["rules"])


class TestOutbox:
    async def test_webhook_delivered_via_allowlist(self, env):
        from ontogeny.action.models import OutboxRow
        from sqlalchemy import select

        await _release_high_priority_order(env)

        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(202)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with env["maker"]() as s:
            events = (await s.execute(select(OutboxRow))).scalars().all()
        high_priority_hook = [e for e in events if e.payload.get("kind") == "webhook"]
        assert high_priority_hook, "a HIGH priority release -> webhook enqueued"

        dispatcher = OutboxDispatcher(env["maker"], env["settings"], http_client=http)
        stats = await dispatcher.dispatch_pending()
        assert stats["webhook"] >= 1
        assert any(r.url.host == "wms.example.test" for r in requests)

    async def test_webhook_blocked_without_allowlist(self, env):
        """An empty allowlist means DENY ALL, and "blocked" must mean the request
        was never sent — not merely that it failed. The event is consumed (so a
        bad deployment cannot wedge the pipeline) and logged for replay."""
        from ontogeny.config import Settings as S

        await _release_high_priority_order(env)

        sent: list[httpx.Request] = []
        http = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: sent.append(r) or httpx.Response(200)))
        settings = S(env=env["settings"].env, webhook_allowlist=())
        dispatcher = OutboxDispatcher(env["maker"], settings, http_client=http)
        await dispatcher.dispatch_pending()
        assert sent == [], "nothing may leave the platform without an allowlist entry"

    async def test_webhook_blocked_for_an_unlisted_host(self, env):
        """Being on the allowlist is per host: a second host is still denied."""
        from ontogeny.config import Settings as S

        await _release_high_priority_order(env)

        sent: list[httpx.Request] = []
        http = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: sent.append(r) or httpx.Response(200)))
        settings = S(env=env["settings"].env, webhook_allowlist=("allowed.test",))
        dispatcher = OutboxDispatcher(env["maker"], settings, http_client=http)
        await dispatcher.dispatch_pending()
        assert not [r for r in sent if r.url.host == "wms.example.test"]

    async def test_sse_broadcast(self, env):
        broker = SseBroker()
        q = broker.subscribe()
        dispatcher = OutboxDispatcher(env["maker"], env["settings"], sse=broker)
        async with env["maker"]() as s:
            await env["runtime"].execute(s, "release-production-order", PLANNER, {}, "PO-1002")
            await s.commit()
        await dispatcher.dispatch_pending()
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        assert any(e["object_id"] == "PO-1002" and e["op"] in ("upsert", "event") for e in events)


class TestWebhookEffectValidation:
    """A webhook URL typo must fail at publish, not silently never deliver.

    Delivery resolves ``${VAR}`` late and treats a failure as
    "consumed with prejudice" (logged, not retried), so a malformed URL used to
    keep the action succeeding while the outside world heard nothing.
    """

    def _pkg_with_effect(self, golden_pkg_path, root, url):
        import shutil
        from pathlib import Path

        shutil.rmtree(root, ignore_errors=True)
        shutil.copytree(golden_pkg_path, root)
        (Path(root) / "actions" / "hooky.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Action\nmetadata: {name: hooky}\n"
            "spec:\n  target: production-order\n  effects:\n"
            f"  - {{kind: webhook, url: '{url}'}}\n",
            encoding="utf-8",
        )
        return Path(root)

    def test_a_non_http_url_is_refused(self, golden_pkg_path, tmp_path):
        from ontogeny.core import load_package, validate

        root = self._pkg_with_effect(golden_pkg_path, tmp_path / "p", "hooks.example.com/x")
        codes = [i.code for i in validate(load_package(str(root))).issues if i.severity == "error"]
        assert "ACTION-WEBHOOK-URL" in codes

    def test_an_env_reference_is_accepted(self, golden_pkg_path, tmp_path):
        from ontogeny.core import load_package, validate

        root = self._pkg_with_effect(golden_pkg_path, tmp_path / "p2", "${HOOK_URL}")
        codes = [i.code for i in validate(load_package(str(root))).issues if i.severity == "error"]
        assert "ACTION-WEBHOOK-URL" not in codes

    def test_an_empty_url_is_refused(self, golden_pkg_path, tmp_path):
        from ontogeny.core import load_package, validate

        root = self._pkg_with_effect(golden_pkg_path, tmp_path / "p3", "")
        codes = [i.code for i in validate(load_package(str(root))).issues if i.severity == "error"]
        assert "ACTION-WEBHOOK-URL" in codes


class TestDeliveryRetry:
    """A failed delivery is retried, not dropped.

    Regression: the dispatcher moved its cursor to each row BEFORE attempting
    delivery, so any consumer returning False (the projection worker's contract
    for "retry me") was skipped permanently. One transient HTTP error lost the
    notification, while the worker's own docstring promised at-least-once.
    """

    async def _enqueue_webhook(self, env, url="${WMS_WEBHOOK}") -> int:
        """Release a HIGH priority order (the webhook effect fires); return that
        outbox row's id.

        The id is what the assertions turn on: the cursor may advance past the
        rows BEFORE it (they were consumed), but never past it.
        """
        from sqlalchemy import select

        from ontogeny.action.models import OutboxRow

        await _release_high_priority_order(env)
        async with env["maker"]() as s:
            hook = None
            for r in (await s.execute(select(OutboxRow))).scalars().all():
                if r.payload.get("kind") == "webhook":
                    r.payload = {**r.payload, "url_template": url}
                    hook = r
            await s.commit()
        assert hook is not None, "the action should have queued a webhook"
        return hook.id

    async def _cursor(self, env, consumer="webhook") -> int:
        from sqlalchemy import select

        from ontogeny.action.models import OutboxConsumerRow

        async with env["maker"]() as s:
            c = (await s.execute(
                select(OutboxConsumerRow).where(OutboxConsumerRow.consumer == consumer)
            )).scalar_one_or_none()
        return c.last_id if c else 0

    async def test_a_connection_error_does_not_advance_the_cursor(self, env):
        hook_id = await self._enqueue_webhook(env)

        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("endpoint down")

        http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
        dispatcher = OutboxDispatcher(env["maker"], env["settings"], http_client=http)
        await dispatcher.dispatch_pending()
        assert await self._cursor(env) < hook_id, "the failed row must stay pending"

    async def test_a_5xx_is_retried_and_a_recovered_endpoint_delivers(self, env):
        hook_id = await self._enqueue_webhook(env)

        down = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
        d1 = OutboxDispatcher(env["maker"], env["settings"], http_client=down)
        await d1.dispatch_pending()
        assert await self._cursor(env) < hook_id, "a 5xx is transient: keep it pending"

        sent: list[httpx.Request] = []
        up = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: sent.append(r) or httpx.Response(200)))
        d2 = OutboxDispatcher(env["maker"], env["settings"], http_client=up)
        await d2.dispatch_pending()
        assert any(r.url.host == "wms.example.test" for r in sent), "the retry delivers"
        assert await self._cursor(env) >= hook_id, "delivered rows advance the cursor"

    async def test_a_4xx_is_consumed_rather_than_blocking_forever(self, env):
        hook_id = await self._enqueue_webhook(env)
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
        dispatcher = OutboxDispatcher(env["maker"], env["settings"], http_client=http)
        await dispatcher.dispatch_pending()
        # a wrong request cannot be fixed by retrying: consume it and log
        assert await self._cursor(env) >= hook_id

    async def test_a_failed_projection_row_stays_pending(self, env):
        """The same contract for the projection consumer: its worker returns
        False to be retried, so the cursor must not walk past it."""

        from ontogeny.action.models import OutboxRow

        async with env["maker"]() as s:
            await env["runtime"].execute(s, "release-production-order", PLANNER, {}, "PO-1002")
            await s.commit()
        before = await self._cursor(env, "projection")

        async def failing_hook(event: OutboxRow) -> bool:
            return False

        dispatcher = OutboxDispatcher(env["maker"], env["settings"],
                                      projection_hook=failing_hook)
        assert (await dispatcher.dispatch_pending())["projection"] == 0
        assert await self._cursor(env, "projection") == before
