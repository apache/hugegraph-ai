# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

"""Canonical immutable models and state rules for confirmed writes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any


class ApplyStatus(str, Enum):
    """Evidence-backed outcome of one write operation."""

    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    LEGACY_UNKNOWN = "LEGACY_UNKNOWN"
    RETRYABLE_NOT_APPLIED = "RETRYABLE_NOT_APPLIED"


class PlanStatus(str, Enum):
    """Lifecycle and aggregate outcome of one immutable write plan."""

    ISSUED = "ISSUED"
    EXECUTING = "EXECUTING"
    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    LEGACY_UNKNOWN = "LEGACY_UNKNOWN"
    RETRYABLE_NOT_APPLIED = "RETRYABLE_NOT_APPLIED"
    EXPIRED = "EXPIRED"


ALLOWED_PLAN_TRANSITIONS: Mapping[PlanStatus, frozenset[PlanStatus]] = MappingProxyType(
    {
        PlanStatus.ISSUED: frozenset({PlanStatus.EXECUTING, PlanStatus.EXPIRED}),
        PlanStatus.EXECUTING: frozenset(
            {
                PlanStatus.APPLIED,
                PlanStatus.ALREADY_APPLIED,
                PlanStatus.REJECTED,
                PlanStatus.CONFLICT,
                PlanStatus.PARTIAL,
                PlanStatus.UNKNOWN,
            }
        ),
        PlanStatus.UNKNOWN: frozenset(
            {
                PlanStatus.APPLIED,
                PlanStatus.CONFLICT,
                PlanStatus.RETRYABLE_NOT_APPLIED,
            }
        ),
        PlanStatus.LEGACY_UNKNOWN: frozenset(
            {
                PlanStatus.APPLIED,
                PlanStatus.CONFLICT,
                PlanStatus.RETRYABLE_NOT_APPLIED,
            }
        ),
        PlanStatus.RETRYABLE_NOT_APPLIED: frozenset({PlanStatus.EXECUTING}),
        PlanStatus.PARTIAL: frozenset({PlanStatus.PARTIAL, PlanStatus.APPLIED, PlanStatus.UNKNOWN}),
        PlanStatus.APPLIED: frozenset(),
        PlanStatus.ALREADY_APPLIED: frozenset(),
        PlanStatus.REJECTED: frozenset(),
        PlanStatus.CONFLICT: frozenset(),
        PlanStatus.EXPIRED: frozenset(),
    }
)


@dataclass(frozen=True)
class GraphTarget:
    graph_url: str
    graph_name: str
    graphspace: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_url": self.graph_url,
            "graph_name": self.graph_name,
            "graphspace": self.graphspace,
        }


@dataclass(frozen=True)
class OperationPlan:
    operation_id: str
    kind: str
    target: Mapping[str, Any]
    expected_state: Mapping[str, Any]
    desired_state: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError("operation_id must be non-empty")
        if not self.kind:
            raise ValueError("operation kind must be non-empty")
        object.__setattr__(self, "target", _freeze_mapping(self.target))
        object.__setattr__(
            self,
            "expected_state",
            _freeze_mapping(self.expected_state),
        )
        object.__setattr__(
            self,
            "desired_state",
            _freeze_mapping(self.desired_state),
        )
        object.__setattr__(self, "depends_on", tuple(self.depends_on))

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "target": _thaw(self.target),
            "expected_state": _thaw(self.expected_state),
            "desired_state": _thaw(self.desired_state),
            "depends_on": list(self.depends_on),
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class WritePlan:
    plan_id: str
    tool_name: str
    graph_target: GraphTarget
    principal: str
    operations: tuple[OperationPlan, ...]
    payload_digest: str
    schema_fingerprint: str | None
    status: PlanStatus
    created_at: int
    expires_at: int

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("plan_id must be non-empty")
        if not self.tool_name:
            raise ValueError("tool_name must be non-empty")
        operations = tuple(self.operations)
        object.__setattr__(self, "operations", operations)

        seen: set[str] = set()
        for operation in operations:
            if operation.operation_id in seen:
                raise ValueError(f"duplicate operation_id: {operation.operation_id}")
            missing = [dependency for dependency in operation.depends_on if dependency not in seen]
            if missing:
                raise ValueError(
                    f"operation {operation.operation_id} depends on an earlier operation: {', '.join(missing)}"
                )
            seen.add(operation.operation_id)

        if self.created_at < 0 or self.expires_at <= self.created_at:
            raise ValueError("expires_at must be greater than created_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "tool_name": self.tool_name,
            "graph_target": self.graph_target.to_dict(),
            "principal": self.principal,
            "operations": [operation.to_dict() for operation in self.operations],
            "payload_digest": self.payload_digest,
            "schema_fingerprint": self.schema_fingerprint,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class ApplyReceipt:
    """Canonical receipt with a temporary legacy construction shape."""

    status: ApplyStatus
    plan_id: str | None = None
    operation_id: str | None = None
    observed_state: Mapping[str, Any] | None = None
    reason_code: str | None = None
    attempt: int = 0
    attempt_token: str | None = None
    reconciliation_required: bool = False
    committed_at: int | None = None
    operation: Mapping[str, Any] | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.attempt < 0:
            raise ValueError("attempt must not be negative")
        if self.observed_state is not None:
            object.__setattr__(
                self,
                "observed_state",
                _freeze_mapping(self.observed_state),
            )
        if self.operation is not None:
            object.__setattr__(
                self,
                "operation",
                _freeze_mapping(self.operation),
            )

    def to_dict(self) -> dict[str, Any]:
        if self.plan_id is None and self.operation_id is None:
            return {
                "status": self.status.value,
                "operation": _thaw(self.operation),
                "observed_state": _thaw(self.observed_state),
                "reason": self.reason,
                "reconciliation_required": self.reconciliation_required,
            }
        return {
            "plan_id": self.plan_id,
            "operation_id": self.operation_id,
            "status": self.status.value,
            "observed_state": _thaw(self.observed_state),
            "reason_code": self.reason_code,
            "attempt": self.attempt,
            "reconciliation_required": self.reconciliation_required,
            "committed_at": self.committed_at,
            **({"attempt_token": self.attempt_token} if self.attempt_token is not None else {}),
        }


def can_transition(current: PlanStatus, target: PlanStatus) -> bool:
    """Return whether the explicit state machine permits this transition."""

    return target in ALLOWED_PLAN_TRANSITIONS.get(current, frozenset())


def aggregate_plan_status(
    operation_statuses: Sequence[ApplyStatus],
) -> PlanStatus:
    """Aggregate operation evidence without hiding known partial writes."""

    statuses = tuple(operation_statuses)
    if not statuses:
        return PlanStatus.ISSUED

    success = {ApplyStatus.APPLIED, ApplyStatus.ALREADY_APPLIED}
    if all(status in success for status in statuses):
        if all(status is ApplyStatus.ALREADY_APPLIED for status in statuses):
            return PlanStatus.ALREADY_APPLIED
        return PlanStatus.APPLIED
    if any(status in success for status in statuses):
        return PlanStatus.PARTIAL
    if ApplyStatus.PARTIAL in statuses:
        return PlanStatus.PARTIAL
    if ApplyStatus.UNKNOWN in statuses:
        return PlanStatus.UNKNOWN
    if ApplyStatus.CONFLICT in statuses:
        return PlanStatus.CONFLICT
    if ApplyStatus.RETRYABLE_NOT_APPLIED in statuses:
        return PlanStatus.RETRYABLE_NOT_APPLIED
    return PlanStatus.REJECTED


def canonical_plan_json(plan: WritePlan) -> str:
    """Serialize one plan deterministically for integrity checks."""

    return json.dumps(
        plan.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_plan_digest(plan: WritePlan) -> str:
    """Return the full SHA-256 digest of a canonical plan."""

    return hashlib.sha256(canonical_plan_json(plan).encode("utf-8")).hexdigest()


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("write plan state must be a mapping")
    return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted((_thaw(item) for item in value), key=repr)
    if isinstance(value, Enum):
        return value.value
    return value
