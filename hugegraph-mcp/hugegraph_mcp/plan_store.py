# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

"""Versioned SQLite persistence for immutable write plans and operations."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
    aggregate_plan_status,
    can_transition,
    canonical_plan_json,
)

SCHEMA_VERSION = 3


class PlanTransitionError(Exception):
    """The requested plan transition does not match durable state."""


class PlanStoreUnavailableError(Exception):
    """The configured durable plan store cannot safely serve writes."""


@runtime_checkable
class PlanStore(Protocol):
    def prepare(self) -> None: ...

    def save_plan(self, plan: WritePlan) -> None: ...

    def get_plan(self, plan_id: str) -> WritePlan | None: ...

    def get_plan_record(self, plan_id: str) -> dict[str, Any] | None: ...

    def transition_plan(
        self,
        plan_id: str,
        *,
        expected: PlanStatus,
        target: PlanStatus,
    ) -> WritePlan: ...

    def record_receipt(
        self,
        receipt: ApplyReceipt,
        *,
        owner_token: str | None = None,
        attempt_token: str | None = None,
    ) -> None: ...

    def claim_plan(
        self,
        plan_id: str,
        *,
        owner_token: str | None = None,
        lease_seconds: int = 30,
        resume: bool = False,
    ) -> tuple[WritePlan, bool]: ...

    def claim_operation(
        self,
        plan_id: str,
        operation_id: str,
        *,
        owner_token: str | None = None,
        attempt_token: str | None = None,
        lease_seconds: int = 30,
    ) -> int: ...

    def begin_reconcile(self, plan_id: str) -> WritePlan: ...

    def record_reconciliation_receipt(self, receipt: ApplyReceipt) -> None: ...


class SQLitePlanStore:
    DATABASE_NAME = "write_plans.sqlite3"
    LEGACY_DATABASE_NAME = "confirmations.sqlite3"

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.database_path = self.state_dir / self.DATABASE_NAME
        self.legacy_database_path = self.state_dir / self.LEGACY_DATABASE_NAME

    @classmethod
    def from_config(cls, cfg=None) -> SQLitePlanStore:
        if cfg is None:
            from hugegraph_mcp.config import MCPConfig

            cfg = MCPConfig.from_env()
        return cls(cfg.state_dir)

    @staticmethod
    def legacy_plan_id(plan_hash: str) -> str:
        return f"wp_legacy_{plan_hash}"

    @staticmethod
    def legacy_operation_id(plan_hash: str) -> str:
        return f"op_legacy_{plan_hash}"

    def prepare(self) -> None:
        self._prepare_storage()
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise PlanStoreUnavailableError(
                    f"write plan database schema {version} is newer than supported {SCHEMA_VERSION}"
                )
            self._migrate_schema(connection, version)
            self._migrate_legacy(connection)
            connection.commit()

    def save_plan(self, plan: WritePlan) -> None:
        """Persist one immutable plan and its ordered operations atomically."""
        self.prepare()
        payload_json = canonical_plan_json(plan)
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO write_plans (
                    plan_id, tool_name, graph_target_json, principal,
                    payload_json, payload_digest, schema_fingerprint, status,
                    created_at, expires_at, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    plan.plan_id,
                    plan.tool_name,
                    self._canonical_json(plan.graph_target.to_dict()),
                    plan.principal,
                    payload_json,
                    plan.payload_digest,
                    plan.schema_fingerprint,
                    plan.status.value,
                    plan.created_at,
                    plan.expires_at,
                ),
            )
            for ordinal, operation in enumerate(plan.operations):
                connection.execute(
                    """
                    INSERT INTO write_operations (
                        operation_id, plan_id, ordinal, kind, payload_json,
                        status, attempt, receipt_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)
                    """,
                    (
                        operation.operation_id,
                        plan.plan_id,
                        ordinal,
                        operation.kind,
                        self._canonical_json(operation.to_dict()),
                        PlanStatus.ISSUED.value,
                        plan.created_at,
                    ),
                )
            connection.commit()

    def get_plan(self, plan_id: str) -> WritePlan | None:
        """Rehydrate an immutable canonical plan from durable storage."""
        record = self.get_plan_record(plan_id)
        if record is None:
            return None
        # Legacy confirmation rows lack the canonical graph target and
        # operation state required for safe execution or reconciliation.
        if record["tool_name"] == "legacy":
            return None
        operations = tuple(
            OperationPlan(
                operation_id=item["payload"]["operation_id"],
                kind=item["payload"]["kind"],
                target=item["payload"]["target"],
                expected_state=item["payload"]["expected_state"],
                desired_state=item["payload"]["desired_state"],
                depends_on=tuple(item["payload"].get("depends_on") or ()),
                idempotency_key=item["payload"].get("idempotency_key"),
            )
            for item in record["operations"]
        )
        target = record["graph_target"]
        return WritePlan(
            plan_id=record["plan_id"],
            tool_name=record["tool_name"],
            graph_target=GraphTarget(
                graph_url=target["graph_url"],
                graph_name=target["graph_name"],
                graphspace=target.get("graphspace"),
            ),
            principal=record["principal"],
            operations=operations,
            payload_digest=record["payload_digest"],
            schema_fingerprint=record["schema_fingerprint"],
            status=PlanStatus(record["status"]),
            created_at=record["created_at"],
            expires_at=record["expires_at"],
        )

    def transition_plan(
        self,
        plan_id: str,
        *,
        expected: PlanStatus,
        target: PlanStatus,
    ) -> WritePlan:
        """Compare-and-set one legal plan transition in SQLite."""
        if not can_transition(expected, target):
            raise PlanTransitionError(f"illegal transition: {expected} -> {target}")
        self.prepare()
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            confirmed_at_sql = (
                ", confirmed_at = COALESCE(confirmed_at, strftime('%s','now'))"
                if target is PlanStatus.EXECUTING
                else ""
            )
            updated = connection.execute(
                f"""
                UPDATE write_plans SET status = ?{confirmed_at_sql}
                WHERE plan_id = ? AND status = ?
                """,
                (target.value, plan_id, expected.value),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise PlanTransitionError("durable plan state did not match the expected state")
            connection.commit()
        plan = self.get_plan(plan_id)
        if plan is None:
            raise PlanTransitionError("plan disappeared after transition")
        return plan

    def claim_plan(
        self,
        plan_id: str,
        *,
        owner_token: str | None = None,
        lease_seconds: int = 30,
        resume: bool = False,
    ) -> tuple[WritePlan, bool]:
        """Atomically elect one executor and persist its fencing lease."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.prepare()
        owner_token = owner_token or uuid.uuid4().hex
        now = int(time.time())
        claimed = False
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, lease_expires_at FROM write_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise PlanTransitionError("plan was not found")
            current = PlanStatus(row[0])
            claimable = {PlanStatus.ISSUED}
            if resume:
                claimable.update({PlanStatus.RETRYABLE_NOT_APPLIED, PlanStatus.PARTIAL})
            lease_available = row[1] is None or int(row[1]) <= now
            if current in claimable and lease_available:
                target = PlanStatus.EXECUTING if current is not PlanStatus.PARTIAL else current
                updated = connection.execute(
                    """
                    UPDATE write_plans
                    SET status = ?, confirmed_at = COALESCE(confirmed_at, ?),
                        lease_owner = ?, lease_expires_at = ?
                    WHERE plan_id = ? AND status = ?
                      AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                    """,
                    (
                        target.value,
                        now,
                        owner_token,
                        now + lease_seconds,
                        plan_id,
                        current.value,
                        now,
                    ),
                )
                claimed = updated.rowcount == 1
            connection.commit()
        plan = self.get_plan(plan_id)
        if plan is None:
            raise PlanTransitionError("plan disappeared after claim")
        return plan, claimed

    def claim_operation(
        self,
        plan_id: str,
        operation_id: str,
        *,
        owner_token: str | None = None,
        attempt_token: str | None = None,
        lease_seconds: int = 30,
    ) -> int:
        """Atomically claim one not-yet-applied operation and increment attempt."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.prepare()
        claimable = {
            PlanStatus.ISSUED.value,
            PlanStatus.RETRYABLE_NOT_APPLIED.value,
        }
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute(
                "SELECT lease_owner, lease_expires_at FROM write_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            now = int(time.time())
            if plan_row is None or plan_row[1] is None or int(plan_row[1]) <= now:
                connection.rollback()
                raise PlanTransitionError("executor lease is absent or expired")
            effective_owner = owner_token or str(plan_row[0])
            if plan_row[0] != effective_owner:
                connection.rollback()
                raise PlanTransitionError("executor lease owner did not match")
            row = connection.execute(
                """
                SELECT status, attempt FROM write_operations
                WHERE plan_id = ? AND operation_id = ?
                """,
                (plan_id, operation_id),
            ).fetchone()
            if row is None or row[0] not in claimable:
                connection.rollback()
                raise PlanTransitionError("operation is not claimable")
            attempt = int(row[1]) + 1
            attempt_token = attempt_token or uuid.uuid4().hex
            connection.execute(
                """
                UPDATE write_operations
                SET status = ?, attempt = ?, attempt_token = ?, reconciled = 0,
                    updated_at = ?
                WHERE plan_id = ? AND operation_id = ?
                """,
                (
                    PlanStatus.EXECUTING.value,
                    attempt,
                    attempt_token,
                    now,
                    plan_id,
                    operation_id,
                ),
            )
            renewed = connection.execute(
                """UPDATE write_plans SET lease_expires_at = ?
                   WHERE plan_id = ? AND lease_owner = ? AND lease_expires_at > ?""",
                (now + lease_seconds, plan_id, effective_owner, now),
            )
            if renewed.rowcount != 1:
                connection.rollback()
                raise PlanTransitionError("executor lease could not be renewed")
            connection.commit()
        return attempt

    def record_receipt(
        self,
        receipt: ApplyReceipt,
        *,
        owner_token: str | None = None,
        attempt_token: str | None = None,
    ) -> None:
        """Persist one operation receipt and recompute the aggregate plan state."""
        if not receipt.plan_id or not receipt.operation_id:
            raise ValueError("canonical receipt requires plan_id and operation_id")
        self.prepare()
        operation_status = PlanStatus(receipt.status.value)
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            operation_row = connection.execute(
                """
                SELECT o.status, o.attempt, o.attempt_token, p.lease_owner,
                       p.lease_expires_at
                FROM write_operations o JOIN write_plans p ON p.plan_id = o.plan_id
                WHERE o.plan_id = ? AND o.operation_id = ?
                """,
                (receipt.plan_id, receipt.operation_id),
            ).fetchone()
            if operation_row is None:
                connection.rollback()
                raise PlanTransitionError("operation receipt target was not found")
            effective_owner = owner_token or operation_row[3]
            effective_attempt_token = attempt_token or receipt.attempt_token or operation_row[2]
            if (
                operation_row[0] != PlanStatus.EXECUTING.value
                or int(operation_row[1]) != receipt.attempt
                or not effective_attempt_token
                or operation_row[2] != effective_attempt_token
                or operation_row[3] != effective_owner
                or operation_row[4] is None
                or int(operation_row[4]) <= int(time.time())
            ):
                connection.rollback()
                raise PlanTransitionError("stale or unfenced operation receipt")
            updated = connection.execute(
                """
                UPDATE write_operations
                SET status = ?, attempt = ?, receipt_json = ?, updated_at = ?
                WHERE plan_id = ? AND operation_id = ? AND status = ?
                    AND attempt = ? AND attempt_token = ?
                """,
                (
                    operation_status.value,
                    receipt.attempt,
                    self._canonical_json(receipt.to_dict()),
                    receipt.committed_at or 0,
                    receipt.plan_id,
                    receipt.operation_id,
                    PlanStatus.EXECUTING.value,
                    receipt.attempt,
                    effective_attempt_token,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise PlanTransitionError("operation receipt target was not found")
            rows = connection.execute(
                "SELECT status FROM write_operations WHERE plan_id = ? ORDER BY ordinal",
                (receipt.plan_id,),
            ).fetchall()
            aggregate = self._aggregate_persisted_statuses([str(row[0]) for row in rows])
            current_row = connection.execute(
                "SELECT status FROM write_plans WHERE plan_id = ?",
                (receipt.plan_id,),
            ).fetchone()
            if current_row is None:
                connection.rollback()
                raise PlanTransitionError("receipt plan was not found")
            current = PlanStatus(current_row[0])
            if current is not aggregate and not can_transition(current, aggregate):
                connection.rollback()
                raise PlanTransitionError(f"illegal receipt transition: {current} -> {aggregate}")
            keep_lease = receipt.status in {
                ApplyStatus.APPLIED,
                ApplyStatus.ALREADY_APPLIED,
            } and aggregate in {PlanStatus.EXECUTING, PlanStatus.PARTIAL}
            connection.execute(
                """UPDATE write_plans SET status = ?,
                       lease_owner = CASE WHEN ? THEN lease_owner ELSE NULL END,
                       lease_expires_at = CASE WHEN ? THEN lease_expires_at ELSE NULL END
                   WHERE plan_id = ?""",
                (aggregate.value, keep_lease, keep_lease, receipt.plan_id),
            )
            connection.commit()

    def begin_reconcile(self, plan_id: str) -> WritePlan:
        """Fence an expired executor before any read-only reconciliation."""
        self.prepare()
        now = int(time.time())
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, lease_expires_at FROM write_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise PlanTransitionError("plan was not found")
            status = PlanStatus(row[0])
            if row[1] is not None and int(row[1]) > now:
                connection.rollback()
                raise PlanTransitionError("execution lease is still active")
            if status is PlanStatus.EXECUTING:
                connection.execute(
                    """UPDATE write_plans SET status = ?, lease_owner = NULL,
                           lease_expires_at = NULL
                       WHERE plan_id = ? AND status = ? AND
                           (lease_expires_at IS NULL OR lease_expires_at <= ?)""",
                    (
                        PlanStatus.UNKNOWN.value,
                        plan_id,
                        PlanStatus.EXECUTING.value,
                        now,
                    ),
                )
            elif status in {
                PlanStatus.UNKNOWN,
                PlanStatus.LEGACY_UNKNOWN,
                PlanStatus.PARTIAL,
            }:
                connection.execute(
                    "UPDATE write_plans SET lease_owner = NULL, lease_expires_at = NULL WHERE plan_id = ?",
                    (plan_id,),
                )
            connection.commit()
        plan = self.get_plan(plan_id)
        if plan is None:
            raise PlanTransitionError("plan is not canonically rehydratable")
        return plan

    def record_reconciliation_receipt(self, receipt: ApplyReceipt) -> None:
        """Persist evidence only after the executor has been fenced."""
        if not receipt.plan_id or not receipt.operation_id:
            raise ValueError("canonical receipt requires plan_id and operation_id")
        self.prepare()
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute(
                "SELECT lease_owner FROM write_plans WHERE plan_id = ?",
                (receipt.plan_id,),
            ).fetchone()
            if plan_row is None or plan_row[0] is not None:
                connection.rollback()
                raise PlanTransitionError("reconciliation requires a fenced executor")
            updated = connection.execute(
                """UPDATE write_operations SET status = ?, receipt_json = ?,
                       updated_at = ?, reconciled = 1
                   WHERE plan_id = ? AND operation_id = ?
                     AND status IN ('ISSUED','EXECUTING','UNKNOWN','LEGACY_UNKNOWN')""",
                (
                    receipt.status.value,
                    self._canonical_json(receipt.to_dict()),
                    receipt.committed_at or int(time.time()),
                    receipt.plan_id,
                    receipt.operation_id,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise PlanTransitionError("operation is not reconcilable")
            statuses = [
                str(row[0])
                for row in connection.execute(
                    "SELECT status FROM write_operations WHERE plan_id = ? ORDER BY ordinal",
                    (receipt.plan_id,),
                )
            ]
            aggregate = self._aggregate_persisted_statuses(statuses)
            connection.execute(
                "UPDATE write_plans SET status = ? WHERE plan_id = ?",
                (aggregate.value, receipt.plan_id),
            )
            connection.commit()

    @staticmethod
    def _aggregate_persisted_statuses(statuses: list[str]) -> PlanStatus:
        completed: list[ApplyStatus] = []
        pending = False
        for status in statuses:
            try:
                completed.append(ApplyStatus(status))
            except ValueError:
                pending = True
        if pending:
            if any(status in {ApplyStatus.APPLIED, ApplyStatus.ALREADY_APPLIED} for status in completed):
                return PlanStatus.PARTIAL
            if ApplyStatus.UNKNOWN in completed:
                return PlanStatus.UNKNOWN
            if ApplyStatus.CONFLICT in completed:
                return PlanStatus.CONFLICT
            if ApplyStatus.RETRYABLE_NOT_APPLIED in completed:
                return PlanStatus.RETRYABLE_NOT_APPLIED
            if completed and all(status is ApplyStatus.REJECTED for status in completed):
                return PlanStatus.REJECTED
            return PlanStatus.EXECUTING
        return aggregate_plan_status(completed)

    def get_plan_record(self, plan_id: str) -> dict[str, Any] | None:
        self.prepare()
        with sqlite3.connect(self.database_path, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            plan = connection.execute(
                "SELECT * FROM write_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if plan is None:
                return None
            operations = connection.execute(
                """
                SELECT * FROM write_operations
                WHERE plan_id = ? ORDER BY ordinal
                """,
                (plan_id,),
            ).fetchall()
        return {
            "plan_id": plan["plan_id"],
            "tool_name": plan["tool_name"],
            "graph_target": json.loads(plan["graph_target_json"]),
            "principal": plan["principal"],
            "payload": json.loads(plan["payload_json"]),
            "payload_digest": plan["payload_digest"],
            "schema_fingerprint": plan["schema_fingerprint"],
            "status": plan["status"],
            "created_at": plan["created_at"],
            "expires_at": plan["expires_at"],
            "confirmed_at": plan["confirmed_at"],
            "lease_owner": plan["lease_owner"],
            "lease_expires_at": plan["lease_expires_at"],
            "operations": [
                {
                    "operation_id": operation["operation_id"],
                    "ordinal": operation["ordinal"],
                    "kind": operation["kind"],
                    "payload": json.loads(operation["payload_json"]),
                    "status": operation["status"],
                    "attempt": operation["attempt"],
                    "attempt_token": operation["attempt_token"],
                    "reconciled": bool(operation["reconciled"]),
                    "receipt": (json.loads(operation["receipt_json"]) if operation["receipt_json"] else None),
                    "updated_at": operation["updated_at"],
                }
                for operation in operations
            ],
        }

    def _migrate_schema(self, connection: sqlite3.Connection, version: int) -> None:
        """Apply additive schema steps in order; never silently downgrade."""
        if version < 1:
            self._ensure_v1_schema(connection)
            connection.execute("PRAGMA user_version = 1")
            version = 1
        if version < 2:
            plan_columns = {row[1] for row in connection.execute("PRAGMA table_info(write_plans)")}
            operation_columns = {row[1] for row in connection.execute("PRAGMA table_info(write_operations)")}
            if "lease_owner" not in plan_columns:
                connection.execute("ALTER TABLE write_plans ADD COLUMN lease_owner TEXT")
            if "lease_expires_at" not in plan_columns:
                connection.execute("ALTER TABLE write_plans ADD COLUMN lease_expires_at INTEGER")
            if "attempt_token" not in operation_columns:
                connection.execute("ALTER TABLE write_operations ADD COLUMN attempt_token TEXT")
            connection.execute("PRAGMA user_version = 2")
            version = 2
        if version < 3:
            operation_columns = {row[1] for row in connection.execute("PRAGMA table_info(write_operations)")}
            if "reconciled" not in operation_columns:
                connection.execute("ALTER TABLE write_operations ADD COLUMN reconciled INTEGER NOT NULL DEFAULT 0")
            connection.execute("PRAGMA user_version = 3")

    def _ensure_v1_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS write_plans (
                plan_id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                graph_target_json TEXT NOT NULL,
                principal TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                schema_fingerprint TEXT,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                confirmed_at INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS write_operations (
                operation_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                receipt_json TEXT,
                updated_at INTEGER NOT NULL,
                UNIQUE(plan_id, ordinal),
                FOREIGN KEY(plan_id) REFERENCES write_plans(plan_id)
            )
            """
        )

    def _migrate_legacy(self, connection: sqlite3.Connection) -> None:
        if not self.legacy_database_path.exists():
            return
        with sqlite3.connect(self.legacy_database_path, timeout=30) as legacy:
            legacy.row_factory = sqlite3.Row
            issued = self._legacy_rows(legacy, "issued_confirmations", "plan_hash")
            consumed = self._legacy_rows(legacy, "consumed_confirmations", "plan_hash")
            operations = self._legacy_rows(legacy, "write_operations", "plan_hash")

        for plan_hash in sorted(set(issued) | set(consumed) | set(operations)):
            self._migrate_legacy_plan(
                connection,
                plan_hash=plan_hash,
                issued=issued.get(plan_hash),
                consumed=consumed.get(plan_hash),
                operation=operations.get(plan_hash),
            )

    def _migrate_legacy_plan(
        self,
        connection: sqlite3.Connection,
        *,
        plan_hash: str,
        issued: sqlite3.Row | None,
        consumed: sqlite3.Row | None,
        operation: sqlite3.Row | None,
    ) -> None:
        payload_text = self._row_value(operation, "plan_payload_json")
        if payload_text is None:
            payload_text = self._row_value(issued, "plan_payload_json")
        payload, payload_valid = self._safe_json(payload_text)

        receipt_text = self._row_value(operation, "receipt_json")
        receipt, receipt_valid = self._safe_json(receipt_text)
        status = self._legacy_status(
            operation=operation,
            consumed=consumed,
            payload_valid=payload_valid,
            receipt_valid=receipt_valid,
        )
        if not payload_valid or not receipt_valid:
            receipt = {"reason_code": "CORRUPT_LEGACY_STATE"}

        created_at = int(
            self._row_value(issued, "issued_at")
            or self._row_value(consumed, "consumed_at")
            or self._row_value(operation, "updated_at")
            or 0
        )
        expires_at = int(self._row_value(issued, "expires_at") or self._row_value(consumed, "expires_at") or created_at)
        confirmed_at = int(self._row_value(consumed, "consumed_at")) if consumed else None
        plan_id = self.legacy_plan_id(plan_hash)
        payload_json = self._canonical_json(payload)
        receipt_json = self._canonical_json(receipt) if receipt is not None else None

        connection.execute(
            """
            INSERT OR IGNORE INTO write_plans (
                plan_id, tool_name, graph_target_json, principal, payload_json,
                payload_digest, schema_fingerprint, status, created_at,
                expires_at, confirmed_at
            ) VALUES (?, 'legacy', '{}', 'legacy', ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                plan_id,
                payload_json,
                plan_hash,
                status.value,
                created_at,
                expires_at,
                confirmed_at,
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO write_operations (
                operation_id, plan_id, ordinal, kind, payload_json, status,
                attempt, receipt_json, updated_at
            ) VALUES (?, ?, 0, 'LEGACY_CONFIRMATION', ?, ?, ?, ?, ?)
            """,
            (
                self.legacy_operation_id(plan_hash),
                plan_id,
                payload_json,
                status.value,
                1 if consumed else 0,
                receipt_json,
                int(self._row_value(operation, "updated_at") or created_at),
            ),
        )

    @staticmethod
    def _legacy_status(
        *,
        operation: sqlite3.Row | None,
        consumed: sqlite3.Row | None,
        payload_valid: bool,
        receipt_valid: bool,
    ) -> PlanStatus:
        if not payload_valid or not receipt_valid:
            return PlanStatus.LEGACY_UNKNOWN
        raw_status = SQLitePlanStore._row_value(operation, "status")
        if raw_status is not None:
            try:
                return PlanStatus(raw_status)
            except ValueError:
                return PlanStatus.LEGACY_UNKNOWN
        if consumed is not None:
            return PlanStatus.LEGACY_UNKNOWN
        return PlanStatus.ISSUED

    @staticmethod
    def _legacy_rows(
        connection: sqlite3.Connection,
        table: str,
        key: str,
    ) -> dict[str, sqlite3.Row]:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            return {}
        return {str(row[key]): row for row in connection.execute(f"SELECT * FROM {table}")}

    @staticmethod
    def _row_value(row: sqlite3.Row | None, key: str) -> Any:
        if row is None or key not in set(row.keys()):
            return None
        return row[key]

    @staticmethod
    def _safe_json(value: str | None) -> tuple[Any, bool]:
        if value is None:
            return None, True
        try:
            return json.loads(value), True
        except (TypeError, json.JSONDecodeError):
            return None, False

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _prepare_storage(self) -> None:
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_dir.chmod(0o700)
        descriptor = os.open(
            self.database_path,
            os.O_CREAT | os.O_APPEND | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        self.database_path.chmod(0o600)


def plan_store_from_config(cfg=None) -> PlanStore:
    if cfg is None:
        from hugegraph_mcp.config import MCPConfig

        cfg = MCPConfig.from_env()
    if not cfg.has_safe_write_store():
        raise PlanStoreUnavailableError("The configured plan store is not safe for this write topology")
    return SQLitePlanStore(cfg.state_dir)
