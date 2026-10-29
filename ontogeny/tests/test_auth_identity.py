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
# specific language governing permissions and
# limitations under the License.

"""Who is the caller? The four-way resolution and its visible precedence.

`get_principal` is the single door every request passes, so this module pins
the contract the Access page's identity tab renders:

- ``via`` names the winner (session / bearer / dev-header / anonymous) — the UI
  turns an otherwise invisible precedence into a fact;
- a dev-header principal may open the console while dev_auth is on (otherwise
  an acting-as picker could only decorate requests the browser never makes);
- ``Authorization: Bearer`` works for programmatic clients, and the order is
  cookie > bearer > dev header > anonymous;
- a simulated identity is decided by the SAME Cedar engine — simulation changes
  who asks, never whether the policy plane answers.
"""

from __future__ import annotations

import json
import shutil

import httpx
import pytest
import pytest_asyncio

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.service import ServiceContext

ADMIN = {"id": "admin", "Role": ["admin"], "is_admin": True}


def _header(p: dict) -> dict[str, str]:
    return {"X-Ontogeny-Principal": json.dumps(p)}


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

    settings = Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"},
    )
    sc = ServiceContext(settings, str(pkg_root))
    await sc.initialize()
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, sc


async def _login(c: httpx.AsyncClient, username: str, password: str) -> str:
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


class TestViaTag:
    async def test_dev_header_identity_opens_the_console(self, client):
        """The acting-as path must reach /auth/me, or the picker in the UI could
        never get past the login gate it sits behind."""
        c, _ = client
        r = await c.get("/api/v1/auth/me", headers=_header({"id": "u-planner", "Role": ["planner"]}))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["principal"]["via"] == "dev-header"
        assert body["principal"]["authenticated"] is False
        assert body["principal"]["Role"] == ["planner"]
        assert body["dev_auth"] is True

    async def test_session_wins_and_is_tagged(self, client):
        c, _ = client
        await _login(c, "root", "root-password")  # cookie jar now holds the session
        r = await c.get("/api/v1/auth/me", headers=_header({"id": "u-planner", "Role": ["visitor"]}))
        assert r.status_code == 200
        body = r.json()
        # the session decides, NOT the header: this is the precedence the UI
        # must be able to explain
        assert body["principal"]["via"] == "session"
        assert body["principal"]["id"] == "root"
        assert body["principal"]["authenticated"] is True

    async def test_anonymous_is_still_a_401_on_auth_me(self, client):
        c, _ = client
        r = await c.get("/api/v1/auth/me")
        assert r.status_code == 401


class TestBearer:
    async def test_bearer_token_authenticates_without_a_cookie_jar(self, client):
        c, _ = client
        token = await _login(c, "root", "root-password")
        c.cookies.clear()  # programmatic callers carry the token, not the jar

        r = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["principal"]["via"] == "bearer"

        # ...and it is a first-class credential for every endpoint, not a
        # special case for auth/me
        r = await c.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text

    async def test_cookie_beats_bearer(self, client):
        """Two credentials for two different accounts: the session cookie must
        win, or a browser with a stale client token would silently switch user."""
        c, sc = client
        await _login(c, "root", "root-password")  # the jar holds root's session
        await sc.auth.create_user(username="op", password="op-password", roles=["operator"])
        # log op in on a SEPARATE client so the first client's jar keeps only
        # root's cookie while we hold op's bearer token
        op_transport = httpx.ASGITransport(app=build_app(sc))
        async with httpx.AsyncClient(transport=op_transport, base_url="http://test") as op_c:
            op_token = await _login(op_c, "op", "op-password")

        r = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {op_token}"})
        body = r.json()
        assert body["principal"]["via"] == "session"
        assert body["principal"]["id"] == "root"

    async def test_bearer_beats_dev_header(self, client):
        c, _ = client
        token = await _login(c, "root", "root-password")
        c.cookies.clear()
        r = await c.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}", **_header({"id": "u-planner", "Role": ["visitor"]})},
        )
        assert r.json()["principal"]["via"] == "bearer"

    async def test_expired_or_garbage_bearer_falls_through(self, client):
        c, _ = client
        r = await c.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"})
        assert r.status_code == 401

    async def test_dev_auth_off_rejects_the_header_but_not_the_token(
        self, client, golden_pkg_path, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("ONTOGENY_ADMIN_USER", "root")
        monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", "root-password")
        pkg_root = tmp_path / "pkg-secure"
        shutil.copytree(golden_pkg_path, pkg_root)
        settings = Settings(
            db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'secure.db'}",
            dev_auth=False,
            env={"ERP_DSN": f"sqlite+aiosqlite:///{tmp_path / 'erp.db'}"},
        )
        sc = ServiceContext(settings, str(pkg_root))
        await sc.initialize()
        transport = httpx.ASGITransport(app=build_app(sc))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            token = await _login(c, "root", "root-password")
            c.cookies.clear()
            r = await c.get("/api/v1/auth/me", headers=_header({"id": "u-planner", "Role": ["visitor"]}))
            assert r.status_code == 401, "dev_auth off -> the header must not sign anyone in"
            r = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            assert r.json()["principal"]["via"] == "bearer"


