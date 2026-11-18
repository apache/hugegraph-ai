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
import json
import time
from pathlib import Path
from typing import Any

import pytest

from hugegraph_mcp import server
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.events import ResourceEvent
from hugegraph_mcp.runtime import build_runtime
from hugegraph_mcp.stores.base import (
    Actor,
    LeaseConflictError,
    PlanNotFoundError,
    PlanOutcome,
)
from hugegraph_mcp.stores.postgres import PostgresPlanStore
from hugegraph_mcp.write_plan import ApplyReceipt, ApplyStatus, GraphTarget, OperationPlan, PlanStatus, WritePlan


def _sample_plan(plan_id: str = "wp_v2_1") -> WritePlan:
    now = int(time.time())
    return WritePlan(
        plan_id=plan_id,
        tool_name="manage_schema_tool",
        graph_target=GraphTarget(graph_url="http://127.0.0.1:8080", graph_name="hugegraph", graphspace="DEFAULT"),
        principal="default:local-operator",
        created_at=now,
        expires_at=now + 300,
        status=PlanStatus.ISSUED,
        schema_fingerprint="fp_v2",
        operations=(
            OperationPlan(
                operation_id="op_1",
                kind="property_key_create",
                target={"name": "age"},
                expected_state={},
                desired_state={"data_type": "INT"},
            ),
        ),
        payload_digest="digest_v2",
    )


def test_config_v2_transport_and_postgres_store_settings():
    cfg = MCPConfig.from_env(
        {
            "HUGEGRAPH_MCP_TRANSPORT": "streamable-http",
            "HUGEGRAPH_MCP_HTTP_HOST": "0.0.0.0",
            "HUGEGRAPH_MCP_HTTP_PORT": "9000",
            "HUGEGRAPH_MCP_HTTP_PATH": "mcp-v2",
            "HUGEGRAPH_MCP_DEPLOYMENT": "prod-cluster",
            "HUGEGRAPH_MCP_PLAN_STORE": "postgres",
            "HUGEGRAPH_MCP_PLAN_STORE_DSN": "postgresql://user:pass@db:5432/mcp",
            "HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT": "3",
        }
    )
    assert cfg.transport == "streamable-http"
    assert cfg.http_host == "0.0.0.0"
    assert cfg.http_port == 9000
    assert cfg.http_path == "/mcp-v2"
    assert cfg.deployment_id == "prod-cluster"
    assert cfg.has_safe_write_store() is True

    cfg_missing_dsn = MCPConfig.from_env(
        {
            "HUGEGRAPH_MCP_PLAN_STORE": "postgres",
            "HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT": "3",
        }
    )
    assert cfg_missing_dsn.has_safe_write_store() is False


def test_sqlite_async_adapter_lifecycle_and_event_publish(tmp_path: Path):
    cfg = MCPConfig(state_dir=tmp_path)
    rt = build_runtime(cfg)
    actor = Actor(issuer="bearer", tenant="acme", subject="agent-1")
    other = Actor(issuer="bearer", tenant="acme", subject="agent-2")
    plan = _sample_plan("wp_adapter_1")

    async def scenario():
        await rt.plan_store.check_ready()
        created = await rt.plan_store.create(plan, actor)
        assert created.status == PlanStatus.ISSUED

        with pytest.raises(PlanNotFoundError):
            await rt.plan_store.read("wp_adapter_1", other)

        lease = await rt.plan_store.claim("wp_adapter_1", actor, "worker-a", ttl_s=30)
        assert lease.fence == 1

        with pytest.raises(LeaseConflictError):
            await rt.plan_store.claim("wp_adapter_1", actor, "worker-b", ttl_s=30)

        renewed = await rt.plan_store.renew(lease, actor, ttl_s=60)
        assert renewed.expires_at >= lease.expires_at

        receipt = ApplyReceipt(
            plan_id="wp_adapter_1",
            operation_id="op_1",
            status=ApplyStatus.APPLIED,
            observed_state={"created": "age"},
        )
        updated = await rt.plan_store.record_operation(
            lease, actor, "op_1", expected_version=lease.plan_version, receipt=receipt
        )
        assert updated.version == lease.plan_version + 1

        event = ResourceEvent.create(
            deployment="default",
            graphspace="DEFAULT",
            graph="hugegraph",
            uri="hugegraph://default/DEFAULT/hugegraph/schema",
            kind="updated",
            resource_version=updated.version + 1,
        )
        finished = await rt.plan_store.finish(
            lease,
            actor,
            expected_version=updated.version,
            outcome=PlanOutcome(status=PlanStatus.APPLIED, summary={"applied": 1}),
            events=(event,),
        )
        assert finished.status == PlanStatus.APPLIED
        assert len(rt.event_bus.recent_events()) == 1

    asyncio.run(scenario())


