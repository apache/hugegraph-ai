# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import gzip
import http.server
import json
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastmcp import Client
from pyhugegraph.utils.huge_config import HGraphConfig
from pyhugegraph.utils.huge_requests import HGraphSession

import hugegraph_mcp.tools.manage_schema as schema_mod
from hugegraph_mcp import server
from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.events import ResourceEvent
from hugegraph_mcp.plan_store import SQLitePlanStore, plan_store_from_config
from hugegraph_mcp.resource_uri import build_graph_resource_uri
from hugegraph_mcp.resources import read_plan_resource
from hugegraph_mcp.runtime import (
    build_runtime,
    reset_current_actor,
    reset_current_runtime,
    set_current_actor,
    set_current_runtime,
)
from hugegraph_mcp.stores.base import Actor, SyncToAsyncPlanStoreAdapter
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)


def test_legacy_apply_schema_enforces_write_actor_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    anon = Actor(
        tenant="default",
        subject="anonymous",
        scopes=frozenset(),
        issuer="http-bearer",
        is_anonymous=True,
    )
    token = set_current_actor(anon)
    try:
        res = server.apply_schema_tool(
            mode="apply",
            operations=[
                {
                    "type": "create_property_key",
                    "name": "blocked_pk",
                    "data_type": "TEXT",
                    "cardinality": "SINGLE",
                }
            ],
            confirm=True,
        )
        assert res["ok"] is False
        assert res["error"]["type"] == "READONLY_VIOLATION"
    finally:
        reset_current_actor(token)


def test_sqlite_plan_ownership_enforced_across_tools_and_resources(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    alice = Actor(
        tenant="default",
        subject="alice",
        scopes=frozenset({"mcp:read", "mcp:write"}),
        issuer="http-bearer",
    )
    bob = Actor(
        tenant="default",
        subject="bob",
        scopes=frozenset({"mcp:read", "mcp:write"}),
        issuer="http-bearer",
    )

    cfg = MCPConfig.from_env()
    rt = build_runtime(cfg)
    rt_tok = set_current_runtime(rt)
    try:
        a_tok = set_current_actor(alice)
        try:
            plan = WritePlan(
                plan_id="plan_owned_1",
                tool_name="apply_schema_tool",
                graph_target=GraphTarget(
                    graph_url="http://127.0.0.1:8080",
                    graphspace="DEFAULT",
                    graph_name="hugegraph",
                ),
                operations=(
                    OperationPlan(
                        operation_id="op_1",
                        kind="create_property_key",
                        target={"name": "k1"},
                        expected_state={"exists": True},
                        desired_state={"exists": True},
                    ),
                ),
                payload_digest="digest_1",
                schema_fingerprint="fp_1",
                created_at=int(time.time()),
                expires_at=int(time.time()) + 300,
                status=PlanStatus.ISSUED,
                principal="admin",
            )
            plan_store_from_config(cfg).save_plan(plan)
            alice_status = server.get_write_status_tool("plan_owned_1")
            assert alice_status["ok"] is True
            alice_res = json.loads(asyncio.run(read_plan_resource("plan_owned_1")))
            assert alice_res["plan_id"] == "plan_owned_1"
        finally:
            reset_current_actor(a_tok)

        b_tok = set_current_actor(bob)
        try:
            bob_status = server.get_write_status_tool("plan_owned_1")
            assert bob_status["ok"] is False
            bob_confirm = server.confirm_write_tool("plan_owned_1")
            assert bob_confirm["ok"] is False
            with pytest.raises(ValueError):
                asyncio.run(read_plan_resource("plan_owned_1"))
        finally:
            reset_current_actor(b_tok)
    finally:
        reset_current_runtime(rt_tok)


def test_runtime_config_isolated_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "env_graph")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    cfg = MCPConfig.from_env(
        {
            "HUGEGRAPH_GRAPH": "isolated_graph",
            "HUGEGRAPH_MCP_READONLY": "true",
            "HUGEGRAPH_MCP_STATE_DIR": str(tmp_path),
        }
    )
    rt = build_runtime(cfg)
    tok = set_current_runtime(rt)
    try:
        eff = get_effective_config()
        assert eff.graph == "isolated_graph"
        assert eff.is_readonly() is True
        gate = server._admin_gate("refresh_vid_embeddings_tool", requires_write=True)
        assert gate is not None
        assert gate["error"]["type"] in {"FEATURE_DISABLED", "READONLY_VIOLATION"}
    finally:
        reset_current_runtime(tok)


