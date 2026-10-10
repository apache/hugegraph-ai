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
"""Regression tests for the governance/data-integrity hardening pass.

Each test here pins ONE fixed defect to a behaviour, so the fix cannot be
quietly reverted: the admin/evolve router gates, the history/aggregate masking
bypasses, the T0 promote fail-closed gate, newId() uniqueness, the validator's
own crash bugs, the linter's dead chain-depth rule, and watermark pagination.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import sys

import httpx
import pytest

from ontogeny.core import expr as _expr
from ontogeny.core import validate
from ontogeny.core.linter import lint
from ontogeny.core.models import JoinTableJoin, SourceRef

# ---------------------------------------------------------------------------
# 1. the admin / evolve / audit / SSE planes are gated
# ---------------------------------------------------------------------------

def _anon(client):
    """A client with NO default identity: the shared fixture carries an admin
    dev-header by default (the gated planes need it); these tests must see
    what a truly anonymous visitor sees."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=client[0]._transport.app),
                             base_url="http://anon")


class TestRouterGates:
    async def test_anonymous_cannot_reach_admin_plane(self, client):
        async with _anon(client) as c:
            r = await c.post("/api/v1/admin/builder/save", json={"resources": []})
            assert r.status_code == 403, "builder/save writes policy text: it must be admin-gated"
            for method, path, body in (
                ("post", "/api/v1/admin/publish", {}),
                ("post", "/api/v1/admin/domains", {"name": "nope"}),
                ("get", "/api/v1/admin/metrics", None),
                ("get", "/api/v1/admin/builder/resources", None),
            ):
                r = await c.request(method, path, json=body)
                assert r.status_code == 403, path

    async def test_anonymous_cannot_reach_evolve_plane(self, client):
        async with _anon(client) as c:
            for method, path, body in (
                ("post", "/api/v1/evolve/diagnose", None),
                ("post", "/api/v1/evolve/aggregate", None),
                ("post", "/api/v1/evolve/proposals/1/promote", None),
                ("get", "/api/v1/evolve/signals", None),
            ):
                r = await c.request(method, path, json=body)
                assert r.status_code == 403, path

    async def test_non_admin_principal_is_refused_on_admin(self, client):
        c, _ = client
        h = {"X-Ontogeny-Principal": json.dumps({"id": "planner", "Role": ["planner"]})}
        r = await c.get("/api/v1/admin/builder/resources", headers=h)
        assert r.status_code == 403

    async def test_audit_and_sse_require_authentication(self, client):
        async with _anon(client) as c:
            r = await c.get("/api/v1/audit/revisions")
            assert r.status_code == 401
            r = await c.get("/api/v1/subscriptions/objects/material")
            assert r.status_code == 401

    async def test_approval_deletion_is_admin_only(self, client):
        async with _anon(client) as c:
            r = await c.delete("/api/v1/agent/approvals/999")
            assert r.status_code == 403, "deleting an approval erases audit: admin only"


# ---------------------------------------------------------------------------
# 2. masking has no read-side bypasses
# ---------------------------------------------------------------------------


class TestMaskingBypasses:
    async def test_history_versions_are_masked(self, client):
        c, _ = client
        await c.post("/api/v1/admin/sync/material")
        h = {"X-Ontogeny-Principal": json.dumps({"id": "visitor"})}  # no markings claim
        r = await c.get("/api/v1/objects/material/M-104/history", headers=h)
        assert r.status_code == 200
        versions = r.json()["versions"]
        assert versions, "seeded material must have at least the initial version"
        for v in versions:
            assert v.get("unit_cost") == "__masked__", "history leaked a marked value"

    async def test_history_unmasks_for_claiming_principal(self, client):
        c, _ = client
        await c.post("/api/v1/admin/sync/material")
        h = {"X-Ontogeny-Principal": json.dumps({"id": "buyer", "markings": ["internal"]})}
        r = await c.get("/api/v1/objects/material/M-104/history", headers=h)
        assert all(v["unit_cost"] != "__masked__" for v in r.json()["versions"])

    async def test_aggregate_on_marked_field_is_denied(self, client):
        c, _ = client
        await c.post("/api/v1/admin/sync/material")
        h = {"X-Ontogeny-Principal": json.dumps({"id": "visitor"})}
        r = await c.post("/api/v1/objects/material/aggregate",
                         json={"fn": "avg", "field": "unit_cost"}, headers=h)
        assert r.status_code == 403
        assert r.json()["code"] == "POLICY_DENIED"

    async def test_aggregate_on_marked_field_allows_claiming_principal(self, client):
        c, _ = client
        await c.post("/api/v1/admin/sync/material")
        h = {"X-Ontogeny-Principal": json.dumps({"id": "buyer", "markings": ["internal"]})}
        r = await c.post("/api/v1/objects/material/aggregate",
                         json={"fn": "avg", "field": "unit_cost"}, headers=h)
        assert r.status_code == 200 and r.json()["value"] > 0


# ---------------------------------------------------------------------------
# 3. T0 auto-merge is fail-closed without a green eval report
# ---------------------------------------------------------------------------


