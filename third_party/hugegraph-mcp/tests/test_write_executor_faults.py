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

"""Fault-injection coverage for durable confirmed-write execution."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from hugegraph_mcp.plan_store import PlanTransitionError, SQLitePlanStore
from hugegraph_mcp.reconciler import ReconcileReaderRegistry, WriteReconciler
from hugegraph_mcp.write_executor import WriteExecutor, WriteExecutorRegistry
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)


class InjectedCrashError(RuntimeError):
    """A deterministic process-boundary fault used by these tests."""


class FaultStore:
    """Delegate to SQLite while injecting one precisely placed failure."""

    def __init__(
        self,
        delegate: SQLitePlanStore,
        *,
        claim_plan: str | None = None,
        record_receipt: str | None = None,
    ):
        self.delegate = delegate
        self.claim_plan_fault = claim_plan
        self.record_receipt_fault = record_receipt

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def claim_plan(self, plan_id, **kwargs):
        if self.claim_plan_fault == "before":
            raise InjectedCrashError("before plan claim")
        result = self.delegate.claim_plan(plan_id, **kwargs)
        if self.claim_plan_fault == "after":
            raise InjectedCrashError("after plan claim")
        return result

    def record_receipt(self, receipt, **kwargs):
        if self.record_receipt_fault == "before":
            raise InjectedCrashError("before receipt persistence")
        self.delegate.record_receipt(receipt, **kwargs)
        if self.record_receipt_fault == "after":
            raise InjectedCrashError("after receipt persistence")


def _plan(
    *,
    operations: int = 1,
    kinds: tuple[str, ...] | None = None,
) -> WritePlan:
    operation_kinds = kinds or ("TEST_APPLY",) * operations
    return WritePlan(
        plan_id="wp-fault",
        tool_name="test",
        graph_target=GraphTarget("http://127.0.0.1:8080", "hugegraph", "DEFAULT"),
        principal="admin",
        operations=tuple(
            OperationPlan(
                operation_id=f"op-{index}",
                kind=operation_kinds[index],
                target={"id": f"v-{index}"},
                expected_state={"value": index},
                desired_state={"value": index + 1},
            )
            for index in range(operations)
        ),
        payload_digest="digest",
        schema_fingerprint=None,
        status=PlanStatus.ISSUED,
        created_at=100,
        expires_at=4_102_444_800,
    )


def _receipt_adapter(calls: list[str]) -> Callable:
    def apply(plan, operation, attempt):
        calls.append(operation.operation_id)
        return ApplyReceipt(
            plan_id=plan.plan_id,
            operation_id=operation.operation_id,
            status=ApplyStatus.APPLIED,
            observed_state=operation.desired_state,
            attempt=attempt,
            committed_at=150,
        )

    return apply


def _executor(store, adapter) -> WriteExecutor:
    registry = WriteExecutorRegistry()
    registry.register("TEST_APPLY", adapter)
    return WriteExecutor(store=store, registry=registry)


def _restarted_status(state_dir) -> dict:
    restarted = SQLitePlanStore(state_dir)
    return WriteExecutor(
        store=restarted,
        registry=WriteExecutorRegistry(),
    ).status("wp-fault")["data"]


def _reconcile_as(state_dir, observed_state: dict) -> dict:
    store = SQLitePlanStore(state_dir)
    _expire_lease(store, "wp-fault")
    readers = ReconcileReaderRegistry()
    readers.register("TEST_APPLY", lambda _plan, _operation: observed_state)
    return WriteReconciler(store=store, readers=readers).reconcile("wp-fault")


def _expire_lease(store: SQLitePlanStore, plan_id: str) -> None:
    import sqlite3

    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE write_plans SET lease_expires_at = 0 WHERE plan_id = ?",
            (plan_id,),
        )


def test_crash_before_claim_leaves_plan_issued_and_adapter_unstarted(tmp_path):
    durable = SQLitePlanStore(tmp_path)
    durable.save_plan(_plan())
    calls = []

    with pytest.raises(InjectedCrashError):
        _executor(
            FaultStore(durable, claim_plan="before"),
            _receipt_adapter(calls),
        ).confirm("wp-fault")

    assert calls == []
    status = _restarted_status(tmp_path)
    assert status["status"] == "ISSUED"
    assert status["operations"][0]["status"] == "ISSUED"

    retry_calls = []
    retried = _executor(
        SQLitePlanStore(tmp_path),
        _receipt_adapter(retry_calls),
    ).confirm("wp-fault")
    assert retried["data"]["status"] == "APPLIED"
    assert retry_calls == ["op-0"]


def test_crash_after_executing_before_adapter_recovers_as_unknown(tmp_path):
    durable = SQLitePlanStore(tmp_path)
    durable.save_plan(_plan())
    calls = []

    with pytest.raises(InjectedCrashError):
        _executor(
            FaultStore(durable, claim_plan="after"),
            _receipt_adapter(calls),
        ).confirm("wp-fault")

    assert calls == []
    status = _restarted_status(tmp_path)
    assert status["status"] == "EXECUTING"
    assert status["reconciliation_required"] is False
    assert status["operations"][0]["status"] == "ISSUED"

    _expire_lease(SQLitePlanStore(tmp_path), "wp-fault")
    reconciled = WriteReconciler(
        store=SQLitePlanStore(tmp_path),
        readers=ReconcileReaderRegistry(),
    ).reconcile("wp-fault")
    assert reconciled["data"]["status"] == "RETRYABLE_NOT_APPLIED"
    retry_calls = []
    resumed = _executor(
        SQLitePlanStore(tmp_path),
        _receipt_adapter(retry_calls),
    ).resume("wp-fault")
    assert resumed["data"]["status"] == "APPLIED"
    assert retry_calls == ["op-0"]


def test_adapter_response_loss_persists_unknown_across_restart(tmp_path):
    durable = SQLitePlanStore(tmp_path)
    durable.save_plan(_plan())

    def response_lost(_plan, _operation, _attempt):
        raise InjectedCrashError("request sent; response lost")

    result = _executor(durable, response_lost).confirm("wp-fault")

    assert result["ok"] is False
    assert result["error"]["type"] == "WRITE_OUTCOME_UNKNOWN"
    assert result["error"]["details"]["status"] == "UNKNOWN"
    status = _restarted_status(tmp_path)
    assert status["status"] == "UNKNOWN"
    assert status["operations"][0]["status"] == "UNKNOWN"
    assert status["operations"][0]["receipt"]["reconciliation_required"] is True

    reconciled = _reconcile_as(tmp_path, {"value": 0})
    assert reconciled["data"]["status"] == "UNKNOWN"
    assert reconciled["data"]["operations"][0]["receipt"]["reason_code"] == ("IN_FLIGHT_COMMIT_NOT_EXCLUDED")
    with pytest.raises(PlanTransitionError):
        _executor(
            SQLitePlanStore(tmp_path),
            _receipt_adapter([]),
        ).resume("wp-fault")


def test_crash_before_receipt_persistence_recovers_executing_as_unknown(tmp_path):
    durable = SQLitePlanStore(tmp_path)
    durable.save_plan(_plan())
    calls = []

    with pytest.raises(InjectedCrashError):
        _executor(
            FaultStore(durable, record_receipt="before"),
            _receipt_adapter(calls),
        ).confirm("wp-fault")

    assert calls == ["op-0"]
    status = _restarted_status(tmp_path)
    assert status["status"] == "EXECUTING"
    assert status["reconciliation_required"] is False
    assert status["operations"][0]["status"] == "EXECUTING"
    assert status["operations"][0]["receipt"] is None

    reconciled = _reconcile_as(tmp_path, {"value": 1})
    assert reconciled["data"]["status"] == "APPLIED"


def test_crash_after_receipt_before_response_recovers_applied(tmp_path):
    durable = SQLitePlanStore(tmp_path)
    durable.save_plan(_plan())
    calls = []

    with pytest.raises(InjectedCrashError):
        _executor(
            FaultStore(durable, record_receipt="after"),
            _receipt_adapter(calls),
        ).confirm("wp-fault")

    assert calls == ["op-0"]
    status = _restarted_status(tmp_path)
    assert status["status"] == "APPLIED"
    assert status["operations"][0]["status"] == "APPLIED"


def test_resume_requires_reconcile_and_replays_only_proven_not_applied(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(
        _plan(
            operations=2,
            kinds=("ALREADY_FINISHED_WITHOUT_ADAPTER", "TEST_APPLY"),
        )
    )
    store.claim_plan("wp-fault")
    first_attempt = store.claim_operation("wp-fault", "op-0")
    store.record_receipt(
        ApplyReceipt(
            plan_id="wp-fault",
            operation_id="op-0",
            status=ApplyStatus.APPLIED,
            observed_state={"value": 1},
            attempt=first_attempt,
            committed_at=150,
        )
    )
    store.claim_operation("wp-fault", "op-1")
    store.record_receipt(
        ApplyReceipt(
            plan_id="wp-fault",
            operation_id="op-1",
            status=ApplyStatus.UNKNOWN,
            attempt=1,
            reconciliation_required=True,
        )
    )
    calls = []
    executor = _executor(store, _receipt_adapter(calls))

    with pytest.raises(PlanTransitionError):
        executor.resume("wp-fault")

    readers = ReconcileReaderRegistry()
    readers.register(
        "TEST_APPLY",
        lambda _plan, operation: dict(operation.expected_state),
    )
    reconciled = WriteReconciler(store=store, readers=readers).reconcile("wp-fault")
    assert reconciled["data"]["status"] == "PARTIAL"
    operation_statuses = {item["operation_id"]: item["status"] for item in reconciled["data"]["operations"]}
    assert operation_statuses == {
        "op-0": "APPLIED",
        "op-1": "UNKNOWN",
    }
    with pytest.raises(PlanTransitionError):
        executor.resume("wp-fault")
    assert calls == []


def test_reconcile_applied_claimed_operation_allows_only_unclaimed_later_work(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_plan(operations=2))
    store.claim_plan("wp-fault")
    store.claim_operation("wp-fault", "op-0")
    _expire_lease(store, "wp-fault")
    readers = ReconcileReaderRegistry()
    readers.register(
        "TEST_APPLY",
        lambda _plan, operation: dict(operation.desired_state),
    )

    reconciled = WriteReconciler(store=store, readers=readers).reconcile("wp-fault")

    statuses = {item["operation_id"]: item["status"] for item in reconciled["data"]["operations"]}
    assert statuses == {"op-0": "APPLIED", "op-1": "RETRYABLE_NOT_APPLIED"}
    calls = []
    resumed = _executor(store, _receipt_adapter(calls)).resume("wp-fault")
    assert resumed["data"]["status"] == "APPLIED"
    assert calls == ["op-1"]


def test_partial_resume_cannot_replace_an_existing_valid_lease(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store.save_plan(_plan(operations=2))
    store.claim_plan("wp-fault")
    store.claim_operation("wp-fault", "op-0")
    _expire_lease(store, "wp-fault")
    readers = ReconcileReaderRegistry()
    readers.register(
        "TEST_APPLY",
        lambda _plan, operation: dict(operation.desired_state),
    )
    result = WriteReconciler(store=store, readers=readers).reconcile("wp-fault")
    assert result["data"]["status"] == "PARTIAL"
    _, claimed = store.claim_plan(
        "wp-fault",
        owner_token="first-resumer",
        lease_seconds=60,
        resume=True,
    )
    assert claimed is True

    with pytest.raises(PlanTransitionError, match="exclusively leased"):
        _executor(store, _receipt_adapter([])).resume("wp-fault")

    record = store.get_plan_record("wp-fault")
    assert record is not None
    assert record["lease_owner"] == "first-resumer"
