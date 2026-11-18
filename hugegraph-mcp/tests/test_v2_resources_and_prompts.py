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

import pytest

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.events import ResourceEvent
from hugegraph_mcp.notifications import SubscriptionManager
from hugegraph_mcp.prompts import (
    render_design_graph_schema_prompt,
    render_explore_graph_prompt,
    render_investigate_write_status_prompt,
    render_review_write_plan_prompt,
)
from hugegraph_mcp.resource_uri import (
    GraphResourceURI,
    InvalidResourceURIError,
    PlanResourceURI,
    build_graph_resource_uri,
    build_plan_resource_uri,
    parse_resource_uri,
)
from hugegraph_mcp.resources import (
    compute_schema_fingerprint,
    read_embeddings_vid_resource,
    read_plan_resource,
    read_schema_resource,
    read_summary_resource,
)
from hugegraph_mcp.runtime import build_runtime
from hugegraph_mcp.stores.base import Actor
from hugegraph_mcp.write_plan import GraphTarget, OperationPlan, PlanStatus, WritePlan


def _make_plan(plan_id: str = "wp_test_1") -> WritePlan:
    now = int(time.time())
    return WritePlan(
        plan_id=plan_id,
        tool_name="manage_schema_tool",
        graph_target=GraphTarget(graph_url="http://127.0.0.1:8080", graph_name="hugegraph", graphspace="DEFAULT"),
        principal="default:alice",
        created_at=now,
        expires_at=now + 300,
        status=PlanStatus.ISSUED,
        schema_fingerprint="fp_1",
        operations=(
            OperationPlan(
                operation_id="op_1",
                kind="property_key_create",
                target={"name": "age"},
                expected_state={},
                desired_state={"data_type": "INT"},
            ),
        ),
        payload_digest="digest_1",
    )


def test_resource_uri_round_trip_and_rejection():
    schema_uri = build_graph_resource_uri("prod", "DEFAULT", "hugegraph", "schema")
    assert schema_uri == "hugegraph://prod/DEFAULT/hugegraph/schema"
    assert parse_resource_uri(schema_uri) == GraphResourceURI(
        deployment="prod",
        graphspace="DEFAULT",
        graph="hugegraph",
        kind="schema",
    )

    emb_uri = build_graph_resource_uri("prod", "DEFAULT", "hugegraph", "embeddings_vid")
    assert emb_uri == "hugegraph://prod/DEFAULT/hugegraph/embeddings/vid"
    assert parse_resource_uri(emb_uri) == GraphResourceURI(
        deployment="prod",
        graphspace="DEFAULT",
        graph="hugegraph",
        kind="embeddings_vid",
    )

    plan_uri = build_plan_resource_uri("wp_123")
    assert plan_uri == "plan://wp_123"
    assert parse_resource_uri(plan_uri) == PlanResourceURI(plan_id="wp_123")

    for bad in (
        "",
        "http://example.com/schema",
        "hugegraph://prod/DEFAULT/hugegraph/schema?x=1",
        "hugegraph://prod/DEFAULT/hugegraph/schema#frag",
        "hugegraph://prod/../hugegraph/schema",
        "hugegraph://prod/%252e%252e/hugegraph/schema",
        "hugegraph://prod/DEFAULT//schema",
        "hugegraph://prod/DEFAULT/hugegraph/unknown",
        "plan://wp_123/extra",
        "plan://wp_123/",
        "plan://wp_123?",
        "hugegraph://prod/DEFAULT/hugegraph/schema\t",
        "plan://..",
    ):
        with pytest.raises(InvalidResourceURIError):
            parse_resource_uri(bad)


def test_schema_resource_cache_and_invalidation(monkeypatch, tmp_path: Path):
    cfg = MCPConfig(state_dir=tmp_path, deployment_id="local", graphspace="DEFAULT", graph="hugegraph")
    rt = build_runtime(cfg)

    calls = {"count": 0}

    def fake_inspect_schema(include_raw_schema: bool = True):
        calls["count"] += 1
        return {
            "ok": True,
            "data": {
                "property_keys": [{"name": "name", "data_type": "TEXT"}],
                "call_count": calls["count"],
            },
        }

    monkeypatch.setattr("hugegraph_mcp.resources.inspect_schema", fake_inspect_schema)

    first = json.loads(asyncio.run(read_schema_resource("local", "DEFAULT", "hugegraph", runtime=rt)))
    second = json.loads(asyncio.run(read_schema_resource("local", "DEFAULT", "hugegraph", runtime=rt)))
    assert calls["count"] == 1
    assert first["schema_fingerprint"] == compute_schema_fingerprint(first["schema"])
    assert second["schema_fingerprint"] == first["schema_fingerprint"]

    rt.resource_cache.invalidate_graph("local", "DEFAULT", "hugegraph")
    third = json.loads(asyncio.run(read_schema_resource("local", "DEFAULT", "hugegraph", runtime=rt)))
    assert calls["count"] == 2
    assert third["schema"]["call_count"] == 2


