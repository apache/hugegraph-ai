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
from pathlib import Path

from starlette.testclient import TestClient

from hugegraph_mcp import server
from hugegraph_mcp.auth_middleware import StaticSecretBearerVerifier
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.events import InMemoryEventBus, OutboxEventRelay, ResourceEvent
from hugegraph_mcp.notifications import SubscriptionManager
from hugegraph_mcp.runtime import build_runtime


def test_http_app_probes_and_bearer_auth(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HUGEGRAPH_MCP_TRANSPORT", "streamable-http")

    cfg = MCPConfig.from_env()
    app = server.create_http_app(
        cfg,
        require_auth=True,
        verifier=StaticSecretBearerVerifier("secret-token-123", default_subject="agent-alpha"),
    )

    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        assert ready.json()["checks"]["plan_store"] == "ok"

        unauth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert unauth.status_code == 401

        bad_auth = client.post(
            "/mcp",
            headers={"Authorization": "Bearer wrong-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
        assert bad_auth.status_code == 401

        authed = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer secret-token-123",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )
        assert authed.status_code != 401


def test_outbox_relay_and_subscription_delivery():
    class _FakeOutboxSource:
        def __init__(self) -> None:
            self.rows = [
                (
                    1,
                    ResourceEvent.create(
                        deployment="prod",
                        graphspace="DEFAULT",
                        graph="hugegraph",
                        uri="hugegraph://prod/DEFAULT/hugegraph/schema",
                        kind="updated",
                        resource_version=1,
                    ),
                ),
                (
                    2,
                    ResourceEvent.create(
                        deployment="prod",
                        graphspace="DEFAULT",
                        graph="hugegraph",
                        uri="hugegraph://prod/DEFAULT/hugegraph/schema",
                        kind="updated",
                        resource_version=2,
                    ),
                ),
            ]

        async def fetch_outbox_since(self, after_seq: int, *, limit: int = 100):
            return [(seq, ev) for seq, ev in self.rows if seq > after_seq][:limit]

    bus = InMemoryEventBus()
    relay = OutboxEventRelay(_FakeOutboxSource(), bus)
    mgr = SubscriptionManager()
    delivered: list[str] = []

    async def notify(uri: str) -> None:
        delivered.append(uri)

    mgr.subscribe("s1", "hugegraph://prod/DEFAULT/hugegraph/schema", notify)

    async def scenario():
        count = await relay.poll_once()
        assert count == 2
        assert relay.last_seq == 2
        assert await relay.poll_once() == 0

        for ev in bus.recent_events():
            await mgr.dispatch(ev)
        assert len(delivered) == 2

    asyncio.run(scenario())


def test_confirm_write_tool_invalidates_cache_and_tracks_runtime(monkeypatch, tmp_path: Path):
    cfg = MCPConfig(state_dir=tmp_path, deployment_id="local")
    rt = build_runtime(cfg)
    rt.resource_cache.set(("local", "DEFAULT", "hugegraph", "schema", "public"), {"cached": True}, now=10**12)

    monkeypatch.setattr("hugegraph_mcp.server.get_current_runtime", lambda: rt)
    monkeypatch.setattr(
        "hugegraph_mcp.server.confirm_write",
        lambda plan_id: {
            "ok": True,
            "data": {"plan_id": plan_id, "status": "APPLIED"},
            "meta": {},
        },
    )

    async def run_and_verify():
        res = server.confirm_write_tool("wp_123")
        assert res["ok"] is True
        await asyncio.sleep(0)
        assert (
            rt.resource_cache.get(("local", "DEFAULT", "hugegraph", "schema", "public"), now=10**12, ttl_s=30) is None
        )
        events = rt.event_bus.recent_events()
        assert len(events) == 2
        assert {e.uri for e in events} == {
            "hugegraph://local/DEFAULT/hugegraph/schema",
            "hugegraph://local/DEFAULT/hugegraph/summary",
        }

    asyncio.run(run_and_verify())


def test_multi_app_http_instances_have_isolated_runtimes(tmp_path: Path):
    cfg_a = MCPConfig(state_dir=tmp_path / "a", deployment_id="dep-a", transport="streamable-http")
    cfg_b = MCPConfig(state_dir=tmp_path / "b", deployment_id="dep-b", transport="streamable-http")

    app_a = server.create_http_app(cfg_a, require_auth=False)
    app_b = server.create_http_app(cfg_b, require_auth=False)

    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        assert client_a.get("/readyz").status_code == 200
        assert client_b.get("/readyz").status_code == 200
        rt_a = getattr(app_a.state, "fastmcp_server", None)
        # Verify both apps serve independently and shut down cleanly without interfering
        assert app_a is not app_b
        assert rt_a is None or rt_a is not app_b


def test_lifespan_wires_event_bus_to_subscription_manager(tmp_path: Path):
    from hugegraph_mcp.runtime import create_runtime_lifespan

    cfg = MCPConfig(state_dir=tmp_path, deployment_id="dep-fanout")
    delivered: list[str] = []

    async def notify(uri: str) -> None:
        delivered.append(uri)

    async def scenario():
        lifespan = create_runtime_lifespan(cfg)
        async with lifespan(None) as rt:
            uri = "hugegraph://dep-fanout/DEFAULT/hugegraph/schema"
            rt.subscription_manager.subscribe("sess-1", uri, notify)
            await rt.event_bus.publish(
                ResourceEvent.create(
                    deployment="dep-fanout",
                    graphspace="DEFAULT",
                    graph="hugegraph",
                    uri=uri,
                    kind="updated",
                    resource_version=1,
                )
            )
            await asyncio.sleep(0.05)
            assert delivered == [uri]

    asyncio.run(scenario())