def test_confirm_write_unknown_invalidates_cache_and_publishes_from_thread(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    state = {"schema": {"propertykeys": [], "vertexlabels": [], "edgelabels": [], "indexlabels": []}}
    committed = False

    def fake_read(*args, **kwargs):
        if committed:
            raise TimeoutError("post-write read timeout")
        return state

    monkeypatch.setattr(schema_mod, "current_live_schema", fake_read)
    manager = Mock()

    def do_create():
        nonlocal committed
        committed = True

    manager.property_key.return_value.create.side_effect = do_create
    monkeypatch.setattr(schema_mod, "_schema_manager", lambda: manager)

    async def scenario() -> None:
        cfg = MCPConfig.from_env()
        rt = build_runtime(cfg)
        rt._loop = asyncio.get_running_loop()
        received: list[ResourceEvent] = []

        async def collect():
            async for ev in rt.event_bus.subscribe():
                received.append(ev)
                if len(received) >= 2:
                    break

        sub_task = asyncio.create_task(collect())
        await asyncio.sleep(0)

        tok = set_current_runtime(rt)
        try:
            dry = server.apply_schema_tool(
                mode="dry_run",
                operations=[
                    {
                        "type": "create_property_key",
                        "name": "unknown_pk",
                        "data_type": "TEXT",
                        "cardinality": "SINGLE",
                    }
                ],
            )
            key = ("default", "DEFAULT", "hugegraph", "schema", "public")
            rt.resource_cache.set(key, {"schema": "stale"}, now=time.time())

            res = await asyncio.to_thread(server.confirm_write_tool, dry["data"]["plan_id"])
            assert res["ok"] is False
            assert res["error"]["details"]["status"] == "UNKNOWN"
            assert rt.resource_cache.get(key, now=time.time(), ttl_s=30) is None
            await asyncio.wait_for(sub_task, timeout=2.0)
            assert any(ev.kind == "invalidated" for ev in received)
        finally:
            reset_current_runtime(tok)

    asyncio.run(scenario())


def test_mcp_resource_subscribe_and_remote_cache_invalidation(tmp_path: Path) -> None:
    cfg = MCPConfig.from_env(
        {
            "HUGEGRAPH_MCP_STATE_DIR": str(tmp_path),
            "HUGEGRAPH_MCP_READONLY": "true",
        }
    )
    srv = server.create_server(cfg)

    async def scenario() -> None:
        caps = srv._mcp_server.get_capabilities()
        assert caps.resources is not None
        assert caps.resources.subscribe is True
        async with Client(srv):
            uri = build_graph_resource_uri("default", "DEFAULT", "hugegraph", "schema")
            rt = srv._hugegraph_runtime
            sub_entry = srv._mcp_server._request_handlers["resources/subscribe"]
            unsub_entry = srv._mcp_server._request_handlers["resources/unsubscribe"]
            # Simulate a 2025-11-25 client session subscribing via the registered MCP handler
            delivered: list[str] = []

            class _FakeSession:
                session_id = "sess-1"

                async def send_resource_updated(self, updated_uri) -> None:
                    delivered.append(str(updated_uri))

            session = _FakeSession()
            rt.subscription_manager.subscribe_session("sess-1", uri, session)
            assert len(rt.subscription_manager._sessions) == 1
            key = ("default", "DEFAULT", "hugegraph", "schema", "public")
            rt.resource_cache.set(key, {"schema": "stale"}, now=time.time())
            await rt.event_bus.publish(
                ResourceEvent.create(
                    deployment="default",
                    graphspace="DEFAULT",
                    graph="hugegraph",
                    uri=uri,
                    kind="updated",
                    resource_version=42,
                )
            )
            await asyncio.sleep(0.05)
            assert rt.resource_cache.get(key, now=time.time(), ttl_s=30) is None
            assert delivered == [uri]
            rt.subscription_manager.unsubscribe("sess-1", uri)
            assert len(rt.subscription_manager._sessions) == 0
            assert sub_entry is not None and unsub_entry is not None

    asyncio.run(scenario())


def test_sqlite_plan_adapter_projects_operation_receipts(tmp_path: Path) -> None:
    store = SQLitePlanStore(tmp_path)
    actor = Actor(
        tenant="default",
        subject="alice",
        scopes=frozenset({"mcp:read", "mcp:write"}),
        issuer="http-bearer",
    )
    adapter = SyncToAsyncPlanStoreAdapter(store)
    plan = WritePlan(
        plan_id="plan_rcpt_1",
        tool_name="apply_schema_tool",
        graph_target=GraphTarget(
            graph_url="http://127.0.0.1:8080",
            graphspace="DEFAULT",
            graph_name="hugegraph",
        ),
        operations=(
            OperationPlan(
                operation_id="op_1",
                kind="create_property_key",
                target={"name": "k1"},
                expected_state={"exists": True},
                desired_state={"exists": True},
            ),
        ),
        principal="admin",
        payload_digest="digest_2",
        schema_fingerprint="fp_2",
        status=PlanStatus.ISSUED,
        created_at=int(time.time()),
        expires_at=int(time.time()) + 300,
    )

    async def scenario() -> None:
        await adapter.create(plan, actor)
        lease = await adapter.claim("plan_rcpt_1", actor, holder="worker")
        await adapter.record_operation(
            lease,
            actor,
            "op_1",
            expected_version=lease.plan_version,
            receipt=ApplyReceipt(
                plan_id="plan_rcpt_1",
                operation_id="op_1",
                status=ApplyStatus.UNKNOWN,
                observed_state={"exists": None},
                attempt=1,
                reconciliation_required=True,
                committed_at=None,
                reason_code="READ_TIMEOUT",
            ),
        )
        view = await adapter.read("plan_rcpt_1", actor)
        assert len(view.receipts) == 1
        assert view.receipts[0]["status"] == "UNKNOWN"

    asyncio.run(scenario())


def test_request_guard_decompresses_gzip_response() -> None:
    payload = json.dumps({"graphs": ["hugegraph"]}).encode("utf-8")
    compressed = gzip.compress(payload)

    class GzipHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(compressed)))
            self.end_headers()
            self.wfile.write(compressed)

        def log_message(self, format: str, *args) -> None:
            return

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GzipHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        cfg = HGraphConfig(
            url=f"http://127.0.0.1:{httpd.server_port}",
            graph_name="hugegraph",
            username="admin",
            password="",
            graphspace="DEFAULT",
        )
        session = HGraphSession(cfg)
        with session.request_guard(max_response_bytes=1024 * 1024, deadline_seconds=5.0):
            resp = session.request("/graphs", "get")
        assert resp == {"graphs": ["hugegraph"]}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_confirmation_store_enforces_owner_principal(tmp_path: Path) -> None:
    from hugegraph_mcp.confirmation_store import ConfirmationNotIssuedError, ConfirmationStore

    store = ConfirmationStore(tmp_path)
    alice = Actor(tenant="default", subject="alice", scopes=frozenset({"mcp:write"}), issuer="http-bearer")
    bob = Actor(tenant="default", subject="bob", scopes=frozenset({"mcp:write"}), issuer="http-bearer")
    expires_at = int(time.time()) + 120

    tok = set_current_actor(alice)
    try:
        store.issue(nonce="nonce-1", plan_hash="hash-1", expires_at=expires_at, plan_payload={"op": "x"})
    finally:
        reset_current_actor(tok)

    tok = set_current_actor(bob)
    try:
        with pytest.raises(ConfirmationNotIssuedError):
            store.consume(nonce="nonce-1", plan_hash="hash-1", expires_at=expires_at)
    finally:
        reset_current_actor(tok)

    tok = set_current_actor(alice)
    try:
        payload = store.consume(nonce="nonce-1", plan_hash="hash-1", expires_at=expires_at)
        assert payload == {"op": "x"}
    finally:
        reset_current_actor(tok)