def test_summary_and_embeddings_resources(monkeypatch, tmp_path: Path):
    cfg = MCPConfig(state_dir=tmp_path, deployment_id="local", allow_ai=False)
    rt = build_runtime(cfg)

    monkeypatch.setattr(
        "hugegraph_mcp.resources.inspect_graph",
        lambda include_raw_schema=False: {
            "ok": False,
            "error": {"message": "HugeGraph unreachable"},
        },
    )
    summary = json.loads(asyncio.run(read_summary_resource("local", "DEFAULT", "hugegraph", runtime=rt)))
    assert summary["status"] == "degraded"

    emb = json.loads(asyncio.run(read_embeddings_vid_resource("local", "DEFAULT", "hugegraph", runtime=rt)))
    assert emb["status"] == "disabled"
    assert emb["ai_url"] is None


def test_plan_resource_actor_isolation(tmp_path: Path):
    cfg = MCPConfig(state_dir=tmp_path)
    rt = build_runtime(cfg)
    alice = Actor(issuer="bearer", tenant="t1", subject="alice")
    bob = Actor(issuer="bearer", tenant="t1", subject="bob")

    plan = _make_plan("wp_secret_1")
    asyncio.run(rt.plan_store.create(plan, alice))

    alice_view = json.loads(asyncio.run(read_plan_resource("wp_secret_1", runtime=rt, actor=alice)))
    assert alice_view["plan_id"] == "wp_secret_1"
    assert alice_view["status"] == "ISSUED"

    with pytest.raises(ValueError, match="not found"):
        asyncio.run(read_plan_resource("wp_secret_1", runtime=rt, actor=bob))


def test_prompts_validation_and_rendering():
    explore = render_explore_graph_prompt("Find top 5 neighbors", depth=2)
    assert "hugegraph://default/DEFAULT/hugegraph/schema" in explore
    assert "max hop depth=2" in explore

    with pytest.raises(ValueError):
        render_explore_graph_prompt("bad depth", depth=5)
    with pytest.raises(ValueError):
        render_explore_graph_prompt("   ")

    design = render_design_graph_schema_prompt("Add person vertex", constraints="name is primary key")
    assert "Add person vertex" in design
    assert "name is primary key" in design

    review = render_review_write_plan_prompt("wp_123")
    assert "plan://wp_123" in review
    assert "NEVER call `confirm_write_tool` automatically" in review

    investigate = render_investigate_write_status_prompt("wp_123")
    assert "reconcile_write_tool" in investigate


def test_subscription_manager_dedup_and_delivery():
    mgr = SubscriptionManager()
    delivered_a: list[str] = []
    delivered_b: list[str] = []

    async def notify_a(uri: str) -> None:
        delivered_a.append(uri)

    async def notify_b(uri: str) -> None:
        delivered_b.append(uri)

    uri = "hugegraph://default/DEFAULT/hugegraph/schema"
    mgr.subscribe("sess_a", uri, notify_a)
    mgr.subscribe("sess_b", "hugegraph://default/DEFAULT/hugegraph/summary", notify_b)

    evt1 = ResourceEvent.create(
        deployment="default",
        graphspace="DEFAULT",
        graph="hugegraph",
        uri=uri,
        kind="updated",
        resource_version=10,
    )
    evt_dup = ResourceEvent.create(
        deployment="default",
        graphspace="DEFAULT",
        graph="hugegraph",
        uri=uri,
        kind="updated",
        resource_version=10,
    )
    evt2 = ResourceEvent.create(
        deployment="default",
        graphspace="DEFAULT",
        graph="hugegraph",
        uri=uri,
        kind="updated",
        resource_version=11,
    )

    assert asyncio.run(mgr.dispatch(evt1)) == 1
    assert asyncio.run(mgr.dispatch(evt_dup)) == 0
    assert asyncio.run(mgr.dispatch(evt2)) == 1
    assert delivered_a == [uri, uri]
    assert delivered_b == []

    mgr.unsubscribe("sess_a", uri)
    assert mgr.subscribed_uris("sess_a") == frozenset()
