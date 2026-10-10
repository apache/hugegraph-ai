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

import pytest

from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.plan_store import PlanTransitionError, SQLitePlanStore
from hugegraph_mcp.reconciler import (
    ReconcileReaderRegistry,
    WriteReconciler,
    reconcile_operation_state,
)
from hugegraph_mcp.write_executor import WriteExecutor, WriteExecutorRegistry
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)


@pytest.mark.parametrize(
    ("kind", "expected", "desired", "observed", "status"),
    [
        (
            "CREATE_VERTEX",
            {"exists": False},
            {"exists": True},
            {"exists": True},
            ApplyStatus.APPLIED,
        ),
        (
            "CREATE_EDGE",
            {"exists": False},
            {"exists": True, "id": "e-1"},
            {"exists": False},
            ApplyStatus.RETRYABLE_NOT_APPLIED,
        ),
        (
            "CREATE_SCHEMA",
            {"exists": False},
            {"exists": True, "name": "person"},
            {"exists": True, "name": "other"},
            ApplyStatus.CONFLICT,
        ),
        (
            "DELETE_VERTEX",
            {"exists": True, "id": "v-1"},
            {"exists": False},
            {"exists": False},
            ApplyStatus.APPLIED,
        ),
        (
            "DELETE_EDGE",
            {"exists": True, "id": "e-1"},
            {"exists": False},
            {"exists": True, "id": "e-1"},
            ApplyStatus.RETRYABLE_NOT_APPLIED,
        ),
        (
            "REPLACE_PROPERTIES",
            {"properties": {"age": 20}},
            {"properties": {"age": 21}},
            {"properties": {"age": 21}},
            ApplyStatus.APPLIED,
        ),
        (
            "REPLACE_PROPERTIES",
            {"properties": {"age": 20}},
            {"properties": {"age": 21}},
            {"properties": {"age": 22}},
            ApplyStatus.CONFLICT,
        ),
    ],
)
def test_reconcile_operation_state(kind, expected, desired, observed, status):
    assert reconcile_operation_state(kind, expected, desired, observed) is status


def _unknown_plan() -> WritePlan:
    return WritePlan(
        plan_id="wp-reconcile",
        tool_name="test",
        graph_target=GraphTarget("http://127.0.0.1:8080", "hugegraph", "DEFAULT"),
        principal="admin",
        operations=(
            OperationPlan(
                operation_id="op-reconcile",
                kind="REPLACE_PROPERTIES",
                target={"id": "v-1"},
                expected_state={"properties": {"age": 20}},
                desired_state={"properties": {"age": 21}},
            ),
        ),
        payload_digest="digest",
        schema_fingerprint=None,
        status=PlanStatus.ISSUED,
        created_at=100,
        expires_at=4_102_444_800,
    )


def _crash_plan(store: SQLitePlanStore) -> None:
    store.save_plan(_unknown_plan())
    store.claim_plan("wp-reconcile")
    store.claim_operation("wp-reconcile", "op-reconcile")
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE write_plans SET lease_expires_at = 0 WHERE plan_id = 'wp-reconcile'")


def test_reconcile_is_read_only_and_idempotent(tmp_path):
    store = SQLitePlanStore(tmp_path)
    _crash_plan(store)
    reads = []
    readers = ReconcileReaderRegistry()

    def read(plan, operation):
        reads.append((plan.plan_id, operation.operation_id))
        return {"properties": {"age": 21}}

    readers.register("REPLACE_PROPERTIES", read)
    reconciler = WriteReconciler(store=store, readers=readers)

    first = reconciler.reconcile("wp-reconcile")
    second = reconciler.reconcile("wp-reconcile")

    assert first["data"]["status"] == "APPLIED"
    assert second["data"]["status"] == "APPLIED"
    assert reads == [("wp-reconcile", "op-reconcile")]


def test_reconcile_refuses_to_take_over_an_active_execution_lease(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_unknown_plan())
    store.claim_plan("wp-reconcile")
    store.claim_operation("wp-reconcile", "op-reconcile")
    reads = []
    readers = ReconcileReaderRegistry()
    readers.register("REPLACE_PROPERTIES", lambda *_: reads.append(True) or {})

    result = WriteReconciler(store=store, readers=readers).reconcile("wp-reconcile")

    assert result["ok"] is False
    assert result["error"]["type"] == "WRITE_CONFLICT"
    assert result["error"]["details"]["reason_code"] == "EXECUTION_LEASE_ACTIVE"
    assert reads == []
    assert store.get_plan_record("wp-reconcile")["status"] == "EXECUTING"


def test_reconcile_expected_state_cannot_exclude_late_inflight_commit(tmp_path):
    store = SQLitePlanStore(tmp_path)
    _crash_plan(store)
    readers = ReconcileReaderRegistry()
    readers.register(
        "REPLACE_PROPERTIES",
        lambda _plan, _operation: {"properties": {"age": 20}},
    )
    reconciler = WriteReconciler(store=store, readers=readers)

    result = reconciler.reconcile("wp-reconcile")

    assert result["data"]["status"] == "UNKNOWN"
    receipt = result["data"]["operations"][0]["receipt"]
    assert receipt["reason_code"] == "IN_FLIGHT_COMMIT_NOT_EXCLUDED"
    assert receipt["reconciliation_required"] is True


def test_resume_rejects_claimed_unknown_even_when_expected_state_is_observed(tmp_path):
    store = SQLitePlanStore(tmp_path)
    _crash_plan(store)
    executor = WriteExecutor(store=store, registry=WriteExecutorRegistry())

    with pytest.raises(PlanTransitionError):
        executor.resume("wp-reconcile")

    readers = ReconcileReaderRegistry()
    readers.register(
        "REPLACE_PROPERTIES",
        lambda _plan, _operation: {"properties": {"age": 20}},
    )
    WriteReconciler(store=store, readers=readers).reconcile("wp-reconcile")
    executor.registry.register(
        "REPLACE_PROPERTIES",
        lambda plan, operation, attempt: ApplyReceipt(
            plan_id=plan.plan_id,
            operation_id=operation.operation_id,
            status=ApplyStatus.APPLIED,
            attempt=attempt,
            committed_at=200,
        ),
    )

    with pytest.raises(PlanTransitionError):
        executor.resume("wp-reconcile")


def test_public_reconcile_tool_routes_only_plan_id(monkeypatch):
    from hugegraph_mcp.server import reconcile_write_tool

    expected = envelope_ok({"plan_id": "wp-reconcile", "status": "APPLIED"})
    calls = []

    def fake_reconcile(plan_id):
        calls.append(plan_id)
        return expected

    monkeypatch.setattr("hugegraph_mcp.server.reconcile_write", fake_reconcile)

    result = reconcile_write_tool(plan_id="wp-reconcile")

    assert result["ok"] is True
    assert calls == ["wp-reconcile"]