def test_two_isolated_servers_do_not_cross_contaminate_runtime(tmp_path: Path) -> None:
    cfg_a = MCPConfig.from_env(
        {
            "HUGEGRAPH_GRAPH": "graph_a",
            "HUGEGRAPH_MCP_READONLY": "true",
            "HUGEGRAPH_MCP_STATE_DIR": str(tmp_path / "a"),
        }
    )
    cfg_b = MCPConfig.from_env(
        {
            "HUGEGRAPH_GRAPH": "graph_b",
            "HUGEGRAPH_MCP_READONLY": "true",
            "HUGEGRAPH_MCP_STATE_DIR": str(tmp_path / "b"),
        }
    )
    srv_a = server.create_server(cfg_a)
    srv_b = server.create_server(cfg_b)

    async def scenario() -> None:
        async with Client(srv_a) as client_a, Client(srv_b) as client_b:
            res_a = (await client_a.call_tool("get_write_status_tool", {"plan_id": "missing"})).data
            res_b = (await client_b.call_tool("get_write_status_tool", {"plan_id": "missing"})).data
            assert res_a["meta"]["graph"] == "graph_a"
            assert res_b["meta"]["graph"] == "graph_b"

    asyncio.run(scenario())


def test_postgres_record_operation_receipt_writes_outbox_with_applied_status() -> None:
    from hugegraph_mcp.stores.postgres import PostgresPlanStore

    executed: list[tuple[str, tuple]] = []

    class _FakeConn:
        async def fetchone(self, sql: str, params=()):
            if "FROM plan_operations o" in sql:
                return {
                    "status": "EXECUTING",
                    "attempt": 1,
                    "attempt_token": "att",
                    "lease_holder": "own",
                    "lease_active": True,
                }
            if "SELECT status, graphspace" in sql:
                return {
                    "status": "EXECUTING",
                    "graphspace": "DEFAULT",
                    "graph": "g1",
                    "payload_json": {"graph_target": {}},
                    "version": 2,
                }
            return {"ok": 1}

        async def fetchall(self, sql: str, params=()):
            return [{"status": "APPLIED"}]

        async def execute(self, sql: str, params=()):
            executed.append((sql, params))

    class _FakePool:
        async def acquire(self):
            return _FakeConn()

        async def release(self, conn, err=None):
            return None

    store = PostgresPlanStore("postgresql://u:p@localhost:5432/db", pool=_FakePool(), deployment_id="prod")
    actor = Actor(tenant="default", subject="alice", scopes=frozenset({"mcp:write"}), issuer="http-bearer")
    receipt = ApplyReceipt(
        plan_id="wp_1",
        operation_id="op_1",
        status=ApplyStatus.APPLIED,
        observed_state={"exists": True},
        attempt=1,
        reconciliation_required=False,
        committed_at=int(time.time()),
    )
    asyncio.run(store.record_operation_receipt(receipt, actor, owner_token="own", attempt_token="att"))
    outbox_inserts = [p for sql, p in executed if "INSERT INTO event_outbox" in sql]
    assert len(outbox_inserts) == 2
    assert outbox_inserts[0][1] == "prod"
    assert outbox_inserts[0][4] == "hugegraph://prod/DEFAULT/g1/schema"
    assert outbox_inserts[0][6] > 1_000_000_000_000


