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

"""Read-only reconciliation for ambiguous persisted write outcomes."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from hugegraph_mcp.envelope import ErrorType, envelope_err
from hugegraph_mcp.plan_store import (
    PlanStore,
    PlanTransitionError,
    plan_store_from_config,
)
from hugegraph_mcp.write_executor import WriteExecutor, WriteExecutorRegistry
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    OperationPlan,
    PlanStatus,
    WritePlan,
)

ReconcileReader = Callable[[WritePlan, OperationPlan], Mapping[str, Any]]


class ReconcileReaderRegistry:
    def __init__(self) -> None:
        self._readers: dict[str, ReconcileReader] = {}

    def register(self, kind: str, reader: ReconcileReader) -> None:
        if not kind:
            raise ValueError("reader kind must be non-empty")
        self._readers[kind] = reader

    def reader_for(self, kind: str) -> ReconcileReader | None:
        return self._readers.get(kind)


def reconcile_operation_state(
    kind: str,
    expected_state: Mapping[str, Any],
    desired_state: Mapping[str, Any],
    observed_state: Mapping[str, Any],
) -> ApplyStatus:
    """Classify observed state without performing any write."""

    observed = dict(observed_state)
    if observed == dict(desired_state):
        return ApplyStatus.APPLIED
    if observed == dict(expected_state):
        return ApplyStatus.RETRYABLE_NOT_APPLIED
    if kind.startswith("DELETE_") and observed.get("exists") is False:
        return ApplyStatus.APPLIED
    return ApplyStatus.CONFLICT


class WriteReconciler:
    def __init__(self, *, store: PlanStore, readers: ReconcileReaderRegistry):
        self.store = store
        self.readers = readers

    def reconcile(self, plan_id: str) -> dict:
        record = self.store.get_plan_record(plan_id)
        if record is None:
            return envelope_err(
                ErrorType.NOT_FOUND,
                "No persisted write plan matches this plan_id.",
                retryable=False,
            )
        if record["tool_name"] == "legacy":
            return envelope_err(
                ErrorType.FEATURE_DISABLED,
                "Legacy confirmation state cannot be safely reconciled.",
                retryable=False,
                details={"reason_code": "LEGACY_PLAN_NOT_RECONCILABLE"},
            )
        try:
            plan = self.store.begin_reconcile(plan_id)
        except PlanTransitionError as exc:
            return envelope_err(
                ErrorType.WRITE_CONFLICT,
                "The write plan still has an active execution lease.",
                retryable=False,
                details={"reason_code": "EXECUTION_LEASE_ACTIVE", "reason": str(exc)},
            )
        if plan.status not in {
            PlanStatus.UNKNOWN,
            PlanStatus.LEGACY_UNKNOWN,
            PlanStatus.PARTIAL,
        }:
            return self._status(plan_id)

        record = self.store.get_plan_record(plan_id)
        assert record is not None
        operation_records = {item["operation_id"]: item for item in record["operations"]}
        unresolved = {
            PlanStatus.EXECUTING.value,
            PlanStatus.UNKNOWN.value,
            PlanStatus.LEGACY_UNKNOWN.value,
        }
        for operation in plan.operations:
            operation_record = operation_records[operation.operation_id]
            if operation_record["status"] == PlanStatus.ISSUED.value:
                self.store.record_reconciliation_receipt(
                    ApplyReceipt(
                        plan_id=plan_id,
                        operation_id=operation.operation_id,
                        status=ApplyStatus.RETRYABLE_NOT_APPLIED,
                        reason_code="RECONCILED_OPERATION_NOT_CLAIMED",
                        attempt=operation_record["attempt"],
                        reconciliation_required=False,
                    )
                )
                continue
            if operation_record["status"] not in unresolved:
                continue
            reader = self.readers.reader_for(operation.kind)
            if reader is None:
                return envelope_err(
                    ErrorType.FEATURE_DISABLED,
                    "The write plan requires an unavailable reconciliation reader.",
                    retryable=False,
                    details={"missing_operation_kind": operation.kind},
                )
            observed = reader(plan, operation)
            status = reconcile_operation_state(
                operation.kind,
                operation.expected_state,
                operation.desired_state,
                observed,
            )
            reason_code = "RECONCILED_CURRENT_STATE"
            reconciliation_required = False
            if status is ApplyStatus.RETRYABLE_NOT_APPLIED and operation_record["attempt"] > 0:
                # A backend read cannot prove that an already-dispatched request
                # will not commit later. Only never-claimed operations are safe
                # to authorize for replay.
                status = ApplyStatus.UNKNOWN
                reason_code = "IN_FLIGHT_COMMIT_NOT_EXCLUDED"
                reconciliation_required = True
            self.store.record_reconciliation_receipt(
                ApplyReceipt(
                    plan_id=plan_id,
                    operation_id=operation.operation_id,
                    status=status,
                    observed_state=observed,
                    reason_code=reason_code,
                    attempt=operation_record["attempt"],
                    reconciliation_required=reconciliation_required,
                    committed_at=(int(time.time()) if status is ApplyStatus.APPLIED else None),
                )
            )
        return self._status(plan_id)

    def _status(self, plan_id: str) -> dict:
        return WriteExecutor(
            store=self.store,
            registry=WriteExecutorRegistry(),
        ).status(plan_id)


DEFAULT_RECONCILE_READERS = ReconcileReaderRegistry()

from hugegraph_mcp.tools.graph_write_adapter import (  # noqa: E402
    register_graph_reconcile_readers,
)
from hugegraph_mcp.tools.schema_write_adapter import (  # noqa: E402
    register_schema_reconcile_readers,
)

register_graph_reconcile_readers(DEFAULT_RECONCILE_READERS)
register_schema_reconcile_readers(DEFAULT_RECONCILE_READERS)


def reconcile_write(plan_id: str) -> dict:
    try:
        store = plan_store_from_config()
    except Exception as exc:
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "The durable plan store is unavailable.",
            retryable=False,
            details={"reason": type(exc).__name__},
        )
    try:
        return WriteReconciler(
            store=store,
            readers=DEFAULT_RECONCILE_READERS,
        ).reconcile(plan_id)
    except PlanTransitionError as exc:
        return envelope_err(
            ErrorType.WRITE_CONFLICT,
            "The persisted plan state changed during reconciliation.",
            retryable=False,
            details={"reason": str(exc)},
        )
