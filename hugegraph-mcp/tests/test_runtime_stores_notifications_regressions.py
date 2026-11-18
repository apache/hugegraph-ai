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
import gc
import json
import time
import weakref
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from mcp import types as mcp_types

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.notifications import SubscriptionManager
from hugegraph_mcp.plan_store import PlanStoreUnavailableError, SQLitePlanStore
from hugegraph_mcp.resource_uri import InvalidResourceURIError
from hugegraph_mcp.resources import read_schema_resource, register_resources
from hugegraph_mcp.runtime import build_runtime
from hugegraph_mcp.stores.base import (
    Actor,
    LeaseConflictError,
    SyncToAsyncPlanStoreAdapter,
)
from hugegraph_mcp.write_plan import (
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)


def _sample_plan(plan_id: str = "wp_test_1") -> WritePlan:
    now = int(time.time())
    return WritePlan(
        plan_id=plan_id,
        tool_name="apply_schema_tool",
        graph_target=GraphTarget(
            graph_url="http://127.0.0.1:8080",
            graph_name="hugegraph",
            graphspace="DEFAULT",
        ),
        principal="local",
        operations=(
            OperationPlan(
                operation_id="op_1",
                kind="CREATE_PROPERTY_KEY",
                target={"name": "age"},
                expected_state={"exists": False},
                desired_state={"exists": True},
            ),
        ),
        payload_digest="digest-1",
        schema_fingerprint="fp-1",
        status=PlanStatus.ISSUED,
        created_at=now,
        expires_at=now + 600,
    )


def test_build_runtime_postgres_without_dsn_fails_closed(tmp_path: Path) -> None:
    cfg = MCPConfig(
        plan_store_backend="postgres",
        plan_store_dsn=None,
        state_dir=tmp_path,
    )
    with pytest.raises(PlanStoreUnavailableError):
        build_runtime(cfg)


def test_build_runtime_unsupported_backend_fails_closed(tmp_path: Path) -> None:
    cfg = MCPConfig(
        plan_store_backend="unknown",
        state_dir=tmp_path,
    )
    with pytest.raises(PlanStoreUnavailableError):
        build_runtime(cfg)


def test_sqlite_async_lease_renewal_persists_and_enforces_fencing(tmp_path: Path) -> None:
    async def _run() -> None:
        sync_store = SQLitePlanStore(tmp_path)
        adapter = SyncToAsyncPlanStoreAdapter(sync_store)
        actor = Actor(issuer="local-stdio", tenant="default", subject="op")
        plan = _sample_plan("wp_renew_1")
        await adapter.create(plan, actor)
        lease = await adapter.claim(plan.plan_id, actor, "worker-1", ttl_s=10)

        renewed = await adapter.renew(lease, actor, ttl_s=60)
        assert renewed.expires_at >= int(time.time()) + 50
        record = sync_store.get_plan_record(plan.plan_id)
        assert record is not None
        assert record["lease_expires_at"] == int(renewed.expires_at)

        with pytest.raises(LeaseConflictError):
            await adapter.renew(replace(renewed, fence=renewed.fence + 1), actor, ttl_s=60)

        with pytest.raises(LeaseConflictError):
            await adapter.renew(replace(renewed, holder="other-worker:deadbeef"), actor, ttl_s=60)

        with pytest.raises(LeaseConflictError):
            await adapter.renew(replace(renewed, expires_at=time.time() - 5), actor, ttl_s=60)

        with pytest.raises(ValueError):
            await adapter.renew(renewed, actor, ttl_s=0)

    asyncio.run(_run())


def test_subscription_manager_does_not_leak_session_strong_ref() -> None:
    class _DummySession:
        async def send_resource_updated(self, uri: Any) -> None:
            return None

    mgr = SubscriptionManager()
    session = _DummySession()
    weak_sess = weakref.ref(session)
    uri = "hugegraph://default/DEFAULT/hugegraph/schema"
    mgr.subscribe_session("sess-1", uri, session)
    assert uri in mgr.subscribed_uris("sess-1")

    del session
    gc.collect()
    assert weak_sess() is None
    assert mgr.subscribed_uris("sess-1") == frozenset()


def test_plan_uri_subscription_rejected() -> None:
    handlers: dict[str, Any] = {}

    class _FakeLowLevel:
        def add_request_handler(self, name: str, params_cls: Any, handler: Any) -> None:
            handlers[name] = handler

    class _FakeMCP:
        _mcp_server = _FakeLowLevel()

        def resource(self, *args: Any, **kwargs: Any):
            return lambda fn: fn

    register_resources(_FakeMCP())
    assert "resources/subscribe" in handlers

    class _FakeCtx:
        session = object()

    with pytest.raises(InvalidResourceURIError):
        asyncio.run(
            handlers["resources/subscribe"](
                _FakeCtx(),
                mcp_types.SubscribeRequestParams(uri="plan://wp_123"),  # type: ignore[arg-type]
            )
        )


def test_read_schema_resource_skips_duplicate_truncation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import hugegraph_mcp.resources as resources_mod

    cfg = MCPConfig(state_dir=tmp_path)
    rt = build_runtime(cfg)

    monkeypatch.setattr(
        resources_mod,
        "inspect_schema",
        lambda **kwargs: {
            "ok": True,
            "data": {
                "raw_schema": {"vertexlabels": []},
                "schema_fingerprint": "fp-precomputed",
                "truncated": False,
                "truncation_reason": None,
            },
        },
    )

    def _fail_bound(*args: Any, **kwargs: Any):
        raise AssertionError("bound_schema_payload should not be called a second time")

    monkeypatch.setattr(resources_mod, "bound_schema_payload", _fail_bound)

    raw_json = asyncio.run(read_schema_resource("default", "DEFAULT", "hugegraph", runtime=rt))
    payload = json.loads(raw_json)
    assert payload["schema_fingerprint"] == "fp-precomputed"
    assert payload["truncated"] is False
