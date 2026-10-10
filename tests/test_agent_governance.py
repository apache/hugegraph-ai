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
"""Governance hardening: driver accountability, atomic budgets, the wall
clock, and the frozen catalog.

Each block pins one fix:

- A2  driver authentication: dev_auth off => anonymous drivers are refused on
      BOTH the REST agent endpoints and /mcp; a signed-in driver is recorded
      on the session and every step (the trail answers WHO, I4).
- A3  atomic budget accounting: concurrent callers cannot squeeze past a
      step/write ceiling (conditional increments, portable to Postgres).
- A4  wall_ms is enforced: the third budget gate actually fires, per RUN
      (a fresh run gets a fresh clock).
- B5  the frozen catalog: a plugin edit mid-session changes nothing for a
      running session -- the documented contract, now the actual behaviour.
"""
from __future__ import annotations

import asyncio
import os
import shutil

import httpx
import pytest
import pytest_asyncio
from dataclasses import replace

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.demo import seed_from_package
from ontogeny.service import ServiceContext

PLUGIN = """\
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata:
  name: planning-copilot
spec:
  engine: { kind: builtin-llm }
  principal:
    id: "agent:planning-copilot"
    Role: [planner]
    site: plant-north
  tools:
    allow: [describe_ontology, search_work_center, search_production_order,
            act_release_production_order]
  approval: { writes: confirm }
  budget: { steps: 6, wall_ms: 60000, writes_per_session: 3 }
"""


def _settings(tmp_path, src, *, db_dsn: str | None = None, **over) -> Settings:
    over.setdefault("dev_auth", True)  # the platform default is OFF; tests opt in
    return Settings(
        db_dsn=db_dsn or f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}",
             "WMS_WEBHOOK": "https://wms.example.test/hook"},
        **over,
    )


async def _make(golden_pkg_path, tmp_path, *, db_dsn: str | None = None, **settings_over):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(PLUGIN, encoding="utf-8")
    src = tmp_path / "erp.db"
    seed_from_package(golden_pkg_path, src, force=True)
    sc = ServiceContext(_settings(tmp_path, src, db_dsn=db_dsn, **settings_over), str(root))
    await sc.initialize()
    for t in sc.compiled.objects:
        await sc.sync(t)
    return sc


@pytest_asyncio.fixture()
async def sc(golden_pkg_path, tmp_path):
    return await _make(golden_pkg_path, tmp_path)


@pytest_asyncio.fixture()
async def client(golden_pkg_path, tmp_path):
    # no lifespan wrapper here: the MCP session manager carries anyio cancel
    # scopes that must exit in the task that entered them (fixtures tear down
    # in another task); the REST surface below needs no lifespan anyway
    sc = await _make(golden_pkg_path, tmp_path)
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, sc


# ---------------------------------------------------------------------- A2


class TestDriverAuthentication:
    async def test_dev_mode_records_anonymous_driver(self, client):
        """dev_auth on (opt-in): an anonymous driver may open and drive, and
        the session honestly records that 'anonymous' asked for it."""
        c, _ = client
        r = await c.post("/api/v1/agent/sessions",
                         json={"plugin": "planning-copilot", "task": "x"})
        assert r.status_code == 200
        sess = r.json()
        assert sess["driver"]["id"] == "anonymous"
        assert sess["driver"]["via"] == "anonymous"

        out = (await c.post("/api/v1/agent/sessions/1/tools/search_work_center",
                            json={"limit": 2})).json()
        assert out["outcome"] == "ok"
        detail = (await c.get("/api/v1/agent/sessions/1")).json()
        assert detail["steps"][0]["driver"] == "anonymous"

    async def test_dev_auth_off_refuses_anonymous_and_accepts_bearer(self, golden_pkg_path, tmp_path):
        sc = await _make(golden_pkg_path, tmp_path, dev_auth=False)
        await sc.auth.create_user(username="op", password="op-password-123",
                                  roles=["planner"], is_admin=True)
        app = build_app(sc)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/api/v1/agent/sessions",
                             json={"plugin": "planning-copilot", "task": "x"})
            assert r.status_code == 401
            assert "authenticated driver" in r.json()["detail"]

            login = await c.post("/api/v1/auth/login",
                                 json={"username": "op", "password": "op-password-123"})
            token = login.json()["token"]
            r = await c.post("/api/v1/agent/sessions",
                             json={"plugin": "planning-copilot", "task": "x"},
                             headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            assert r.json()["driver"]["id"] == "op"
            # cookie rides along after login and wins by design (the browser
            # keeps its session); what matters is the identity is real
            assert r.json()["driver"]["via"] in ("bearer", "session")

            # tool calls require a driver too: a cookie-less client is
            # refused (the logged-in client above keeps its session cookie,
            # which is exactly the browser behaviour we want to keep)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as bare:
                r = await bare.post("/api/v1/agent/sessions/1/tools/describe_ontology", json={})
                assert r.status_code == 401
            r = await c.post("/api/v1/agent/sessions/1/tools/describe_ontology", json={},
                             headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200

    async def test_mcp_bearer_gate(self, golden_pkg_path, tmp_path):
        """dev_auth off: /mcp refuses anonymous, serves a valid bearer, and
        the opened session records the token's principal as its driver."""
        sc = await _make(golden_pkg_path, tmp_path, dev_auth=False)
        await sc.auth.create_user(username="mcpop", password="mcp-password-123",
                                  roles=["planner"], is_admin=True)
        app = build_app(sc)
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as hc:
                r = await hc.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                "params": {"protocolVersion": "2025-06-18",
                                                           "capabilities": {},
                                                           "clientInfo": {"name": "t", "version": "0"}}},
                                  headers={"Accept": "application/json, text/event-stream"})
                assert r.status_code == 401

                login = await hc.post("/api/v1/auth/login",
                                      json={"username": "mcpop", "password": "mcp-password-123"})
                token = login.json()["token"]
                from mcp.client.session import ClientSession
                from mcp.client.streamable_http import streamable_http_client

                async with httpx.AsyncClient(
                        transport=transport, base_url="http://test",
                        headers={"Authorization": f"Bearer {token}"}) as authed:
                    async with streamable_http_client(
                            "http://test/mcp", http_client=authed) as streams:
                        async with ClientSession(streams[0], streams[1]) as sess:
                            await sess.initialize()
                            opened = await sess.call_tool(
                                "agent_open_session",
                                {"plugin": "planning-copilot", "task": "wire"})
                            assert opened.is_error is False
                            assert opened.structured_content["driver"]["id"] == "mcpop"

    async def test_engine_steps_are_attributed_to_the_engine(self, sc):
        sid = (await sc.agents.open_session("planning-copilot", "x"))["id"]
        await sc.agents.call_tool(sid, "describe_ontology", {}, engine=True)
        sess = await sc.agents.get_session(sid)
        assert sess["steps"][0]["driver"] == "engine"