class TestSimulationIsDecidedByCedar:
    async def test_simulated_identity_is_authorized_like_any_principal(self, client):
        """Simulation changes who asks; the policy plane still answers. The
        dry-run validate is rules+policy only, so a role granted through the
        matrix really permits a simulated principal and an ungranted one is
        denied by the default."""
        c, sc = client
        await sc.auth.ensure_admin()
        h = _header(ADMIN)

        visitor = {"id": "u-v", "Role": ["visitor"]}
        validate = "/api/v1/actions/release-production-order/validate"
        body = {"parameters": {}, "target_id": "PO-1002"}
        r = await c.post(validate, headers=_header(visitor), json=body)
        assert r.status_code == 200, r.text
        assert r.json()["policy"]["allow"] is False, "no permit for the role -> Cedar denies"

        # grant a role the action through the role matrix, simulate it, pass
        saved = await c.put(
            "/api/v1/admin/roles/closer", headers=h, json={"name": "closer", "actions": ["release-production-order"]}
        )
        assert saved.status_code == 200, saved.text
        closer = {"id": "u-c", "Role": ["closer"]}
        r = await c.post(validate, headers=_header(closer), json=body)
        assert r.status_code == 200, r.text
        assert r.json()["policy"]["allow"] is True, "matrix grant -> Cedar permits the simulation"


