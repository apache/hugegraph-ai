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

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest

from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.plan_store import PlanTransitionError, SQLitePlanStore
from hugegraph_mcp.reconciler import ReconcileReaderRegistry, WriteReconciler
from hugegraph_mcp.server import confirm_write_tool, get_write_status_tool
from hugegraph_mcp.write_executor import WriteExecutor, WriteExecutorRegistry
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)


def _plan() -> WritePlan:
    return WritePlan(
        plan_id="wp-confirm",
        tool_name="test",
        graph_target=GraphTarget("http://127.0.0.1:8080", "hugegraph", "DEFAULT"),
        principal="admin",
        operations=(
            OperationPlan(
                operation_id="op-confirm",
                kind="TEST_APPLY",
                target={"id": "v-1"},
                expected_state={"value": 1},
                desired_state={"value": 2},
            ),
        ),
        payload_digest="digest",
        schema_fingerprint=None,
        status=PlanStatus.ISSUED,
        created_at=100,
        expires_at=4_102_444_800,
    )


def test_repeated_confirmation_returns_persisted_status_without_second_attempt(
    tmp_path,
):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_plan())
    calls = []
    registry = WriteExecutorRegistry()

    def apply(plan, operation, attempt):
        calls.append((plan.plan_id, operation.operation_id, attempt))
        return ApplyReceipt(
            plan_id=plan.plan_id,
            operation_id=operation.operation_id,
            status=ApplyStatus.APPLIED,
            observed_state={"value": 2},
            attempt=attempt,
            committed_at=150,
        )

    registry.register("TEST_APPLY", apply)
    executor = WriteExecutor(store=store, registry=registry)

    first = executor.confirm("wp-confirm")
    second = executor.confirm("wp-confirm")

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["data"]["status"] == "APPLIED"
    assert second["data"]["status"] == "APPLIED"
    assert calls == [("wp-confirm", "op-confirm", 1)]


def test_concurrent_confirmation_has_one_adapter_attempt(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_plan())
    registry = WriteExecutorRegistry()
    calls = 0
    calls_lock = Lock()

    def apply(plan, operation, attempt):
        nonlocal calls
        with calls_lock:
            calls += 1
        return ApplyReceipt(
            plan_id=plan.plan_id,
            operation_id=operation.operation_id,
            status=ApplyStatus.APPLIED,
            attempt=attempt,
            committed_at=150,
        )

    registry.register("TEST_APPLY", apply)
    executor = WriteExecutor(store=store, registry=registry)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: executor.confirm("wp-confirm"), range(8)))

    assert calls == 1
    assert all(
        (result["data"]["status"] if result["ok"] else result["error"]["details"]["status"]) in {"APPLIED", "EXECUTING"}
        for result in results
    )
    assert executor.status("wp-confirm")["data"]["status"] == "APPLIED"


def test_expired_executor_is_fenced_from_overwriting_new_attempt(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_plan())
    entered = Barrier(2)
    release_old = Event()
    old_registry = WriteExecutorRegistry()

    def delayed_old(plan, operation, attempt):
        entered.wait()
        assert release_old.wait(timeout=5)
        return ApplyReceipt(
            plan_id=plan.plan_id,
            operation_id=operation.operation_id,
            status=ApplyStatus.CONFLICT,
            attempt=attempt,
        )

    old_registry.register("TEST_APPLY", delayed_old)
    old_executor = WriteExecutor(store=store, registry=old_registry)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old_result = pool.submit(old_executor.confirm, "wp-confirm")
        entered.wait()
        with sqlite3.connect(store.database_path) as connection:
            connection.execute("UPDATE write_plans SET lease_expires_at = 0 WHERE plan_id = 'wp-confirm'")

        readers = ReconcileReaderRegistry()
        readers.register(
            "TEST_APPLY",
            lambda _plan, _operation: {"value": 1},
        )
        reconciled = WriteReconciler(store=store, readers=readers).reconcile("wp-confirm")
        assert reconciled["data"]["status"] == "UNKNOWN"
        assert reconciled["data"]["operations"][0]["receipt"]["reason_code"] == ("IN_FLIGHT_COMMIT_NOT_EXCLUDED")
        with pytest.raises(PlanTransitionError):
            WriteExecutor(store=store, registry=WriteExecutorRegistry()).resume("wp-confirm")
        release_old.set()
        with pytest.raises(PlanTransitionError, match="stale or unfenced"):
            old_result.result()

    record = store.get_plan_record("wp-confirm")
    assert record is not None
    assert record["status"] == "UNKNOWN"
    assert record["operations"][0]["attempt"] == 1


def test_claiming_each_operation_renews_lease_and_blocks_reconcile(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_plan())
    owner = "executor-owner"
    store.claim_plan("wp-confirm", owner_token=owner, lease_seconds=10)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE write_plans SET lease_expires_at = strftime('%s','now') + 1 WHERE plan_id = 'wp-confirm'"
        )

    store.claim_operation(
        "wp-confirm",
        "op-confirm",
        owner_token=owner,
        attempt_token="attempt-one",
        lease_seconds=40,
    )

    record = store.get_plan_record("wp-confirm")
    assert record is not None
    assert record["lease_expires_at"] >= int(time.time()) + 39
    result = WriteReconciler(
        store=store,
        readers=ReconcileReaderRegistry(),
    ).reconcile("wp-confirm")
    assert result["error"]["details"]["reason_code"] == "EXECUTION_LEASE_ACTIVE"


def test_missing_adapter_does_not_claim_plan(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_plan())
    executor = WriteExecutor(store=store, registry=WriteExecutorRegistry())

    result = executor.confirm("wp-confirm")

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert store.get_plan("wp-confirm").status is PlanStatus.ISSUED


def test_status_preserves_active_executing_lease_and_redacts_payload(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_plan())
    store.claim_plan("wp-confirm")
    executor = WriteExecutor(store=store, registry=WriteExecutorRegistry())

    result = executor.status("wp-confirm")

    assert result["ok"] is True
    assert result["data"]["status"] == "EXECUTING"
    assert result["data"]["reconciliation_required"] is False
    assert "payload" not in result["data"]
    assert "payload" not in result["data"]["operations"][0]


def test_public_confirm_tool_routes_only_plan_id(monkeypatch):
    expected = envelope_ok({"plan_id": "wp-confirm", "status": "APPLIED"})
    calls = []

    def fake_confirm(plan_id):
        calls.append(plan_id)
        return expected

    monkeypatch.setattr("hugegraph_mcp.server.confirm_write", fake_confirm)

    result = confirm_write_tool(plan_id="wp-confirm")

    assert result["ok"] is True
    assert calls == ["wp-confirm"]


def test_public_status_tool_routes_only_plan_id(monkeypatch):
    expected = envelope_ok({"plan_id": "wp-confirm", "status": "UNKNOWN"})
    calls = []

    def fake_status(plan_id):
        calls.append(plan_id)
        return expected

    monkeypatch.setattr("hugegraph_mcp.server.get_write_status", fake_status)

    result = get_write_status_tool(plan_id="wp-confirm")

    assert result["ok"] is True
    assert calls == ["wp-confirm"]