# ---------------------------------------------------------------------- A3


class TestAtomicBudgets:
    async def test_concurrent_calls_cannot_squeeze_past_step_cap(self, sc):
        """budget.steps = 6: 12 concurrent calls must produce exactly 6
        executed steps and 6 structured refusals -- the check and the
        increment are one statement, so no read-modify-write race."""
        sid = (await sc.agents.open_session("planning-copilot", "concurrent"))["id"]
        outs = await asyncio.gather(*[
            sc.agents.call_tool(sid, "describe_ontology", {}) for _ in range(12)
        ])
        ok = [o for o in outs if o["outcome"] == "ok"]
        refused = [o for o in outs if o["outcome"] == "AGENT_BUDGET_EXCEEDED"]
        assert len(ok) == 6, [o.get("outcome") for o in outs]
        assert len(refused) == 6
        sess = await sc.agents.get_session(sid)
        assert sess["budget"]["steps_used"] == 6
        assert len(sess["steps"]) == 6

    async def test_concurrent_writes_cannot_squeeze_past_write_cap(self, sc):
        """confirm-gated writes: budget.writes = 3, so exactly 3 pending
        approvals may be created by 8 concurrent write attempts."""
        sid = (await sc.agents.open_session("planning-copilot", "writes race"))["id"]
        outs = await asyncio.gather(*[
            sc.agents.call_tool(sid, "act_release_production_order",
                                {"parameters": {}, "target_id": f"PO-100{i}"})
            for i in range(8)
        ])
        pending = [o for o in outs if o["outcome"] == "pending_approval"]
        refused = [o for o in outs if o["outcome"] == "AGENT_BUDGET_EXCEEDED"]
        assert len(pending) == 3, [o.get("outcome") for o in outs]
        assert len(refused) == 5
        sess = await sc.agents.get_session(sid)
        assert sess["budget"]["writes_used"] == 3

    async def test_rejection_refunds_exactly_one_slot(self, sc):
        sid = (await sc.agents.open_session("planning-copilot", "refund"))["id"]
        first = await sc.agents.call_tool(sid, "act_release_production_order",
                                          {"parameters": {}, "target_id": "PO-1002"})
        assert first["outcome"] == "pending_approval"
        planner = {"id": "u-planner", "Role": ["planner"], "site": "plant-north"}
        await sc.agents.decide(first["approval_id"], "rejected", planner)
        sess = await sc.agents.get_session(sid)
        assert sess["budget"]["writes_used"] == 0  # refunded, atomically

    @pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"),
                        reason="set ONTOGENY_PG_DSN to run the Postgres concurrency probe")
    async def test_concurrent_step_cap_on_postgres(self, golden_pkg_path, tmp_path):
        """The same atomicity probe on Postgres, where read-modify-write
        races actually lose updates (SQLite serializes writes and hides them).

        Run with: ONTOGENY_PG_DSN=postgresql+asyncpg://.../ontogeny_test pytest \
            tests/test_agent_governance.py -k postgres
        """
        sc = await _make(golden_pkg_path, tmp_path,
                         db_dsn=os.environ["ONTOGENY_PG_DSN"])
        sid = (await sc.agents.open_session("planning-copilot", "pg race"))["id"]
        outs = await asyncio.gather(*[
            sc.agents.call_tool(sid, "describe_ontology", {}) for _ in range(12)
        ])
        ok = [o for o in outs if o["outcome"] == "ok"]
        assert len(ok) == 6, [o.get("outcome") for o in outs]