def test_request_guard_enforces_deadline_during_trickle_stream() -> None:
    import requests as req_lib

    class TrickleHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "100")
            self.end_headers()
            for _ in range(10):
                try:
                    self.wfile.write(b"0123456789")
                    self.wfile.flush()
                    time.sleep(0.05)
                except OSError:
                    break

        def log_message(self, format: str, *args) -> None:
            return

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), TrickleHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        cfg = HGraphConfig(
            url=f"http://127.0.0.1:{httpd.server_port}",
            graph_name="hugegraph",
            username="admin",
            password="",
            graphspace="DEFAULT",
        )
        session = HGraphSession(cfg)
        session._session.trust_env = False
        t0 = time.monotonic()
        with (
            pytest.raises(req_lib.exceptions.ReadTimeout),
            session.request_guard(max_response_bytes=1024 * 1024, deadline_seconds=0.12),
        ):
            session.request("/graphs", "get")
        elapsed = time.monotonic() - t0
        assert elapsed < 0.35
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_actor_principal_key_unambiguous() -> None:
    a1 = Actor(issuer="iss", tenant="org:team", subject="agent")
    a2 = Actor(issuer="iss", tenant="org", subject="team:agent")
    assert a1.principal_key != a2.principal_key


def test_outbox_event_relay_advances_cursor_monotonically_and_dedups() -> None:
    from hugegraph_mcp.events import OutboxEventRelay, ResourceEvent

    ev10 = ResourceEvent(
        event_id="ev-10",
        deployment="default",
        graphspace="DEFAULT",
        graph="g1",
        uri="hugegraph://default/DEFAULT/g1/schema",
        kind="schema",
        resource_version=100,
    )
    ev11 = ResourceEvent(
        event_id="ev-11",
        deployment="default",
        graphspace="DEFAULT",
        graph="g1",
        uri="hugegraph://default/DEFAULT/g1/schema",
        kind="schema",
        resource_version=101,
    )

    class _FakeOutbox:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_outbox_since(self, after_seq: int, *, limit: int = 100):
            self.calls += 1
            if self.calls == 1:
                return [(11, ev11)]
            return [(10, ev10), (11, ev11)]

    received: list[str] = []

    class _FakeBus:
        async def publish(self, ev: ResourceEvent) -> None:
            received.append(ev.event_id)

    relay = OutboxEventRelay(_FakeOutbox(), _FakeBus())

    async def _run() -> None:
        assert await relay.poll_once() == 1
        assert relay.last_seq == 11
        assert await relay.poll_once() == 0
        assert relay.last_seq == 11
        assert received == ["ev-11"]

    asyncio.run(_run())