class _FakePostgresConn:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        q = " ".join(query.split())
        if q.startswith("INSERT INTO write_plans"):
            (
                plan_id,
                tool_name,
                owner_issuer,
                owner_tenant,
                owner_subject,
                graphspace,
                graph,
                payload_json,
                payload_digest,
                status,
                expires_at,
                summary_json,
            ) = params
            self.state["plans"][plan_id] = {
                "plan_id": plan_id,
                "tool_name": tool_name,
                "owner_issuer": owner_issuer,
                "owner_tenant": owner_tenant,
                "owner_subject": owner_subject,
                "graphspace": graphspace,
                "graph": graph,
                "payload_json": json.loads(payload_json),
                "payload_digest": payload_digest,
                "status": status,
                "version": 1,
                "fence": 0,
                "lease_holder": None,
                "lease_expires_at": None,
                "expires_at": float(expires_at),
                "summary_json": json.loads(summary_json),
            }
        elif q.startswith("INSERT INTO plan_operations"):
            plan_id, operation_id, ordinal, kind, target_json, status = params
            self.state["ops"].append(
                {
                    "plan_id": plan_id,
                    "operation_id": operation_id,
                    "ordinal": ordinal,
                    "kind": kind,
                    "target_json": json.loads(target_json),
                    "status": status,
                    "attempt": 0,
                    "reconciled": False,
                    "apply_status": None,
                    "receipt_json": None,
                }
            )
        elif q.startswith("UPDATE plan_operations"):
            apply_status, receipt_json, plan_id, operation_id = params
            for op in self.state["ops"]:
                if op["plan_id"] == plan_id and op["operation_id"] == operation_id:
                    op["apply_status"] = apply_status
                    if op["receipt_json"] is None:
                        op["receipt_json"] = json.loads(receipt_json)
        elif q.startswith("INSERT INTO event_outbox"):
            event_id, deployment, graphspace, graph, uri, kind, resource_version = params
            if not any(e["event_id"] == event_id for e in self.state["outbox"]):
                self.state["outbox"].append(
                    {
                        "event_id": event_id,
                        "deployment": deployment,
                        "graphspace": graphspace,
                        "graph": graph,
                        "uri": uri,
                        "kind": kind,
                        "resource_version": resource_version,
                    }
                )

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        q = " ".join(query.split())
        if q == "SELECT 1 AS ok":
            return {"ok": 1}
        if q.startswith("SELECT plan_id, tool_name"):
            plan_id, issuer, tenant, subject = params
            row = self.state["plans"].get(plan_id)
            if (
                row
                and row["owner_issuer"] == issuer
                and row["owner_tenant"] == tenant
                and row["owner_subject"] == subject
            ):
                return dict(row)
            return None
        if q.startswith("UPDATE write_plans SET status = 'EXECUTING'"):
            holder, ttl_s, plan_id, issuer, tenant, subject = params
            row = self.state["plans"].get(plan_id)
            if (
                row
                and row["owner_issuer"] == issuer
                and row["owner_tenant"] == tenant
                and row["owner_subject"] == subject
                and row["status"] == "ISSUED"
                and row["expires_at"] > time.time()
            ):
                row["status"] = "EXECUTING"
                row["lease_holder"] = holder
                row["fence"] += 1
                row["lease_expires_at"] = time.time() + ttl_s
                row["version"] += 1
                return {
                    "fence": row["fence"],
                    "version": row["version"],
                    "lease_expires_at": row["lease_expires_at"],
                }
            return None
        if q.startswith("UPDATE write_plans SET version = version + 1"):
            plan_id, issuer, tenant, subject, expected_version, fence = params
            row = self.state["plans"].get(plan_id)
            if (
                row
                and row["owner_issuer"] == issuer
                and row["owner_tenant"] == tenant
                and row["owner_subject"] == subject
                and row["status"] == "EXECUTING"
                and row["version"] == expected_version
                and row["fence"] == fence
                and (row["lease_expires_at"] or 0) > time.time()
            ):
                row["version"] += 1
                return {"version": row["version"]}
            return None
        if q.startswith("UPDATE write_plans SET status = 'UNKNOWN'"):
            reason, plan_id, issuer, tenant, subject, expected_version = params
            row = self.state["plans"].get(plan_id)
            if (
                row
                and row["owner_issuer"] == issuer
                and row["owner_tenant"] == tenant
                and row["owner_subject"] == subject
                and row["status"] in {"ISSUED", "EXECUTING", "PARTIAL", "UNKNOWN"}
                and row["version"] == expected_version
            ):
                row["status"] = "UNKNOWN"
                row["summary_json"]["uncertain_reason"] = reason
                row["version"] += 1
                row["lease_holder"] = None
                return {"version": row["version"]}
            return None
        if q.startswith("UPDATE write_plans SET status = %s"):
            status, summary_json, plan_id, issuer, tenant, subject, holder, expected_version, fence = params
            row = self.state["plans"].get(plan_id)
            if (
                row
                and row["owner_issuer"] == issuer
                and row["owner_tenant"] == tenant
                and row["owner_subject"] == subject
                and row["status"] == "EXECUTING"
                and row["lease_holder"] == holder
                and (row["lease_expires_at"] or 0) > time.time()
                and row["version"] == expected_version
                and row["fence"] == fence
            ):
                row["status"] = status
                row["summary_json"] = json.loads(summary_json)
                row["version"] += 1
                row["lease_holder"] = None
                return {"version": row["version"]}
            return None
        return None

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        plan_id = params[0]
        return [dict(op) for op in self.state["ops"] if op["plan_id"] == plan_id]