# ---------------------------------------------------------------------- A4


class TestWallBudget:
    async def test_wall_ms_refuses_after_the_run_clock_expires(self, sc):
        s = await sc.agents.open_session("planning-copilot", "slow",
                                         budget={"wall_ms": 50})
        sid = s["id"]
        await asyncio.sleep(0.2)  # let the 50ms clock run out
        out = await sc.agents.call_tool(sid, "describe_ontology", {})
        assert out["outcome"] == "AGENT_BUDGET_EXCEEDED"
        assert "wall budget" in out["error"]
        # the platform parked the session: no zombie runs
        sess = await sc.agents.get_session(sid)
        assert sess["status"] == "budget_exhausted"

    async def test_a_fresh_run_gets_a_fresh_clock(self, sc):
        s = await sc.agents.open_session("planning-copilot", "re-run",
                                         budget={"wall_ms": 50})
        sid = s["id"]
        await asyncio.sleep(0.2)
        out = await sc.agents.call_tool(sid, "describe_ontology", {})
        assert out["outcome"] == "AGENT_BUDGET_EXCEEDED"
        # driving again resets run_started_at: the new run is live again
        await sc.agents.start_run(sid, task="second wind")
        out = await sc.agents.call_tool(sid, "describe_ontology", {})
        assert out["outcome"] == "ok"

    async def test_wall_zero_means_unlimited(self, sc):
        s = await sc.agents.open_session("planning-copilot", "no wall",
                                         budget={"wall_ms": 0})
        await asyncio.sleep(0.05)
        out = await sc.agents.call_tool(s["id"], "describe_ontology", {})
        assert out["outcome"] == "ok"


# ---------------------------------------------------------------------- B5


class TestFrozenCatalog:
    async def test_plugin_edit_cannot_change_a_running_session(self, sc):
        """The documented contract, now enforced: whatever the plugin's
        allow-list says TODAY, the session keeps the catalog it was opened
        with -- edits can neither widen nor narrow it."""
        sid = (await sc.agents.open_session("planning-copilot", "freeze"))["id"]

        # 1) NARROWING: strip the plugin's allow-list down to nothing
        plug = sc.compiled.agent_plugins["planning-copilot"]
        narrowed = plug.model_copy(deep=True)
        narrowed.spec.tools.allow = []
        original = sc.compiled
        sc.compiled = replace(original,
                              agent_plugins={**original.agent_plugins,
                                             "planning-copilot": narrowed})
        try:
            out = await sc.agents.call_tool(sid, "search_work_center", {"limit": 2})
            assert out["outcome"] == "ok"  # still in the FROZEN catalog
        finally:
            sc.compiled = original

        # 2) WIDENING: grant the plugin a tool it never had
        widened = plug.model_copy(deep=True)
        widened.spec.tools.allow = [*plug.spec.tools.allow, "search_material"]
        sc.compiled = replace(original,
                              agent_plugins={**original.agent_plugins,
                                             "planning-copilot": widened})
        try:
            out = await sc.agents.call_tool(sid, "search_material", {"limit": 2})
            assert out["outcome"] == "AGENT_TOOL_NOT_ALLOWED"  # not in the freeze
        finally:
            sc.compiled = original

    async def test_vanished_plugin_still_runs_readonly_and_gates_writes(self, sc):
        """Even deleting the plugin row mid-session cannot strand or widen a
        session: reads run on the frozen catalog + frozen principal, and
        writes fall back to the confirm gate (never silent auto-execution)."""
        sid = (await sc.agents.open_session("planning-copilot", "survivor"))["id"]
        original = sc.compiled
        sc.compiled = replace(
            original,
            agent_plugins={k: v for k, v in original.agent_plugins.items()
                           if k != "planning-copilot"})
        try:
            out = await sc.agents.call_tool(sid, "describe_ontology", {})
            assert out["outcome"] == "ok"

            out = await sc.agents.call_tool(sid, "act_release_production_order",
                                            {"parameters": {}, "target_id": "PO-1002"})
            assert out["outcome"] == "pending_approval"  # conservative fallback
        finally:
            sc.compiled = original

    async def test_legacy_session_freezes_at_first_use(self, sc):
        """Rows created before the freeze column existed recompute once and
        persist the freeze -- never silently narrowing mid-flight."""
        sid = (await sc.agents.open_session("planning-copilot", "legacy"))["id"]
        async with sc.sessionmaker() as s:
            from sqlalchemy import update as sa_update

            from ontogeny.agent.models import AgentSessionRow
            await s.execute(sa_update(AgentSessionRow)
                            .where(AgentSessionRow.id == sid)
                            .values(tools_json=None))
            await s.commit()
        out = await sc.agents.call_tool(sid, "describe_ontology", {})
        assert out["outcome"] == "ok"
        sess = await sc.agents.get_session(sid)
        assert "describe_ontology" in sess["tools"]  # frozen at first use