def test_append_schema_requires_nullable_keys_for_new_properties() -> None:
    from hugegraph_mcp.tools.manage_schema import validate_schema_operations

    live = {
        "schema": {
            "propertykeys": [{"name": "name"}, {"name": "age"}, {"name": "weight"}],
            "vertexlabels": [{"name": "person", "properties": ["name"], "nullable_keys": []}],
            "edgelabels": [{"name": "knows", "properties": ["name"], "nullable_keys": []}],
        }
    }
    res_v = validate_schema_operations(
        [{"type": "append_vertex_label", "name": "person", "properties": ["age"]}],
        live_schema=live,
    )
    assert res_v["valid"] is False
    assert "nullable_keys" in str(res_v["errors"][0])

    res_e = validate_schema_operations(
        [{"type": "append_edge_label", "name": "knows", "properties": ["weight"]}],
        live_schema=live,
    )
    assert res_e["valid"] is False
    assert "nullable_keys" in str(res_e["errors"][0])


def test_mcp_resources_subscribe_and_unsubscribe_via_session(tmp_path: Path) -> None:
    from fastmcp import Client

    cfg = server.MCPConfig.from_env(
        {
            "HUGEGRAPH_MCP_ENABLE_V2_PLAN_STORE": "true",
            "HUGEGRAPH_MCP_PLAN_STORE_BACKEND": "sqlite",
            "HUGEGRAPH_MCP_PLAN_DB_PATH": str(tmp_path / "plans.db"),
            "HUGEGRAPH_MCP_READONLY": "true",
        }
    )
    srv = server.create_server(cfg)
    uri = "hugegraph://default/DEFAULT/hugegraph/schema"

    async def _run() -> None:
        async with Client(srv, mode="legacy") as client:
            rt = srv._hugegraph_runtime
            await client.session.subscribe_resource(uri)
            assert len(rt.subscription_manager._sessions) == 1
            await client.session.unsubscribe_resource(uri)
            assert len(rt.subscription_manager._sessions) == 0

    asyncio.run(_run())


