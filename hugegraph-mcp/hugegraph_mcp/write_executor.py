# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

"""Unified plan-ID confirmation and executor dispatch."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from math import ceil

from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.plan_store import (
    PlanStore,
    PlanTransitionError,
    plan_store_from_config,
)
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    OperationPlan,
    PlanStatus,
    WritePlan,
)

WriteAdapter = Callable[[WritePlan, OperationPlan, int], ApplyReceipt]
LEASE_SAFETY_MARGIN_SECONDS = 5


class WriteExecutorRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, WriteAdapter] = {}

    def register(self, kind: str, adapter: WriteAdapter) -> None:
        if not kind:
            raise ValueError("adapter kind must be non-empty")
        self._adapters[kind] = adapter

    def adapter_for(self, kind: str) -> WriteAdapter | None:
        return self._adapters.get(kind)


class WriteExecutor:
    def __init__(
        self,
        *,
        store: PlanStore,
        registry: WriteExecutorRegistry,
        lease_seconds: int = 300,
    ):
        self.store = store
        self.registry = registry
        self.lease_seconds = lease_seconds

    def confirm(self, plan_id: str) -> dict:
        plan = self.store.get_plan(plan_id)
        if plan is None:
            return envelope_err(
                ErrorType.NOT_FOUND,
                "No server-issued write plan matches this plan_id.",
                retryable=False,
            )
        if int(time.time()) > plan.expires_at and plan.status is PlanStatus.ISSUED:
            self.store.transition_plan(
                plan_id,
                expected=PlanStatus.ISSUED,
                target=PlanStatus.EXPIRED,
            )
            return self._confirmation_result(plan_id)

        missing = [operation.kind for operation in plan.operations if self.registry.adapter_for(operation.kind) is None]
        if missing:
            return envelope_err(
                ErrorType.FEATURE_DISABLED,
                "The confirmed plan requires an unavailable atomic write adapter.",
                retryable=False,
                details={"missing_operation_kinds": sorted(set(missing))},
            )

        try:
            owner_token = uuid.uuid4().hex
            claimed_plan, claimed = self.store.claim_plan(
                plan_id,
                owner_token=owner_token,
                lease_seconds=self.lease_seconds,
            )
        except PlanTransitionError:
            return self._confirmation_result(plan_id)
        if not claimed:
            return self._confirmation_result(plan_id)

        return self._execute_claimed(
            claimed_plan,
            claimable={PlanStatus.ISSUED.value},
            owner_token=owner_token,
        )

    def resume(self, plan_id: str) -> dict:
        plan = self.store.get_plan(plan_id)
        record = self.store.get_plan_record(plan_id)
        if plan is None or record is None:
            raise PlanTransitionError("resume requires a reconciled RETRYABLE_NOT_APPLIED plan")
        operation_statuses = {operation["operation_id"]: operation["status"] for operation in record["operations"]}
        reconciled_operations = {
            operation["operation_id"]: operation["reconciled"] for operation in record["operations"]
        }
        statuses = set(operation_statuses.values())
        resumable = {
            PlanStatus.APPLIED.value,
            PlanStatus.ALREADY_APPLIED.value,
            PlanStatus.RETRYABLE_NOT_APPLIED.value,
        }
        if (
            plan.status not in {PlanStatus.RETRYABLE_NOT_APPLIED, PlanStatus.PARTIAL}
            or PlanStatus.RETRYABLE_NOT_APPLIED.value not in statuses
            or not statuses <= resumable
            or any(
                not reconciled_operations[operation_id]
                for operation_id, status in operation_statuses.items()
                if status == PlanStatus.RETRYABLE_NOT_APPLIED.value
            )
        ):
            raise PlanTransitionError(
                "resume requires reconciled operations whose remaining state is RETRYABLE_NOT_APPLIED"
            )
        missing = [
            operation.kind
            for operation in plan.operations
            if operation_statuses[operation.operation_id] == PlanStatus.RETRYABLE_NOT_APPLIED.value
            and self.registry.adapter_for(operation.kind) is None
        ]
        if missing:
            return envelope_err(
                ErrorType.FEATURE_DISABLED,
                "The reconciled plan requires an unavailable atomic write adapter.",
                retryable=False,
                details={"missing_operation_kinds": sorted(set(missing))},
            )
        owner_token = uuid.uuid4().hex
        claimed_plan, claimed = self.store.claim_plan(
            plan_id,
            owner_token=owner_token,
            lease_seconds=self.lease_seconds,
            resume=True,
        )
        if not claimed:
            raise PlanTransitionError("resumable plan could not be exclusively leased")
        return self._execute_claimed(
            claimed_plan,
            claimable={PlanStatus.RETRYABLE_NOT_APPLIED.value},
            owner_token=owner_token,
        )

    def _execute_claimed(
        self,
        claimed_plan: WritePlan,
        *,
        claimable: set[str],
        owner_token: str,
    ) -> dict:
        plan_id = claimed_plan.plan_id
        record = self.store.get_plan_record(plan_id)
        if record is None:
            raise PlanTransitionError("claimed plan disappeared before execution")
        operation_statuses = {operation["operation_id"]: operation["status"] for operation in record["operations"]}

        for operation in claimed_plan.operations:
            if operation_statuses[operation.operation_id] not in claimable:
                continue
            adapter = self.registry.adapter_for(operation.kind)
            assert adapter is not None
            attempt_token = uuid.uuid4().hex
            attempt = self.store.claim_operation(
                plan_id,
                operation.operation_id,
                owner_token=owner_token,
                attempt_token=attempt_token,
                lease_seconds=self.lease_seconds,
            )
            try:
                receipt = adapter(claimed_plan, operation, attempt)
            except Exception as exc:  # noqa: BLE001 - persist ambiguous adapter outcome
                receipt = ApplyReceipt(
                    plan_id=plan_id,
                    operation_id=operation.operation_id,
                    status=ApplyStatus.UNKNOWN,
                    reason_code=type(exc).__name__,
                    attempt=attempt,
                    reconciliation_required=True,
                )
            receipt = replace(receipt, attempt_token=attempt_token)
            self.store.record_receipt(
                receipt,
                owner_token=owner_token,
                attempt_token=attempt_token,
            )
            if receipt.status not in {
                ApplyStatus.APPLIED,
                ApplyStatus.ALREADY_APPLIED,
            }:
                break
        return self._confirmation_result(plan_id)

    def _confirmation_result(self, plan_id: str) -> dict:
        status_result = self.status(plan_id)
        if not status_result.get("ok"):
            return status_result
        data = status_result["data"]
        status = PlanStatus(data["status"])
        if status in {PlanStatus.APPLIED, PlanStatus.ALREADY_APPLIED}:
            return status_result
        error_type = {
            PlanStatus.PARTIAL: ErrorType.PARTIAL_APPLY,
            PlanStatus.CONFLICT: ErrorType.WRITE_CONFLICT,
            PlanStatus.REJECTED: ErrorType.FLOW_EXECUTION_FAILED,
            PlanStatus.EXPIRED: ErrorType.PLAN_EXPIRED,
        }.get(status, ErrorType.WRITE_OUTCOME_UNKNOWN)
        return envelope_err(
            error_type,
            "The confirmed write plan did not reach an applied final state.",
            retryable=False,
            details=data,
        )

    def status(self, plan_id: str) -> dict:
        record = self.store.get_plan_record(plan_id)
        if record is None:
            return envelope_err(
                ErrorType.NOT_FOUND,
                "No persisted write plan matches this plan_id.",
                retryable=False,
            )
        public = dict(record)
        public.pop("payload", None)
        public["operations"] = [
            {
                key: (
                    {
                        receipt_key: receipt_value
                        for receipt_key, receipt_value in value.items()
                        if receipt_key != "attempt_token"
                    }
                    if key == "receipt" and isinstance(value, dict)
                    else value
                )
                for key, value in operation.items()
                if key not in {"payload", "attempt_token", "reconciled"}
            }
            for operation in record["operations"]
        ]
        if public["status"] == PlanStatus.LEGACY_UNKNOWN.value:
            public["status"] = PlanStatus.UNKNOWN.value
            public["reconciliation_required"] = True
        elif public["status"] == PlanStatus.EXECUTING.value:
            lease_expires_at = public.get("lease_expires_at")
            if lease_expires_at is None or int(lease_expires_at) <= int(time.time()):
                public["status"] = PlanStatus.UNKNOWN.value
                public["reconciliation_required"] = True
            else:
                public["reconciliation_required"] = False
        public.pop("lease_owner", None)
        return envelope_ok(public)


DEFAULT_WRITE_EXECUTOR_REGISTRY = WriteExecutorRegistry()

# Graph adapters are registered here, after the registry type is defined, to
# keep the adapter module independent of executor orchestration.
from hugegraph_mcp.tools.graph_write_adapter import (
    register_graph_write_adapters,
)
from hugegraph_mcp.tools.schema_write_adapter import (
    register_schema_write_adapters,
)

register_graph_write_adapters(DEFAULT_WRITE_EXECUTOR_REGISTRY)
register_schema_write_adapters(DEFAULT_WRITE_EXECUTOR_REGISTRY)


def confirm_write(plan_id: str) -> dict:
    try:
        from hugegraph_mcp.config import MCPConfig

        cfg = MCPConfig.from_env()
        store = plan_store_from_config(cfg)
    except Exception as exc:  # noqa: BLE001 - public tool must remain enveloped
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "The durable plan store is unavailable.",
            retryable=False,
            details={"reason": type(exc).__name__},
        )
    return WriteExecutor(
        store=store,
        registry=DEFAULT_WRITE_EXECUTOR_REGISTRY,
        lease_seconds=ceil(cfg.write_timeout_seconds) + LEASE_SAFETY_MARGIN_SECONDS,
    ).confirm(plan_id)


def get_write_status(plan_id: str) -> dict:
    try:
        store = plan_store_from_config()
    except Exception as exc:  # noqa: BLE001 - public tool must remain enveloped
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "The durable plan store is unavailable.",
            retryable=False,
            details={"reason": type(exc).__name__},
        )
    return WriteExecutor(
        store=store,
        registry=DEFAULT_WRITE_EXECUTOR_REGISTRY,
    ).status(plan_id)