class TestBootstrapCredential:
    @pytest_asyncio.fixture()
    async def default_pw_ctx(self, golden_pkg_path, tmp_path, monkeypatch, caplog):
        """Initialize a fresh context without a configured password."""
        import shutil as _shutil

        monkeypatch.setenv("ONTOGENY_ADMIN_USER", "root")
        monkeypatch.delenv("ONTOGENY_ADMIN_PASSWORD", raising=False)
        pkg_root = tmp_path / "pkg"
        _shutil.copytree(golden_pkg_path, pkg_root)
        settings = Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
        sc = ServiceContext(settings, str(pkg_root))
        await sc.initialize()
        path = tmp_path / "admin-bootstrap-password"
        password = path.read_text().strip()
        assert path.stat().st_mode & 0o777 == 0o600
        assert all(password not in r.getMessage() for r in caplog.records)
        return sc, password

    async def test_unset_env_generates_a_usable_password_once(self, default_pw_ctx, caplog, monkeypatch):
        from ontogeny.errors import AuthenticationError

        sc, password = default_pw_ctx
        assert len(password) >= 32
        token, principal = await sc.auth.login("root", password)
        assert token and principal["id"] == "root"
        with pytest.raises(AuthenticationError):
            await sc.auth.login("root", "ontogeny@2026")
        monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", "new-password")
        caplog.clear()
        assert await sc.auth.ensure_admin() is None
        assert not any("credential file: " in r.getMessage() for r in caplog.records)
        from ontogeny.auth.service import bootstrap_password_path

        assert bootstrap_password_path(sc.settings).read_text().strip() == password
        assert (await sc.auth.login("root", password))[0]
        with pytest.raises(AuthenticationError):
            await sc.auth.login("root", "new-password")

    async def test_env_override_wins_over_default(self, client):
        """The environment variable selects the initial credential."""
        from ontogeny.errors import AuthenticationError

        _c, sc = client
        token, principal = await sc.auth.login("root", "root-password")
        assert token and principal["id"] == "root"
        with pytest.raises(AuthenticationError):
            await sc.auth.login("root", "ontogeny@2026")

    async def test_independent_databases_get_distinct_passwords(
        self, default_pw_ctx, golden_pkg_path, tmp_path, caplog
    ):
        first, first_password = default_pw_ctx
        caplog.clear()
        pkg_root = tmp_path / "second-pkg"
        shutil.copytree(golden_pkg_path, pkg_root)
        second_dir = tmp_path / "second"
        second_dir.mkdir()
        settings = Settings(db_dsn=f"sqlite+aiosqlite:///{second_dir / 'second-auth.db'}")
        second = ServiceContext(settings, str(pkg_root))
        await second.initialize()
        second_password = (second_dir / "admin-bootstrap-password").read_text().strip()
        assert all(second_password not in r.getMessage() for r in caplog.records)
        assert first_password != second_password
        assert (await first.auth.login("root", first_password))[0]
        assert (await second.auth.login("root", second_password))[0]

    async def test_configured_password_is_not_logged(self, golden_pkg_path, tmp_path, monkeypatch, caplog):
        import logging

        password = "operator-configured-password"
        monkeypatch.setenv("ONTOGENY_ADMIN_USER", "root")
        monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", password)
        caplog.set_level(logging.INFO, logger="ontogeny.auth")
        pkg_root = tmp_path / "configured-pkg"
        shutil.copytree(golden_pkg_path, pkg_root)
        settings = Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'configured-auth.db'}")
        sc = ServiceContext(settings, str(pkg_root))
        await sc.initialize()
        assert (await sc.auth.login("root", password))[0]
        assert all(password not in record.getMessage() for record in caplog.records)
        assert not (tmp_path / "admin-bootstrap-password").exists()

    async def test_existing_credential_file_is_not_overwritten(self, golden_pkg_path, tmp_path, monkeypatch):
        from ontogeny.errors import StoreError

        monkeypatch.delenv("ONTOGENY_ADMIN_PASSWORD", raising=False)
        path = tmp_path / "admin-bootstrap-password"
        path.write_text("preserve me")
        settings = Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
        sc = ServiceContext(settings, str(golden_pkg_path))
        with pytest.raises(StoreError, match="credential file already exists"):
            await sc.initialize()
        assert path.read_text() == "preserve me"

    async def test_credential_symlink_is_not_followed(self, golden_pkg_path, tmp_path, monkeypatch):
        from ontogeny.errors import StoreError

        monkeypatch.delenv("ONTOGENY_ADMIN_PASSWORD", raising=False)
        target = tmp_path / "target"
        target.write_text("keep target")
        (tmp_path / "admin-bootstrap-password").symlink_to(target)
        settings = Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
        sc = ServiceContext(settings, str(golden_pkg_path))
        with pytest.raises(StoreError, match="credential file already exists"):
            await sc.initialize()
        assert target.read_text() == "keep target"

    async def test_explicit_data_dir_receives_credential(self, golden_pkg_path, tmp_path, monkeypatch):
        monkeypatch.delenv("ONTOGENY_ADMIN_PASSWORD", raising=False)
        data_dir = tmp_path / "private-state"
        settings = Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}", data_dir=str(data_dir))
        sc = ServiceContext(settings, str(golden_pkg_path))
        await sc.initialize()
        password = (data_dir / "admin-bootstrap-password").read_text().strip()
        assert (await sc.auth.login("admin", password))[0]
        assert not (tmp_path / "admin-bootstrap-password").exists()

    async def test_file_survives_error_after_account_commit(self, golden_pkg_path, tmp_path, monkeypatch):
        from ontogeny.auth.service import AuthService

        monkeypatch.delenv("ONTOGENY_ADMIN_PASSWORD", raising=False)
        settings = Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
        original = AuthService.create_user

        async def create_then_fail(self, **kwargs):
            await original(self, **kwargs)
            raise RuntimeError("after commit")

        monkeypatch.setattr(AuthService, "create_user", create_then_fail)
        sc = ServiceContext(settings, str(golden_pkg_path))
        with pytest.raises(RuntimeError, match="after commit"):
            await sc.initialize()
        password = (tmp_path / "admin-bootstrap-password").read_text().strip()
        assert (await sc.auth.login("admin", password))[0]