def test_tighten_response_socket_timeout_preserves_stricter_existing_timeout() -> None:
    from pyhugegraph.utils.huge_requests import _tighten_response_socket_timeout

    class _FakeSock:
        def __init__(self, timeout: float | None) -> None:
            self.timeout = timeout

        def gettimeout(self) -> float | None:
            return self.timeout

        def settimeout(self, val: float) -> None:
            self.timeout = val

    class _FakeResp:
        def __init__(self, timeout: float | None) -> None:
            sock = _FakeSock(timeout)
            raw_inner = type("_Raw", (), {"_sock": sock})()
            fp_inner = type("_FP", (), {"raw": raw_inner})()
            fp_outer = type("_FPOuter", (), {"fp": fp_inner})()
            self.raw = type("_RespRaw", (), {"_fp": fp_outer})()
            self.sock = sock

    r_strict = _FakeResp(0.5)
    _tighten_response_socket_timeout(r_strict, time.monotonic() + 10.0)
    assert r_strict.sock.timeout == 0.5

    r_loose = _FakeResp(30.0)
    _tighten_response_socket_timeout(r_loose, time.monotonic() + 1.0)
    assert r_loose.sock.timeout <= 1.05


def test_list_and_cancel_write_plans_tool(monkeypatch, tmp_path: Path) -> None:
    from hugegraph_mcp.plan_store import SQLitePlanStore

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ENABLE_V2_PLAN_STORE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path))

    store = SQLitePlanStore(tmp_path)
    now = int(time.time())
    plan = WritePlan(
        plan_id="wp_list_cancel_1",
        tool_name="apply_schema_tool",
        graph_target=GraphTarget(graph_url="http://127.0.0.1:8080", graphspace="DEFAULT", graph_name="hugegraph"),
        operations=(
            OperationPlan(
                operation_id="op_1",
                kind="create_property_key",
                target={"name": "age"},
                expected_state={"exists": False},
                desired_state={"exists": True},
            ),
        ),
        principal="default:local-operator",
        payload_digest="digest_lc_1",
        schema_fingerprint="fp_lc_1",
        status=PlanStatus.ISSUED,
        created_at=now,
        expires_at=now + 300,
    )
    store.save_plan(plan)

    listed = server.list_write_plans_tool(status="ISSUED", limit=10)
    assert listed["ok"] is True
    assert listed["data"]["count"] == 1
    assert listed["data"]["plans"][0]["plan_id"] == "wp_list_cancel_1"
    assert listed["data"]["plans"][0]["graph"] == "hugegraph"

    cancelled = server.cancel_write_plan_tool("wp_list_cancel_1")
    assert cancelled["ok"] is True
    assert cancelled["data"]["status"] == "EXPIRED"
    assert cancelled["data"]["cancelled"] is True

    # Cancelling again returns WRITE_CONFLICT since it is no longer ISSUED
    again = server.cancel_write_plan_tool("wp_list_cancel_1")
    assert again["ok"] is False
    assert again["error"]["type"] == "WRITE_CONFLICT"