class TestT0FailClosed:
    async def test_promote_without_eval_report_is_refused(self, client):
        c, sc = client
        for t in sc.compiled.objects:  # eval suite queries need materialized tables
            await c.post(f"/api/v1/admin/sync/{t}")
        for _ in range(6):  # the unmapped-filter signal the proposer acts on
            await c.post("/api/v1/objects/production-order/query",
                         json={"filter": {"field": "shift", "op": "eq", "value": "DAY"}})
        await c.post("/api/v1/evolve/aggregate")
        pid = (await c.post("/api/v1/evolve/diagnose")).json()["proposals"][0]["id"]
        # promote WITHOUT running /eval first: the gate must refuse, not merge
        r = await c.post(f"/api/v1/evolve/proposals/{pid}/promote")
        assert r.status_code == 200
        assert r.json()["status"] == "needs_eval"
        detail = (await c.get(f"/api/v1/evolve/proposals/{pid}")).json()
        assert detail["status"] != "promoted"


# ---------------------------------------------------------------------------
# 4. newId() cannot mint a duplicate alive row
# ---------------------------------------------------------------------------


class TestNewId:
    async def test_consecutive_creates_get_distinct_ids(self, client):
        c, _ = client
        ids = []
        for _ in range(2):
            r = await c.post("/api/v1/actions/create-production-order/execute", json={
                "parameters": {"product_id": "P-101", "qty": 5, "priority": "NORMAL",
                               "due_date": "2026-12-01"},
            }, headers={"X-Ontogeny-Principal": json.dumps(
                {"id": "planner", "Role": ["planner"], "site": "plant-north"})})
            assert r.status_code == 200, r.text
            ids.append(r.json()["object_id"])
        assert ids[0] != ids[1], "second create minted the same newId() value"

    async def test_create_with_existing_pk_is_a_conflict(self, client):
        from ontogeny.errors import ConflictError

        c, sc = client
        r = await c.post("/api/v1/actions/create-production-order/execute", json={
            "parameters": {"product_id": "P-101", "qty": 5, "priority": "NORMAL",
                           "due_date": "2026-12-01"},
        }, headers={"X-Ontogeny-Principal": json.dumps(
            {"id": "planner", "Role": ["planner"], "site": "plant-north"})})
        assert r.status_code == 200
        pk = r.json()["object_id"]
        async with sc.sessionmaker() as s:
            from ontogeny.stores.repo import ObjectRepository

            repo = ObjectRepository(sc.compiled)
            import datetime as dt

            with pytest.raises(ConflictError):
                # same business key, new version key: must NOT become a second
                # alive row (the old schema happily accepted it)
                await repo.action_insert(s, "production-order", {
                    "order_id": pk, "product_id": "P-101", "qty": 1, "status": "PLANNED",
                }, dt.datetime.now(dt.timezone.utc))


# ---------------------------------------------------------------------------
# 5. the validator itself must not crash on bad input
# ---------------------------------------------------------------------------


class TestValidatorHardening:
    def test_join_keys_unknown_side_is_a_report_not_a_crash(self, golden_pkg):
        pkg = copy.deepcopy(golden_pkg)
        lnk = pkg.find("LinkType", "production-order-inspections")
        lnk.spec.join = JoinTableJoin(kind="join-table", store="erp",
                                     relation=SourceRef(table="production_orders"), keys={
            "sorce": {"order_id": "order_id"},  # typo: used to AttributeError
            "target": {"order_id": "order_id"},
        })
        rep = validate(pkg)
        assert any(i.code == "LINK-KEY" and "sorce" in i.message for i in rep.issues)

    def test_deeply_nested_expression_is_an_expression_error(self):
        # pin a low stack budget so the guard provably bites regardless of the
        # runner's recursion limit (pytest's is higher than python's default)
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(min(limit, 1500))
        try:
            src = "(" * 4000 + "1" + ")" * 4000
            with pytest.raises(_expr.ExpressionError):
                _expr.analyze(src)
            # by design: a non-parseable src is simply not a bare identifier
            assert _expr.is_bare_identifier(src) is None
        finally:
            sys.setrecursionlimit(limit)

    def test_oversized_expression_is_rejected(self):
        with pytest.raises(_expr.ExpressionError):
            _expr.parse("1 + " * 5000 + "1")

    def test_has_right_hand_side_is_not_a_target_reference(self, golden_pkg):
        # `principal has site` used to be mis-analyzed as (target, site) and
        # rejected with EXPR-PATH
        assert _expr.analyze("principal has site") == set()
        pkg = copy.deepcopy(golden_pkg)
        from ontogeny.core.models import Rule

        act = pkg.find("Action", "release-production-order")
        act.spec.rules = [*act.spec.rules, Rule(expr="principal has site")]
        rep = validate(pkg)
        assert not any("principal has site" in i.message and i.code == "EXPR-PATH"
                       for i in rep.issues)

    def test_effect_when_is_statically_validated(self, golden_pkg):
        pkg = copy.deepcopy(golden_pkg)
        eff = pkg.find("Action", "release-production-order").spec.effects[0]
        eff.when = "target.prioraty == 'HIGH'"  # typo: used to pass publish
        rep = validate(pkg)
        assert any(i.code == "EXPR-PATH" for i in rep.issues)

    def test_create_object_cannot_set_derived_property(self, golden_pkg):
        pkg = copy.deepcopy(golden_pkg)
        eff = pkg.find("Action", "create-production-order").spec.effects[0]
        eff.properties["release_lag_h"] = "1"  # release_lag_h is expression-derived
        rep = validate(pkg)
        assert any(i.code == "ACTION-DERIVED" for i in rep.issues)

    def test_linter_flags_deep_derived_chains(self, golden_pkg):
        pkg = copy.deepcopy(golden_pkg)
        obj = pkg.find("ObjectType", "production-order")
        props = obj.spec.properties
        base = {"type": "integer"}
        # qty -> d1 -> d2 -> d3: a 3-deep chain the old object-keyed memo
        # measured as depth 1, so OO-004 never fired
        from ontogeny.core.models import PropertyDef

        props["d1"] = PropertyDef(**base, display="d1", derived="target.qty + 1")
        props["d2"] = PropertyDef(**base, display="d2", derived="target.d1 + 1")
        props["d3"] = PropertyDef(**base, display="d3", derived="target.d2 + 1")
        rep = lint(pkg)
        assert any(i.code == "OO-004" for i in rep.issues), \
            "a 3-deep derived chain must trip OO-004"

    def test_linter_clean_on_golden(self, golden_pkg):
        rep = lint(golden_pkg)
        assert not any(i.code == "OO-004" for i in rep.issues), \
            "the golden package must not false-positive on chain depth"


