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
"""Accounts, sessions, and role/permission administration.

The load-bearing test is `test_granted_permission_is_enforced_by_the_engine`:
the whole design claim is that the role matrix writes *Cedar*, so a permission an
administrator toggles on is enforced by the same policy plane that decides every
other request — not by a second table the engine never reads.
"""
from __future__ import annotations

import json
import shutil

import httpx
import pytest_asyncio

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.service import ServiceContext

ADMIN = {"id": "admin", "Role": ["admin"], "is_admin": True}


@pytest_asyncio.fixture()
async def client(golden_pkg_path, tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOGENY_ADMIN_USER", "root")
    monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", "root-password")
    pkg_root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, pkg_root)
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL (same path the
    # demo bootstrap uses), so tests always agree with the shipped example
    from ontogeny.demo.bootstrap import seed_from_package

    seed_from_package(golden_pkg_path, src, force=True)

    settings = Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
                        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"})
    sc = ServiceContext(settings, str(pkg_root))
    await sc.initialize()
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, sc, pkg_root


def _admin(c, **kw):
    return c.get("/api/v1/admin/users", headers={"X-Ontogeny-Principal": json.dumps(ADMIN)}, **kw)


class TestLogin:
    async def test_bootstrap_administrator_can_sign_in_and_is_remembered(self, client):
        c, sc, _ = client
        # bootstrap runs during initialize(): a deployment with no administrator
        # is unreachable, so the first start creates one from ONTOGENY_ADMIN_*
        admins = [u for u in await sc.auth.list_users() if u["is_admin"]]
        assert [u["username"] for u in admins] == ["root"]
        # ...and it is idempotent
        assert await sc.auth.ensure_admin() is None

        r = await c.post("/api/v1/auth/login",
                         json={"username": "root", "password": "root-password"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["principal"]["id"] == "root"
        assert body["principal"]["is_admin"] is True
        assert body["principal"]["authenticated"] is True
        # the token is set as an HttpOnly cookie, not left to script
        assert "ontogeny_session" in r.cookies

        me = await c.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["principal"]["id"] == "root"

        await c.post("/api/v1/auth/logout")
        assert (await c.get("/api/v1/auth/me")).status_code == 401

    async def test_wrong_password_and_unknown_user_are_indistinguishable(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        a = await c.post("/api/v1/auth/login", json={"username": "root", "password": "nope"})
        b = await c.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})
        assert a.status_code == b.status_code == 401
        assert a.json()["message"] == b.json()["message"]

    async def test_disabled_account_cannot_sign_in(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        await sc.auth.create_user(username="temp", password="temp-password", roles=["operator"])
        await sc.auth.update_user("temp", {"status": "disabled"})
        r = await c.post("/api/v1/auth/login", json={"username": "temp", "password": "temp-password"})
        assert r.status_code == 401

    async def test_changing_a_password_kills_existing_sessions(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        await sc.auth.create_user(username="ana", password="ana-password", roles=["operator"])
        r = await c.post("/api/v1/auth/login", json={"username": "ana", "password": "ana-password"})
        assert r.status_code == 200
        assert (await c.get("/api/v1/auth/me")).status_code == 200

        await sc.auth.update_user("ana", {"password": "ana-password-2"})
        assert (await c.get("/api/v1/auth/me")).status_code == 401


class TestAccountAdministration:
    async def test_only_an_administrator_may_manage_accounts(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        # anonymous
        assert (await c.get("/api/v1/admin/users")).status_code == 403
        # a signed-in non-admin
        await sc.auth.create_user(username="op", password="op-password", roles=["operator"])
        await c.post("/api/v1/auth/login", json={"username": "op", "password": "op-password"})
        assert (await c.get("/api/v1/admin/users")).status_code == 403

    async def test_create_update_and_delete_an_account(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        h = {"X-Ontogeny-Principal": json.dumps(ADMIN)}

        created = await c.post("/api/v1/admin/users", headers=h, json={
            "username": "li", "password": "li-password", "display": "李工",
            "roles": ["operator", "quality"], "site": "plant-north",
        })
        assert created.status_code == 200, created.text
        assert created.json()["roles"] == ["operator", "quality"]

        patched = await c.patch("/api/v1/admin/users/li", headers=h,
                                json={"roles": ["operator"], "site": "south"})
        assert patched.status_code == 200
        assert patched.json()["roles"] == ["operator"]
        assert patched.json()["site"] == "south"

        removed = await c.delete("/api/v1/admin/users/li", headers=h)
        assert removed.status_code == 200
        assert [u["username"] for u in (await c.get("/api/v1/admin/users", headers=h)).json()["users"]] == ["root"]

    async def test_the_last_administrator_cannot_be_deleted(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        h = {"X-Ontogeny-Principal": json.dumps(ADMIN)}
        r = await c.delete("/api/v1/admin/users/root", headers=h)
        assert r.status_code == 400
        assert "last administrator" in r.text

    async def test_short_passwords_are_refused(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        h = {"X-Ontogeny-Principal": json.dumps(ADMIN)}
        r = await c.post("/api/v1/admin/users", headers=h,
                         json={"username": "weak", "password": "123"})
        assert r.status_code == 400


class TestRolesAndPermissions:
    async def test_matrix_reports_what_the_policies_grant(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        h = {"X-Ontogeny-Principal": json.dumps(ADMIN)}

        r = await c.get("/api/v1/admin/roles", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        # roles come from the vocabulary, the policies AND the accounts
        names = {x["name"] for x in body["roles"]}
        assert "planner" in names
        assert "admin" in names
        # the golden package's release-production-order policy is conditional
        # (only PLANNED orders) and hand-written, so the matrix shows it but
        # marks it as not managed
        cell = body["matrix"]["planner"]["release-production-order"]
        assert cell["granted"] is True
        assert cell["managed"] is False
        assert cell["conditional"] is True
        assert "production" in cell["source"]

    async def test_granted_permission_is_enforced_by_the_engine(self, client):
        """The point of the whole design: the matrix writes Cedar, and Cedar is
        what the engine consults. A role granted an action here can really do it;
        revoking it really stops it."""
        c, sc, pkg = client
        await sc.auth.ensure_admin()
        h = {"X-Ontogeny-Principal": json.dumps(ADMIN)}

        # a role with no grants at all
        await sc.auth.create_user(username="op", password="op-password", roles=["line_lead"])
        operator = {"id": "op", "Role": ["line_lead"], "site": "plant-north"}

        async def may_release() -> bool:
            """The dry-run endpoint: rules + policy, no writes and no data
            dependency, so this isolates the authorization question."""
            r = await c.post("/api/v1/actions/release-production-order/validate",
                             headers={"X-Ontogeny-Principal": json.dumps(operator)},
                             json={"parameters": {}, "target_id": "PO-1002"})
            assert r.status_code == 200, r.text
            return bool(r.json()["policy"]["allow"])

        assert await may_release() is False, "no permit yet -> Cedar denies"

        # grant the role the action through the role matrix
        saved = await c.put("/api/v1/admin/roles/line_lead", headers=h,
                            json={"name": "line_lead", "actions": ["release-production-order"]})
        assert saved.status_code == 200, saved.text
        assert (pkg / "policies" / "role-line-lead.cedar").is_file()

        assert await may_release() is True, "the grant is enforced by the engine"

        # and revoking it is just as real
        await c.put("/api/v1/admin/roles/line_lead", headers=h,
                    json={"name": "line_lead", "actions": []})
        assert await may_release() is False

    async def test_deleting_a_role_reassigns_its_holders(self, client):
        c, sc, _ = client
        await sc.auth.ensure_admin()
        h = {"X-Ontogeny-Principal": json.dumps(ADMIN)}
        await sc.auth.create_user(username="m1", password="m1-password", roles=["temp_role"])

        await c.put("/api/v1/admin/roles/temp_role", headers=h,
                    json={"name": "temp_role", "actions": ["release-production-order"]})
        r = await c.request("DELETE", "/api/v1/admin/roles/temp_role", headers=h,
                            json={"name": "temp_role", "reassign_to": "operator"})
        assert r.status_code == 200, r.text
        assert r.json()["reassigned"] == ["m1"]
        users = (await c.get("/api/v1/admin/users", headers=h)).json()["users"]
        assert next(u for u in users if u["username"] == "m1")["roles"] == ["operator"]

    async def test_role_policy_is_deterministic(self, client):
        """Re-saving an unchanged matrix must not churn the content hash."""
        c, sc, pkg = client
        await sc.auth.ensure_admin()
        h = {"X-Ontogeny-Principal": json.dumps(ADMIN)}
        body = {"name": "qa", "actions": ["record-inspection", "release-production-order"]}
        await c.put("/api/v1/admin/roles/qa", headers=h, json=body)
        first = (pkg / "policies" / "role-qa.cedar").read_text(encoding="utf-8")
        await c.put("/api/v1/admin/roles/qa", headers=h,
                    json={"name": "qa", "actions": ["release-production-order", "record-inspection"]})
        assert (pkg / "policies" / "role-qa.cedar").read_text(encoding="utf-8") == first

    async def test_site_scoped_grant_compiles_to_a_condition(self, client):
        c, sc, pkg = client
        await sc.auth.ensure_admin()
        h = {"X-Ontogeny-Principal": json.dumps(ADMIN)}
        await c.put("/api/v1/admin/roles/site_lead", headers=h,
                    json={"name": "site_lead", "actions": ["release-production-order"], "site": "plant-north"})
        text = (pkg / "policies" / "role-site-lead.cedar").read_text(encoding="utf-8")
        assert 'principal.site == "plant-north"' in text