def test_cancel_task_tool_respects_admin_write_gate_and_cancels(monkeypatch) -> None:
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    blocked = server.cancel_task_tool(42)
    assert blocked["ok"] is False

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    class _FakeTaskMgr:
        def cancel_task(self, task_id: int) -> dict:
            return {"id": task_id, "task_status": "cancelling", "task_name": "rebuild"}

    class _FakeClient:
        def task(self) -> _FakeTaskMgr:
            return _FakeTaskMgr()

    monkeypatch.setattr("hugegraph_mcp.tools.task_tools._build_client", lambda _cfg: _FakeClient())
    res = server.cancel_task_tool(42)
    assert res["ok"] is True
    assert res["data"]["task_id"] == 42
    assert res["data"]["status"] == "cancelling"


def test_new_workflow_prompts_render_cleanly() -> None:
    from hugegraph_mcp.prompts import (
        render_ingest_text_to_graph_prompt,
        render_optimize_gremlin_query_prompt,
    )

    ingest = render_ingest_text_to_graph_prompt("Alice works at Acme.", graph_goal="Org graph")
    assert "import_graph_data_tool" in ingest
    assert "mode='ingest'" in ingest
    assert "confirmable=false" in ingest

    opt = render_optimize_gremlin_query_prompt("g.V().count()", symptom="Full scan")
    assert "execute_gremlin_read_tool" not in opt
    assert "query_graph_data_tool" in opt and "traverse_graph_tool" in opt
    assert ".limit(N)" in opt


def test_cancel_write_plan_revokes_legacy_confirmation_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ENABLE_V2_PLAN_STORE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path))

    live = {"schema": {"propertykeys": [], "vertexlabels": [], "edgelabels": [], "indexlabels": []}}
    monkeypatch.setattr("hugegraph_mcp.tools.manage_schema.current_live_schema", lambda *_a, **_k: live)
    op = [{"type": "create_property_key", "name": "nickname", "data_type": "TEXT", "cardinality": "SINGLE"}]

    dry = server.apply_schema_tool(mode="dry_run", operations=op)
    assert dry["ok"] is True
    plan_id = dry["data"]["plan_id"]
    plan_hash = dry["data"]["plan_hash"]
    nonce = dry["data"]["plan_context"]["nonce"]
    expires_at = dry["data"]["plan_context"]["expires_at"]

    cancelled = server.cancel_write_plan_tool(plan_id)
    assert cancelled["ok"] is True

    legacy_apply = server.apply_schema_tool(
        mode="apply",
        operations=op,
        confirm=True,
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
    )
    assert legacy_apply["ok"] is False
    assert legacy_apply["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_read_summary_resource_marks_unavailable_server_degraded(monkeypatch, tmp_path: Path) -> None:
    from hugegraph_mcp.resources import read_summary_resource
    from hugegraph_mcp.runtime import build_runtime

    cfg = server.MCPConfig.from_env(
        {
            "HUGEGRAPH_MCP_ENABLE_V2_PLAN_STORE": "true",
            "HUGEGRAPH_MCP_PLAN_STORE_BACKEND": "sqlite",
            "HUGEGRAPH_MCP_STATE_DIR": str(tmp_path),
        }
    )
    rt = build_runtime(cfg)
    monkeypatch.setattr(
        "hugegraph_mcp.resources.inspect_graph",
        lambda **_k: {
            "ok": True,
            "data": {"hugegraph_server_status": "unavailable"},
            "warnings": ["connection refused"],
        },
    )

    raw = asyncio.run(read_summary_resource(cfg.deployment_id, cfg.graphspace or "DEFAULT", cfg.graph, runtime=rt))
    payload = json.loads(raw)
    assert payload["status"] == "degraded"
    assert payload["warnings"] == ["connection refused"]
    assert (
        rt.resource_cache.get(
            (cfg.deployment_id, cfg.graphspace or "DEFAULT", cfg.graph, "summary", "public"), now=time.time(), ttl_s=30
        )
        is None
    )