# ---------------------------------------------------------------------------
# 6. watermark pagination drains past the first batch
# ---------------------------------------------------------------------------


class TestWatermarkPagination:
    def _source_db(self, path, n=7):
        con = sqlite3.connect(str(path))
        con.execute("CREATE TABLE t (id TEXT PRIMARY KEY, updated_at TEXT)")
        for i in range(n):
            con.execute("INSERT INTO t VALUES (?, ?)",
                        (f"R-{i}", f"2026-01-01T00:00:{i:02d}Z"))
        con.commit()
        con.close()

    async def test_fetch_yields_every_row_past_batch_boundaries(self, tmp_path):
        from ontogeny.core.models import SourceRef, StoreResource
        from ontogeny.stores.sources import SqlSource

        db = tmp_path / "wm.db"
        self._source_db(db)
        store = StoreResource.model_validate({
            "apiVersion": "ontogeny/v1", "kind": "Store",
            "metadata": {"name": "wm"},
            "spec": {"type": "sqlite", "connection": f"sqlite+aiosqlite:///{db}", "access": "read-only"},
        })
        src = SqlSource(store, f"sqlite+aiosqlite:///{db}")
        ref = SourceRef(table="t")
        seen = []
        async for row in src.fetch(ref, watermark_col="updated_at", batch=2):
            seen.append(row["id"])
        assert len(seen) == 7, "rows past the first batch were lost behind the cursor"
        # second pass: everything is behind the watermark now
        again = [r async for r in src.fetch(ref, watermark_col="updated_at",
                                            after="2026-01-01T00:00:06Z", batch=2)]
        assert again == []

    async def test_snapshot_fetch_pages_deterministically(self, tmp_path):
        from ontogeny.core.models import SourceRef, StoreResource
        from ontogeny.stores.sources import SqlSource

        db = tmp_path / "snap.db"
        self._source_db(db, n=5)
        store = StoreResource.model_validate({
            "apiVersion": "ontogeny/v1", "kind": "Store",
            "metadata": {"name": "snap"},
            "spec": {"type": "sqlite", "connection": f"sqlite+aiosqlite:///{db}", "access": "read-only"},
        })
        src = SqlSource(store, f"sqlite+aiosqlite:///{db}")
        ref = SourceRef(table="t")
        seen = [r["id"] async for r in src.fetch(ref, batch=2)]
        assert len(seen) == 5


# ---------------------------------------------------------------------------
# 7. a failed sync leaves its run row behind
# ---------------------------------------------------------------------------


class TestSyncFailureAudit:
    async def test_failed_sync_records_an_error_run(self, client):
        import pathlib

        c, sc = client
        # break the source: the production-order source table disappears
        dsn = sc.settings.env["ERP_DSN"]
        db_path = pathlib.Path(dsn.removeprefix("sqlite+aiosqlite:///"))
        con = sqlite3.connect(str(db_path))
        con.execute("DROP TABLE IF EXISTS production_orders")
        con.commit()
        con.close()
        with pytest.raises(Exception):
            await sc.sync("production-order")
        from sqlalchemy import select

        from ontogeny.stores.sync import SyncRunRow

        async with sc.sessionmaker() as s:
            rows = (await s.execute(
                select(SyncRunRow).where(SyncRunRow.object_type == "production-order")
            )).scalars().all()
        assert any(r.status == "error" and r.error for r in rows), \
            "the failed run's audit must survive the rollback"
