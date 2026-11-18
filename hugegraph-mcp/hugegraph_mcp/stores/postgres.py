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

"""PostgreSQL authoritative PlanStore with optimistic fencing and transactional outbox."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Protocol

from hugegraph_mcp.events import ResourceEvent
from hugegraph_mcp.plan_store import PlanStoreUnavailableError, PlanTransitionError
from hugegraph_mcp.stores.base import (
    Actor,
    Lease,
    LeaseConflictError,
    PlanNotFoundError,
    PlanOutcome,
    PlanView,
)
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

POSTGRES_DDL = """
CREATE TABLE IF NOT EXISTS write_plans (
    plan_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    owner_tenant TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    graphspace TEXT NOT NULL,
    graph TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    payload_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    fence BIGINT NOT NULL DEFAULT 0,
    lease_holder TEXT,
    lease_expires_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE write_plans
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS plan_operations (
    plan_id TEXT NOT NULL REFERENCES write_plans(plan_id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL,
    target_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'ISSUED',
    attempt INTEGER NOT NULL DEFAULT 0,
    attempt_token TEXT,
    reconciled BOOLEAN NOT NULL DEFAULT FALSE,
    apply_status TEXT,
    receipt_json JSONB,
    recorded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (plan_id, operation_id)
);

ALTER TABLE plan_operations
    ADD COLUMN IF NOT EXISTS ordinal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE plan_operations
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ISSUED';
ALTER TABLE plan_operations
    ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 0;
ALTER TABLE plan_operations
    ADD COLUMN IF NOT EXISTS attempt_token TEXT;
ALTER TABLE plan_operations
    ADD COLUMN IF NOT EXISTS reconciled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE plan_operations
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS event_outbox (
    seq BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    deployment TEXT NOT NULL,
    graphspace TEXT NOT NULL,
    graph TEXT NOT NULL,
    uri TEXT NOT NULL,
    kind TEXT NOT NULL,
    resource_version BIGINT NOT NULL,
    txid BIGINT NOT NULL DEFAULT txid_current(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE event_outbox
    ADD COLUMN IF NOT EXISTS txid BIGINT NOT NULL DEFAULT txid_current();

CREATE INDEX IF NOT EXISTS idx_event_outbox_created ON event_outbox (seq);
CREATE INDEX IF NOT EXISTS idx_event_outbox_txid ON event_outbox (seq, txid);
"""


class AsyncDBConnection(Protocol):
    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None: ...

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...


class AsyncDBPool(Protocol):
    async def acquire(self) -> AsyncDBConnection: ...

    async def release(self, conn: AsyncDBConnection, exc: BaseException | None = None) -> None: ...

    async def close(self) -> None: ...


class PostgresPlanStore:
    """Shared multi-instance PlanStore backed by PostgreSQL + transactional outbox."""

    def __init__(
        self,
        dsn: str,
        *,
        pool: AsyncDBPool | None = None,
        deployment_id: str = "default",
    ) -> None:
        if not dsn or not dsn.strip():
            raise PlanStoreUnavailableError("PostgresPlanStore requires a non-empty DSN")
        self._dsn = dsn.strip()
        self._pool = pool
        self._deployment_id = deployment_id or "default"

    async def prepare(self) -> None:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            for statement in [stmt.strip() for stmt in POSTGRES_DDL.split(";") if stmt.strip()]:
                await conn.execute(statement)
        finally:
            await pool.release(conn)

    def _require_pool(self) -> AsyncDBPool:
        if self._pool is None:
            self._pool = _create_psycopg_pool(self._dsn)
        return self._pool

    async def fetch_outbox_since(
        self,
        after_seq: int,
        *,
        limit: int = 100,
    ) -> list[tuple[int, ResourceEvent]]:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            rows = await conn.fetchall(
                """
                SELECT seq, event_id, deployment, graphspace, graph, uri, kind,
                       resource_version, EXTRACT(EPOCH FROM created_at) AS created_at
                FROM event_outbox
                WHERE seq > %s
                  AND txid < txid_snapshot_xmin(txid_current_snapshot())
                ORDER BY seq ASC
                LIMIT %s
                """,
                (after_seq, limit),
            )
            results: list[tuple[int, ResourceEvent]] = []
            for r in rows:
                seq = int(r["seq"])
                results.append(
                    (
                        seq,
                        ResourceEvent(
                            event_id=str(r["event_id"]),
                            deployment=r["deployment"],
                            graphspace=r["graphspace"],
                            graph=r["graph"],
                            uri=r["uri"],
                            kind=r["kind"],
                            resource_version=int(r["resource_version"]),
                            created_at=float(r.get("created_at") or time.time()),
                        ),
                    )
                )
            return results
        finally:
            await pool.release(conn)

    async def create(self, plan: WritePlan, actor: Actor) -> PlanView:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            payload_json = canonical_plan_json(plan)
            graphspace = plan.graph_target.graphspace or "DEFAULT"
            await conn.execute(
                """
                INSERT INTO write_plans (
                    plan_id, tool_name, owner_tenant, owner_subject,
                    graphspace, graph, payload_json, payload_digest,
                    status, version, fence, expires_at, summary_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 1, 0, to_timestamp(%s), %s::jsonb)
                """,
                (
                    plan.plan_id,
                    plan.tool_name,
                    actor.tenant,
                    actor.subject,
                    graphspace,
                    plan.graph_target.graph_name,
                    payload_json,
                    plan.payload_digest,
                    plan.status.value,
                    plan.expires_at,
                    json.dumps({"operation_count": len(plan.operations)}),
                ),
            )
            for idx, op in enumerate(plan.operations):
                await conn.execute(
                    """
                    INSERT INTO plan_operations (
                        plan_id, operation_id, ordinal, kind, target_json, status, attempt, reconciled
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, 0, FALSE)
                    """,
                    (
                        plan.plan_id,
                        op.operation_id,
                        idx,
                        op.kind,
                        json.dumps(op.to_dict()["target"]),
                        PlanStatus.ISSUED.value,
                    ),
                )
            return await self._read_with_conn(conn, plan.plan_id, actor)
        finally:
            await pool.release(conn)

    async def read(self, plan_id: str, actor: Actor) -> PlanView:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            return await self._read_with_conn(conn, plan_id, actor)
        finally:
            await pool.release(conn)

    async def _read_with_conn(self, conn: AsyncDBConnection, plan_id: str, actor: Actor) -> PlanView:
        row = await conn.fetchone(
            """
            SELECT plan_id, tool_name, owner_tenant, owner_subject, graphspace, graph,
                   status, version, EXTRACT(EPOCH FROM expires_at) AS expires_at,
                   summary_json
            FROM write_plans
            WHERE plan_id = %s AND owner_tenant = %s AND owner_subject = %s
            """,
            (plan_id, actor.tenant, actor.subject),
        )
        if row is None:
            raise PlanNotFoundError(f"Write plan {plan_id!r} not found")
        op_rows = await conn.fetchall(
            """
            SELECT operation_id, kind, target_json, apply_status, receipt_json
            FROM plan_operations
            WHERE plan_id = %s
            ORDER BY operation_id ASC
            """,
            (plan_id,),
        )
        operations = tuple(
            {
                "operation_id": r["operation_id"],
                "kind": r["kind"],
                "target": r["target_json"],
            }
            for r in op_rows
        )
        receipts = tuple(r["receipt_json"] for r in op_rows if r.get("receipt_json") is not None)
        return PlanView(
            plan_id=row["plan_id"],
            tool_name=row["tool_name"],
            status=PlanStatus(row["status"]),
            owner_tenant=row["owner_tenant"],
            owner_subject=row["owner_subject"],
            graphspace=row["graphspace"],
            graph=row["graph"],
            expires_at=float(row["expires_at"]),
            version=int(row["version"]),
            operations=operations,
            receipts=receipts,
            summary=dict(row.get("summary_json") or {}),
        )

    async def claim(
        self,
        plan_id: str,
        actor: Actor,
        holder: str,
        ttl_s: int = 30,
    ) -> Lease:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            row = await conn.fetchone(
                """
                UPDATE write_plans
                SET status = 'EXECUTING',
                    lease_holder = %s,
                    fence = fence + 1,
                    lease_expires_at = NOW() + (%s || ' seconds')::interval,
                    version = version + 1,
                    updated_at = NOW()
                WHERE plan_id = %s
                  AND owner_tenant = %s
                  AND owner_subject = %s
                  AND status = 'ISSUED'
                  AND expires_at > NOW()
                RETURNING fence, version, EXTRACT(EPOCH FROM lease_expires_at) AS lease_expires_at
                """,
                (holder, ttl_s, plan_id, actor.tenant, actor.subject),
            )
            if row is None:
                # Distinguish missing/unauthorized from lease conflict only after verifying ownership.
                await self._read_with_conn(conn, plan_id, actor)
                raise LeaseConflictError(
                    f"Plan {plan_id!r} cannot be claimed (already executing, completed, or expired)"
                )
            return Lease(
                plan_id=plan_id,
                holder=holder,
                fence=int(row["fence"]),
                expires_at=float(row["lease_expires_at"]),
                plan_version=int(row["version"]),
            )
        finally:
            await pool.release(conn)

    async def renew(self, lease: Lease, actor: Actor, ttl_s: int = 30) -> Lease:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            row = await conn.fetchone(
                """
                UPDATE write_plans
                SET lease_expires_at = NOW() + (%s || ' seconds')::interval,
                    updated_at = NOW()
                WHERE plan_id = %s
                  AND owner_tenant = %s
                  AND owner_subject = %s
                  AND status = 'EXECUTING'
                  AND lease_holder = %s
                  AND fence = %s
                  AND lease_expires_at > NOW()
                RETURNING EXTRACT(EPOCH FROM lease_expires_at) AS lease_expires_at
                """,
                (ttl_s, lease.plan_id, actor.tenant, actor.subject, lease.holder, lease.fence),
            )
            if row is None:
                raise LeaseConflictError(f"Lease renew rejected for plan {lease.plan_id!r}")
            return Lease(
                plan_id=lease.plan_id,
                holder=lease.holder,
                fence=lease.fence,
                expires_at=float(row["lease_expires_at"]),
                plan_version=lease.plan_version,
            )
        finally:
            await pool.release(conn)

    async def record_operation(
        self,
        lease: Lease,
        actor: Actor,
        operation_id: str,
        expected_version: int,
        receipt: ApplyReceipt,
    ) -> PlanView:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            plan_row = await conn.fetchone(
                """
                UPDATE write_plans
                SET version = version + 1,
                    updated_at = NOW()
                WHERE plan_id = %s
                  AND owner_tenant = %s
                  AND owner_subject = %s
                  AND status = 'EXECUTING'
                  AND version = %s
                  AND fence = %s
                  AND lease_expires_at > NOW()
                RETURNING version
                """,
                (lease.plan_id, actor.tenant, actor.subject, expected_version, lease.fence),
            )
            if plan_row is None:
                raise LeaseConflictError(f"Stale version or expired lease for plan {lease.plan_id!r}")
            receipt_payload = {
                **receipt.to_dict(),
                "recorded_at": time.time(),
            }
            await conn.execute(
                """
                UPDATE plan_operations
                SET apply_status = %s,
                    receipt_json = COALESCE(receipt_json, %s::jsonb),
                    recorded_at = COALESCE(recorded_at, NOW())
                WHERE plan_id = %s AND operation_id = %s
                """,
                (receipt.status.value, json.dumps(receipt_payload), lease.plan_id, operation_id),
            )
            return await self._read_with_conn(conn, lease.plan_id, actor)
        finally:
            await pool.release(conn)

    async def finish(
        self,
        lease: Lease,
        actor: Actor,
        expected_version: int,
        outcome: PlanOutcome,
        events: tuple[ResourceEvent, ...] = (),
    ) -> PlanView:
        pool = self._require_pool()
        conn = await pool.acquire()
        err: BaseException | None = None
        try:
            row = await conn.fetchone(
                """
                UPDATE write_plans
                SET status = %s,
                    summary_json = %s::jsonb,
                    version = version + 1,
                    lease_holder = NULL,
                    updated_at = NOW()
                WHERE plan_id = %s
                  AND owner_tenant = %s
                  AND owner_subject = %s
                  AND status = 'EXECUTING'
                  AND lease_holder = %s
                  AND lease_expires_at > NOW()
                  AND version = %s
                  AND fence = %s
                RETURNING version
                """,
                (
                    outcome.status.value,
                    json.dumps(outcome.summary),
                    lease.plan_id,
                    actor.tenant,
                    actor.subject,
                    lease.holder,
                    expected_version,
                    lease.fence,
                ),
            )
            if row is None:
                raise LeaseConflictError(
                    f"Cannot finish plan {lease.plan_id!r}: stale version, holder, or expired lease"
                )
            for event in events:
                await conn.execute(
                    """
                    INSERT INTO event_outbox (
                        event_id, deployment, graphspace, graph, uri, kind, resource_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (
                        event.event_id,
                        event.deployment,
                        event.graphspace,
                        event.graph,
                        event.uri,
                        event.kind,
                        event.resource_version,
                    ),
                )
            return await self._read_with_conn(conn, lease.plan_id, actor)
        except BaseException as exc:
            err = exc
            raise
        finally:
            await pool.release(conn, err)

    async def mark_uncertain(
        self,
        plan_id: str,
        actor: Actor,
        expected_version: int,
        reason: str,
    ) -> PlanView:
        pool = self._require_pool()
        conn = await pool.acquire()
        err: BaseException | None = None
        try:
            row = await conn.fetchone(
                """
                UPDATE write_plans
                SET status = 'UNKNOWN',
                    summary_json = jsonb_set(summary_json, '{uncertain_reason}', to_jsonb(%s::text), true),
                    version = version + 1,
                    lease_holder = NULL,
                    updated_at = NOW()
                WHERE plan_id = %s
                  AND owner_tenant = %s
                  AND owner_subject = %s
                  AND status IN ('ISSUED', 'EXECUTING', 'PARTIAL', 'UNKNOWN')
                  AND version = %s
                RETURNING version
                """,
                (reason, plan_id, actor.tenant, actor.subject, expected_version),
            )
            if row is None:
                raise LeaseConflictError(f"Cannot mark plan {plan_id!r} uncertain: terminal status or version mismatch")
            return await self._read_with_conn(conn, plan_id, actor)
        except BaseException as exc:
            err = exc
            raise
        finally:
            await pool.release(conn, err)

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
            if any(s in {ApplyStatus.APPLIED, ApplyStatus.ALREADY_APPLIED} for s in completed):
                return PlanStatus.PARTIAL
            if ApplyStatus.UNKNOWN in completed:
                return PlanStatus.UNKNOWN
            if ApplyStatus.CONFLICT in completed:
                return PlanStatus.CONFLICT
            if ApplyStatus.RETRYABLE_NOT_APPLIED in completed:
                return PlanStatus.RETRYABLE_NOT_APPLIED
            if completed and all(s is ApplyStatus.REJECTED for s in completed):
                return PlanStatus.REJECTED
            return PlanStatus.EXECUTING
        return aggregate_plan_status(completed)

    @staticmethod
    def _rehydrate_plan(payload_raw: Any, status_raw: str) -> WritePlan | None:
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        if not isinstance(payload, dict) or payload.get("tool_name") == "legacy":
            return None
        target = payload["graph_target"]
        operations = tuple(
            OperationPlan(
                operation_id=op["operation_id"],
                kind=op["kind"],
                target=op["target"],
                expected_state=op["expected_state"],
                desired_state=op["desired_state"],
                depends_on=tuple(op.get("depends_on") or ()),
                idempotency_key=op.get("idempotency_key"),
            )
            for op in payload["operations"]
        )
        return WritePlan(
            plan_id=payload["plan_id"],
            tool_name=payload["tool_name"],
            graph_target=GraphTarget(
                graph_url=target["graph_url"],
                graph_name=target["graph_name"],
                graphspace=target.get("graphspace"),
            ),
            principal=payload["principal"],
            operations=operations,
            payload_digest=payload["payload_digest"],
            schema_fingerprint=payload["schema_fingerprint"],
            status=PlanStatus(status_raw),
            created_at=int(payload["created_at"]),
            expires_at=int(payload["expires_at"]),
        )

    async def get_full_plan(self, plan_id: str, actor: Actor) -> WritePlan | None:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            row = await conn.fetchone(
                """
                SELECT payload_json, status
                FROM write_plans
                WHERE plan_id = %s AND owner_tenant = %s AND owner_subject = %s
                """,
                (plan_id, actor.tenant, actor.subject),
            )
            if row is None:
                return None
            return self._rehydrate_plan(row["payload_json"], row["status"])
        finally:
            await pool.release(conn)

    async def get_full_plan_record(self, plan_id: str, actor: Actor) -> dict[str, Any] | None:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            row = await conn.fetchone(
                """
                SELECT plan_id, tool_name, payload_json, payload_digest, status,
                       lease_holder,
                       EXTRACT(EPOCH FROM lease_expires_at) AS lease_expires_at,
                       EXTRACT(EPOCH FROM confirmed_at) AS confirmed_at,
                       EXTRACT(EPOCH FROM expires_at) AS expires_at,
                       EXTRACT(EPOCH FROM created_at) AS created_at,
                       EXTRACT(EPOCH FROM updated_at) AS updated_at
                FROM write_plans
                WHERE plan_id = %s AND owner_tenant = %s AND owner_subject = %s
                """,
                (plan_id, actor.tenant, actor.subject),
            )
            if row is None:
                return None
            payload_raw = row["payload_json"]
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
            op_rows = await conn.fetchall(
                """
                SELECT operation_id, kind, status, attempt, reconciled, receipt_json
                FROM plan_operations
                WHERE plan_id = %s
                ORDER BY ordinal ASC, operation_id ASC
                """,
                (plan_id,),
            )
            operations = []
            for op_row in op_rows:
                receipt = op_row.get("receipt_json")
                if isinstance(receipt, str):
                    receipt = json.loads(receipt)
                operations.append(
                    {
                        "operation_id": op_row["operation_id"],
                        "kind": op_row["kind"],
                        "status": op_row.get("status") or PlanStatus.ISSUED.value,
                        "attempt": int(op_row.get("attempt") or 0),
                        "reconciled": bool(op_row.get("reconciled") or False),
                        "receipt": receipt,
                    }
                )
            return {
                "plan_id": row["plan_id"],
                "tool_name": row["tool_name"],
                "graph_target": payload.get("graph_target") if isinstance(payload, dict) else None,
                "principal": payload.get("principal") if isinstance(payload, dict) else None,
                "payload_digest": row["payload_digest"],
                "schema_fingerprint": payload.get("schema_fingerprint") if isinstance(payload, dict) else None,
                "status": row["status"],
                "created_at": int(payload["created_at"])
                if isinstance(payload, dict) and "created_at" in payload
                else int(row["created_at"] or 0),
                "expires_at": int(payload["expires_at"])
                if isinstance(payload, dict) and "expires_at" in payload
                else int(row["expires_at"] or 0),
                "confirmed_at": int(row["confirmed_at"]) if row.get("confirmed_at") is not None else None,
                "lease_owner": row.get("lease_holder"),
                "lease_expires_at": int(row["lease_expires_at"]) if row.get("lease_expires_at") is not None else None,
                "reconciliation_required": row["status"] in (PlanStatus.UNKNOWN.value, PlanStatus.LEGACY_UNKNOWN.value),
                "operations": operations,
            }
        finally:
            await pool.release(conn)

    async def list_plans(
        self,
        actor: Actor,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            params: list[Any] = [actor.tenant, actor.subject]
            status_clause = ""
            if status is not None:
                status_clause = "AND status = %s"
                params.append(status)
            params.append(limit)
            rows = await conn.fetchall(
                f"""
                SELECT plan_id, tool_name, status, graphspace, graph,
                       EXTRACT(EPOCH FROM created_at) AS created_at,
                       EXTRACT(EPOCH FROM expires_at) AS expires_at,
                       EXTRACT(EPOCH FROM confirmed_at) AS confirmed_at
                FROM write_plans
                WHERE owner_tenant = %s AND owner_subject = %s
                {status_clause}
                ORDER BY created_at DESC, plan_id DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return [
                {
                    "plan_id": r["plan_id"],
                    "tool_name": r["tool_name"],
                    "status": r["status"],
                    "graphspace": r.get("graphspace") or "DEFAULT",
                    "graph": r.get("graph") or "",
                    "created_at": int(r["created_at"] or 0),
                    "expires_at": int(r["expires_at"] or 0),
                    "confirmed_at": int(r["confirmed_at"]) if r.get("confirmed_at") is not None else None,
                }
                for r in rows
            ]
        finally:
            await pool.release(conn)

    async def transition_plan_status(
        self,
        plan_id: str,
        actor: Actor,
        *,
        expected: PlanStatus,
        target: PlanStatus,
        reason: str | None = None,
    ) -> None:
        if not can_transition(expected, target):
            raise PlanTransitionError(f"illegal transition: {expected} -> {target}")
        pool = self._require_pool()
        conn = await pool.acquire()
        err: BaseException | None = None
        try:
            if reason is not None:
                row = await conn.fetchone(
                    """
                    UPDATE write_plans
                    SET status = %s,
                        confirmed_at = CASE
                            WHEN %s = 'EXECUTING' THEN COALESCE(confirmed_at, NOW())
                            ELSE confirmed_at
                        END,
                        summary_json = jsonb_set(summary_json, '{transition_reason}', to_jsonb(%s::text), true),
                        version = version + 1,
                        updated_at = NOW()
                    WHERE plan_id = %s
                      AND owner_tenant = %s
                      AND owner_subject = %s
                      AND status = %s
                    RETURNING version
                    """,
                    (
                        target.value,
                        target.value,
                        reason,
                        plan_id,
                        actor.tenant,
                        actor.subject,
                        expected.value,
                    ),
                )
            else:
                row = await conn.fetchone(
                    """
                    UPDATE write_plans
                    SET status = %s,
                        confirmed_at = CASE
                            WHEN %s = 'EXECUTING' THEN COALESCE(confirmed_at, NOW())
                            ELSE confirmed_at
                        END,
                        version = version + 1,
                        updated_at = NOW()
                    WHERE plan_id = %s
                      AND owner_tenant = %s
                      AND owner_subject = %s
                      AND status = %s
                    RETURNING version
                    """,
                    (
                        target.value,
                        target.value,
                        plan_id,
                        actor.tenant,
                        actor.subject,
                        expected.value,
                    ),
                )
            if row is None:
                raise PlanTransitionError("plan status did not match expected state")
        except BaseException as exc:
            err = exc
            raise
        finally:
            await pool.release(conn, err)

    async def claim_plan_for_execution(
        self,
        plan_id: str,
        actor: Actor,
        *,
        owner_token: str | None = None,
        lease_seconds: int = 30,
        resume: bool = False,
    ) -> tuple[WritePlan, bool]:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        owner_token = owner_token or uuid.uuid4().hex
        pool = self._require_pool()
        conn = await pool.acquire()
        err: BaseException | None = None
        try:
            row = await conn.fetchone(
                """
                SELECT status, payload_json,
                       (lease_expires_at IS NULL OR lease_expires_at <= NOW()) AS lease_available
                FROM write_plans
                WHERE plan_id = %s AND owner_tenant = %s AND owner_subject = %s
                FOR UPDATE
                """,
                (plan_id, actor.tenant, actor.subject),
            )
            if row is None:
                raise PlanTransitionError("plan was not found")
            current = PlanStatus(row["status"])
            claimable = {PlanStatus.ISSUED}
            if resume:
                claimable.update({PlanStatus.RETRYABLE_NOT_APPLIED, PlanStatus.PARTIAL})
            claimed = False
            effective_status = current.value
            if current in claimable and bool(row["lease_available"]):
                target = PlanStatus.EXECUTING if current is not PlanStatus.PARTIAL else current
                updated = await conn.fetchone(
                    """
                    UPDATE write_plans
                    SET status = %s,
                        confirmed_at = COALESCE(confirmed_at, NOW()),
                        lease_holder = %s,
                        lease_expires_at = NOW() + make_interval(secs => %s),
                        fence = fence + 1,
                        version = version + 1,
                        updated_at = NOW()
                    WHERE plan_id = %s
                      AND owner_tenant = %s
                      AND owner_subject = %s
                      AND status = %s
                      AND (lease_expires_at IS NULL OR lease_expires_at <= NOW())
                    RETURNING status
                    """,
                    (
                        target.value,
                        owner_token,
                        float(lease_seconds),
                        plan_id,
                        actor.tenant,
                        actor.subject,
                        current.value,
                    ),
                )
                if updated is not None:
                    claimed = True
                    effective_status = updated["status"]
            plan = self._rehydrate_plan(row["payload_json"], effective_status)
            if plan is None:
                raise PlanTransitionError("plan is not canonically rehydratable")
            return plan, claimed
        except BaseException as exc:
            err = exc
            raise
        finally:
            await pool.release(conn, err)

    async def claim_operation(
        self,
        plan_id: str,
        operation_id: str,
        actor: Actor,
        *,
        owner_token: str | None = None,
        attempt_token: str | None = None,
        lease_seconds: int = 30,
    ) -> int:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        pool = self._require_pool()
        conn = await pool.acquire()
        err: BaseException | None = None
        try:
            plan_row = await conn.fetchone(
                """
                SELECT lease_holder, (lease_expires_at IS NOT NULL AND lease_expires_at > NOW()) AS lease_active
                FROM write_plans
                WHERE plan_id = %s AND owner_tenant = %s AND owner_subject = %s
                FOR UPDATE
                """,
                (plan_id, actor.tenant, actor.subject),
            )
            if plan_row is None or not bool(plan_row["lease_active"]):
                raise PlanTransitionError("executor lease is absent or expired")
            effective_owner = owner_token or str(plan_row["lease_holder"])
            if plan_row["lease_holder"] != effective_owner:
                raise PlanTransitionError("executor lease owner did not match")
            op_row = await conn.fetchone(
                """
                SELECT status, attempt
                FROM plan_operations
                WHERE plan_id = %s AND operation_id = %s
                FOR UPDATE
                """,
                (plan_id, operation_id),
            )
            if op_row is None or op_row["status"] not in {
                PlanStatus.ISSUED.value,
                PlanStatus.RETRYABLE_NOT_APPLIED.value,
            }:
                raise PlanTransitionError("operation is not claimable")
            attempt = int(op_row["attempt"]) + 1
            attempt_token = attempt_token or uuid.uuid4().hex
            await conn.execute(
                """
                UPDATE plan_operations
                SET status = %s,
                    attempt = %s,
                    attempt_token = %s,
                    reconciled = FALSE,
                    updated_at = NOW()
                WHERE plan_id = %s AND operation_id = %s
                """,
                (PlanStatus.EXECUTING.value, attempt, attempt_token, plan_id, operation_id),
            )
            renewed = await conn.fetchone(
                """
                UPDATE write_plans
                SET lease_expires_at = NOW() + make_interval(secs => %s),
                    updated_at = NOW()
                WHERE plan_id = %s
                  AND owner_tenant = %s
                  AND owner_subject = %s
                  AND lease_holder = %s
                  AND lease_expires_at > NOW()
                RETURNING plan_id
                """,
                (float(lease_seconds), plan_id, actor.tenant, actor.subject, effective_owner),
            )
            if renewed is None:
                raise PlanTransitionError("executor lease could not be renewed")
            return attempt
        except BaseException as exc:
            err = exc
            raise
        finally:
            await pool.release(conn, err)

    async def record_operation_receipt(
        self,
        receipt: ApplyReceipt,
        actor: Actor,
        *,
        owner_token: str | None = None,
        attempt_token: str | None = None,
    ) -> None:
        if not receipt.plan_id or not receipt.operation_id:
            raise ValueError("canonical receipt requires plan_id and operation_id")
        operation_status = PlanStatus(receipt.status.value)
        pool = self._require_pool()
        conn = await pool.acquire()
        err: BaseException | None = None
        try:
            op_row = await conn.fetchone(
                """
                SELECT o.status, o.attempt, o.attempt_token, p.lease_holder,
                       (p.lease_expires_at IS NOT NULL AND p.lease_expires_at > NOW()) AS lease_active
                FROM plan_operations o
                JOIN write_plans p ON p.plan_id = o.plan_id
                WHERE o.plan_id = %s AND o.operation_id = %s
                  AND p.owner_tenant = %s AND p.owner_subject = %s
                FOR UPDATE
                """,
                (receipt.plan_id, receipt.operation_id, actor.tenant, actor.subject),
            )
            if op_row is None:
                raise PlanTransitionError("operation receipt target was not found")
            effective_owner = owner_token or op_row["lease_holder"]
            effective_attempt_token = attempt_token or receipt.attempt_token or op_row["attempt_token"]
            if (
                op_row["status"] != PlanStatus.EXECUTING.value
                or int(op_row["attempt"]) != receipt.attempt
                or not effective_attempt_token
                or op_row["attempt_token"] != effective_attempt_token
                or op_row["lease_holder"] != effective_owner
                or not bool(op_row["lease_active"])
            ):
                raise PlanTransitionError("stale or unfenced operation receipt")

            updated = await conn.fetchone(
                """
                UPDATE plan_operations
                SET status = %s,
                    attempt = %s,
                    apply_status = %s,
                    receipt_json = %s::jsonb,
                    recorded_at = NOW(),
                    updated_at = NOW()
                WHERE plan_id = %s AND operation_id = %s AND status = %s
                  AND attempt = %s AND attempt_token = %s
                RETURNING operation_id
                """,
                (
                    operation_status.value,
                    receipt.attempt,
                    receipt.status.value,
                    json.dumps(receipt.to_dict()),
                    receipt.plan_id,
                    receipt.operation_id,
                    PlanStatus.EXECUTING.value,
                    receipt.attempt,
                    effective_attempt_token,
                ),
            )
            if updated is None:
                raise PlanTransitionError("operation receipt target was not found")

            status_rows = await conn.fetchall(
                "SELECT status FROM plan_operations WHERE plan_id = %s ORDER BY ordinal ASC, operation_id ASC",
                (receipt.plan_id,),
            )
            aggregate = self._aggregate_persisted_statuses([str(r["status"]) for r in status_rows])
            plan_row = await conn.fetchone(
                "SELECT status, graphspace, graph, payload_json, version "
                "FROM write_plans WHERE plan_id = %s FOR UPDATE",
                (receipt.plan_id,),
            )
            if plan_row is None:
                raise PlanTransitionError("receipt plan was not found")
            current = PlanStatus(plan_row["status"])
            if current is not aggregate and not can_transition(current, aggregate):
                raise PlanTransitionError(f"illegal receipt transition: {current} -> {aggregate}")
            keep_lease = receipt.status in {
                ApplyStatus.APPLIED,
                ApplyStatus.ALREADY_APPLIED,
            } and aggregate in {PlanStatus.EXECUTING, PlanStatus.PARTIAL}
            await conn.execute(
                """
                UPDATE write_plans
                SET status = %s,
                    lease_holder = CASE WHEN %s THEN lease_holder ELSE NULL END,
                    lease_expires_at = CASE WHEN %s THEN lease_expires_at ELSE NULL END,
                    version = version + 1,
                    updated_at = NOW()
                WHERE plan_id = %s
                """,
                (aggregate.value, keep_lease, keep_lease, receipt.plan_id),
            )
            if aggregate in {PlanStatus.APPLIED, PlanStatus.PARTIAL, PlanStatus.UNKNOWN}:
                from hugegraph_mcp.events import ResourceEvent
                from hugegraph_mcp.resource_uri import build_graph_resource_uri

                raw_payload = plan_row.get("payload_json")
                if isinstance(raw_payload, str):
                    try:
                        raw_payload = json.loads(raw_payload)
                    except json.JSONDecodeError:
                        raw_payload = {}
                target_meta = raw_payload.get("graph_target") if isinstance(raw_payload, dict) else {}
                deployment = str((target_meta or {}).get("deployment_id") or self._deployment_id)
                graphspace = str(plan_row.get("graphspace") or "DEFAULT")
                graph = str(plan_row.get("graph") or "hugegraph")
                event_kind = "invalidated" if aggregate in {PlanStatus.PARTIAL, PlanStatus.UNKNOWN} else "updated"
                resource_version = int(time.time() * 1000)
                for res_kind in ("schema", "summary"):
                    event = ResourceEvent.create(
                        deployment=deployment,
                        graphspace=graphspace,
                        graph=graph,
                        uri=build_graph_resource_uri(deployment, graphspace, graph, res_kind),  # type: ignore[arg-type]
                        kind=event_kind,  # type: ignore[arg-type]
                        resource_version=resource_version,
                    )
                    await conn.execute(
                        """
                        INSERT INTO event_outbox (
                            event_id, deployment, graphspace, graph, uri, kind, resource_version
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (
                            event.event_id,
                            event.deployment,
                            event.graphspace,
                            event.graph,
                            event.uri,
                            event.kind,
                            event.resource_version,
                        ),
                    )
        except BaseException as exc:
            err = exc
            raise
        finally:
            await pool.release(conn, err)

    async def begin_reconcile(self, plan_id: str, actor: Actor) -> WritePlan:
        pool = self._require_pool()
        conn = await pool.acquire()
        err: BaseException | None = None
        try:
            row = await conn.fetchone(
                """
                SELECT status, payload_json,
                       (lease_expires_at IS NOT NULL AND lease_expires_at > NOW()) AS lease_active
                FROM write_plans
                WHERE plan_id = %s AND owner_tenant = %s AND owner_subject = %s
                FOR UPDATE
                """,
                (plan_id, actor.tenant, actor.subject),
            )
            if row is None:
                raise PlanTransitionError("plan was not found")
            if bool(row["lease_active"]):
                raise PlanTransitionError("execution lease is still active")
            status = PlanStatus(row["status"])
            effective_status = status.value
            if status is PlanStatus.EXECUTING:
                await conn.execute(
                    """
                    UPDATE write_plans
                    SET status = %s, lease_holder = NULL, lease_expires_at = NULL,
                        version = version + 1, updated_at = NOW()
                    WHERE plan_id = %s AND status = %s
                      AND (lease_expires_at IS NULL OR lease_expires_at <= NOW())
                    """,
                    (PlanStatus.UNKNOWN.value, plan_id, PlanStatus.EXECUTING.value),
                )
                effective_status = PlanStatus.UNKNOWN.value
            elif status in {PlanStatus.UNKNOWN, PlanStatus.LEGACY_UNKNOWN, PlanStatus.PARTIAL}:
                await conn.execute(
                    """
                    UPDATE write_plans
                    SET lease_holder = NULL, lease_expires_at = NULL, updated_at = NOW()
                    WHERE plan_id = %s
                    """,
                    (plan_id,),
                )
            plan = self._rehydrate_plan(row["payload_json"], effective_status)
            if plan is None:
                raise PlanTransitionError("plan is not canonically rehydratable")
            return plan
        except BaseException as exc:
            err = exc
            raise
        finally:
            await pool.release(conn, err)

    async def record_reconciliation_receipt(self, receipt: ApplyReceipt, actor: Actor) -> None:
        if not receipt.plan_id or not receipt.operation_id:
            raise ValueError("canonical receipt requires plan_id and operation_id")
        pool = self._require_pool()
        conn = await pool.acquire()
        err: BaseException | None = None
        try:
            plan_row = await conn.fetchone(
                """
                SELECT lease_holder
                FROM write_plans
                WHERE plan_id = %s AND owner_tenant = %s AND owner_subject = %s
                FOR UPDATE
                """,
                (receipt.plan_id, actor.tenant, actor.subject),
            )
            if plan_row is None or plan_row["lease_holder"] is not None:
                raise PlanTransitionError("reconciliation requires a fenced executor")
            updated = await conn.fetchone(
                """
                UPDATE plan_operations
                SET status = %s,
                    apply_status = %s,
                    receipt_json = %s::jsonb,
                    reconciled = TRUE,
                    recorded_at = NOW(),
                    updated_at = NOW()
                WHERE plan_id = %s AND operation_id = %s
                  AND status IN ('ISSUED', 'EXECUTING', 'UNKNOWN', 'LEGACY_UNKNOWN')
                RETURNING operation_id
                """,
                (
                    receipt.status.value,
                    receipt.status.value,
                    json.dumps(receipt.to_dict()),
                    receipt.plan_id,
                    receipt.operation_id,
                ),
            )
            if updated is None:
                raise PlanTransitionError("operation is not reconcilable")
            status_rows = await conn.fetchall(
                "SELECT status FROM plan_operations WHERE plan_id = %s ORDER BY ordinal ASC, operation_id ASC",
                (receipt.plan_id,),
            )
            aggregate = self._aggregate_persisted_statuses([str(r["status"]) for r in status_rows])
            await conn.execute(
                """
                UPDATE write_plans
                SET status = %s, version = version + 1, updated_at = NOW()
                WHERE plan_id = %s
                """,
                (aggregate.value, receipt.plan_id),
            )
        except BaseException as exc:
            err = exc
            raise
        finally:
            await pool.release(conn, err)

    async def check_ready(self) -> None:
        pool = self._require_pool()
        conn = await pool.acquire()
        try:
            await conn.fetchone("SELECT 1 AS ok")
        finally:
            await pool.release(conn)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()


def _create_psycopg_pool(dsn: str) -> AsyncDBPool:
    """Lazily construct a psycopg_pool AsyncConnectionPool if installed."""
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
    except ImportError as exc:  # pragma: no cover - optional driver
        raise PlanStoreUnavailableError(
            "PostgreSQL backend requires 'psycopg[binary]' and 'psycopg_pool' to be installed."
        ) from exc

    raw_pool = AsyncConnectionPool(conninfo=dsn, kwargs={"row_factory": dict_row}, open=False)

    class _PsycopgConnectionWrapper:
        def __init__(self, raw_conn: Any, ctx: Any, tx_ctx: Any) -> None:
            self._raw = raw_conn
            self._ctx = ctx
            self._tx_ctx = tx_ctx

        async def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
            return await self._raw.execute(query, params)

        async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
            async with self._raw.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchone()

        async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
            async with self._raw.cursor() as cur:
                await cur.execute(query, params)
                return list(await cur.fetchall())

    class _PsycopgPoolAdapter:
        async def acquire(self) -> AsyncDBConnection:
            if not raw_pool._opened:
                await raw_pool.open()
            ctx = raw_pool.connection()
            raw_conn = await ctx.__aenter__()
            tx_ctx = raw_conn.transaction()
            await tx_ctx.__aenter__()
            return _PsycopgConnectionWrapper(raw_conn, ctx, tx_ctx)

        async def release(self, conn: AsyncDBConnection, exc: BaseException | None = None) -> None:
            tx_ctx = getattr(conn, "_tx_ctx", None)
            ctx = getattr(conn, "_ctx", None)
            exc_type = type(exc) if exc is not None else None
            exc_tb = exc.__traceback__ if exc is not None else None
            try:
                if tx_ctx is not None:
                    await tx_ctx.__aexit__(exc_type, exc, exc_tb)
            finally:
                if ctx is not None:
                    await ctx.__aexit__(exc_type, exc, exc_tb)

        async def close(self) -> None:
            await raw_pool.close()

    return _PsycopgPoolAdapter()


class PostgresSyncPlanStore:
    """Synchronous PlanStore bridge delegating to PostgresPlanStore for WriteExecutor/WriteReconciler."""

    def __init__(
        self,
        pg_store: PostgresPlanStore,
        *,
        actor: Actor,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._pg_store = pg_store
        self._actor = actor
        self._loop = loop

    def _run(self, fn):
        if self._loop is not None and self._loop.is_running():
            return asyncio.run_coroutine_threadsafe(fn(self._pg_store), self._loop).result()

        async def _ephemeral():
            if self._pg_store._pool is not None:
                return await fn(self._pg_store)
            temp_store = PostgresPlanStore(self._pg_store._dsn)
            try:
                await temp_store.prepare()
                return await fn(temp_store)
            finally:
                await temp_store.close()

        import sys

        if sys.platform == "win32":
            return asyncio.run(_ephemeral(), loop_factory=asyncio.SelectorEventLoop)
        return asyncio.run(_ephemeral())

    def prepare(self) -> None:
        self._run(lambda s: s.prepare())

    def save_plan(self, plan: WritePlan) -> None:
        self._run(lambda s: s.create(plan, self._actor))

    def get_plan(self, plan_id: str) -> WritePlan | None:
        return self._run(lambda s: s.get_full_plan(plan_id, self._actor))

    def get_plan_record(self, plan_id: str) -> dict[str, Any] | None:
        return self._run(lambda s: s.get_full_plan_record(plan_id, self._actor))

    def transition_plan(
        self,
        plan_id: str,
        *,
        expected: PlanStatus,
        target: PlanStatus,
        reason: str | None = None,
    ) -> None:
        self._run(
            lambda s: s.transition_plan_status(
                plan_id,
                self._actor,
                expected=expected,
                target=target,
                reason=reason,
            )
        )

    def claim_plan(
        self,
        plan_id: str,
        *,
        owner_token: str | None = None,
        lease_seconds: int = 30,
        resume: bool = False,
    ) -> tuple[WritePlan, bool]:
        return self._run(
            lambda s: s.claim_plan_for_execution(
                plan_id,
                self._actor,
                owner_token=owner_token,
                lease_seconds=lease_seconds,
                resume=resume,
            )
        )

    def claim_operation(
        self,
        plan_id: str,
        operation_id: str,
        *,
        owner_token: str | None = None,
        attempt_token: str | None = None,
        lease_seconds: int = 30,
    ) -> int:
        return self._run(
            lambda s: s.claim_operation(
                plan_id,
                operation_id,
                self._actor,
                owner_token=owner_token,
                attempt_token=attempt_token,
                lease_seconds=lease_seconds,
            )
        )

    def record_receipt(
        self,
        receipt: ApplyReceipt,
        *,
        owner_token: str | None = None,
        attempt_token: str | None = None,
    ) -> None:
        self._run(
            lambda s: s.record_operation_receipt(
                receipt,
                self._actor,
                owner_token=owner_token,
                attempt_token=attempt_token,
            )
        )

    def begin_reconcile(self, plan_id: str) -> WritePlan:
        return self._run(lambda s: s.begin_reconcile(plan_id, self._actor))

    def list_plans(self, *, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return self._run(lambda s: s.list_plans(self._actor, status=status, limit=limit))

    def record_reconciliation_receipt(self, receipt: ApplyReceipt) -> None:
        self._run(lambda s: s.record_reconciliation_receipt(receipt, self._actor))