class _FakePostgresPool:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {"plans": {}, "ops": [], "outbox": []}

    async def acquire(self) -> _FakePostgresConn:
        return _FakePostgresConn(self.state)

    async def release(self, conn: _FakePostgresConn, exc: BaseException | None = None) -> None:
        return None

    async def close(self) -> None:
        return None


def test_postgres_plan_store_outbox_and_uncertain():
    pool = _FakePostgresPool()
    store = PostgresPlanStore("postgresql://mock", pool=pool)
    actor = Actor(issuer="bearer", tenant="t1", subject="user-1")
    plan = _sample_plan("wp_pg_1")
    plan_2 = _sample_plan("wp_pg_2")

    async def scenario():
        await store.prepare()
        await store.check_ready()
        created = await store.create(plan, actor)
        assert created.version == 1

        lease = await store.claim("wp_pg_1", actor, "pod-1", ttl_s=30)
        assert lease.fence == 1

        event = ResourceEvent.create(
            deployment="prod",
            graphspace="DEFAULT",
            graph="hugegraph",
            uri="hugegraph://prod/DEFAULT/hugegraph/schema",
            kind="updated",
            resource_version=lease.plan_version + 1,
        )
        finished = await store.finish(
            lease,
            actor,
            expected_version=lease.plan_version,
            outcome=PlanOutcome(status=PlanStatus.APPLIED, summary={"applied": 1}),
            events=(event,),
        )
        assert finished.status == PlanStatus.APPLIED
        assert len(pool.state["outbox"]) == 1

        # Terminal APPLIED plan cannot be transitioned to UNKNOWN
        with pytest.raises(LeaseConflictError):
            await store.mark_uncertain("wp_pg_1", actor, expected_version=finished.version, reason="too_late")

        # Executing plan can be transitioned to UNKNOWN on lease loss
        await store.create(plan_2, actor)
        lease_2 = await store.claim("wp_pg_2", actor, "pod-2", ttl_s=30)
        uncertain = await store.mark_uncertain(
            "wp_pg_2", actor, expected_version=lease_2.plan_version, reason="lease_expired"
        )
        assert uncertain.status == PlanStatus.UNKNOWN

    asyncio.run(scenario())


def test_runtime_drain_and_server_registrations(tmp_path: Path):
    rt = build_runtime(MCPConfig(state_dir=tmp_path))
    rt.ready = True

    async def scenario():
        ok, checks = await rt.check_ready()
        assert ok is True
        assert checks["plan_store"] == "ok"
        rt.begin_write()
        rt.end_write()
        assert await rt.drain_writes(timeout_s=1.0) is True
        ok_after, _ = await rt.check_ready()
        assert ok_after is False

    asyncio.run(scenario())

    # Verify FastMCP instance registered prompts and resource templates alongside tools
    prompts = asyncio.run(server.mcp.list_prompts())
    prompt_names = {p.name for p in prompts}
    assert {"explore_graph", "design_graph_schema", "review_write_plan", "investigate_write_status"} <= prompt_names

    templates = asyncio.run(server.mcp.list_resource_templates())
    template_uris = {t.uri_template for t in templates}
    assert "hugegraph://{deployment}/{graphspace}/{graph}/schema" in template_uris
    assert "plan://{plan_id}" in template_uris


def test_sync_plan_store_from_config_returns_postgres_bridge_and_fails_closed_without_dsn():
    from hugegraph_mcp.plan_store import PlanStoreUnavailableError, plan_store_from_config
    from hugegraph_mcp.stores.postgres import PostgresSyncPlanStore

    cfg = MCPConfig(
        plan_store_backend="postgres",
        plan_store_dsn="postgresql://mock",
        write_instance_count=3,
    )
    store = plan_store_from_config(cfg)
    assert isinstance(store, PostgresSyncPlanStore)

    unsafe_cfg = MCPConfig(
        plan_store_backend="sqlite",
        write_instance_count=3,
    )
    with pytest.raises(PlanStoreUnavailableError):
        plan_store_from_config(unsafe_cfg)
