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

"""Asynchronous PlanStore protocol, Actor identity, and SQLite adapter."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

from hugegraph_mcp.events import EventBus, ResourceEvent
from hugegraph_mcp.plan_store import PlanStore, PlanTransitionError
from hugegraph_mcp.write_plan import ApplyReceipt, PlanStatus, WritePlan


class PlanNotFoundError(LookupError):
    """Raised when a plan does not exist or is not visible to the requesting actor."""


class ActorAuthorizationError(PermissionError):
    """Raised when an actor attempts to access or mutate another principal's plan."""


class LeaseConflictError(RuntimeError):
    """Raised when a plan lease is already held, expired, or fenced out."""


@dataclass(frozen=True)
class Actor:
    issuer: str
    tenant: str
    subject: str
    scopes: frozenset[str] = frozenset()
    is_anonymous: bool = False

    @property
    def principal_key(self) -> str:
        return json.dumps([self.tenant, self.subject], separators=(",", ":"))


def default_stdio_actor() -> Actor:
    return Actor(
        issuer="local-stdio",
        tenant="default",
        subject="local-operator",
        scopes=frozenset({"mcp:read", "mcp:write"}),
        is_anonymous=False,
    )


@dataclass(frozen=True)
class Lease:
    plan_id: str
    holder: str
    fence: int
    expires_at: float
    plan_version: int


@dataclass(frozen=True)
class PlanOutcome:
    status: PlanStatus
    summary: dict[str, Any]


@dataclass(frozen=True)
class PlanView:
    plan_id: str
    tool_name: str
    status: PlanStatus
    owner_tenant: str
    owner_subject: str
    graphspace: str | None
    graph: str
    expires_at: float
    version: int
    operations: tuple[dict[str, Any], ...]
    receipts: tuple[dict[str, Any], ...]
    summary: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "target": {
                "graphspace": self.graphspace or "DEFAULT",
                "graph": self.graph,
            },
            "expires_at": self.expires_at,
            "version": self.version,
            "operations": list(self.operations),
            "receipts": list(self.receipts),
            "summary": dict(self.summary),
        }


@runtime_checkable
class AsyncPlanStore(Protocol):
    async def create(self, plan: WritePlan, actor: Actor) -> PlanView: ...

    async def read(self, plan_id: str, actor: Actor) -> PlanView: ...

    async def claim(
        self,
        plan_id: str,
        actor: Actor,
        holder: str,
        ttl_s: int = 30,
    ) -> Lease: ...

    async def renew(self, lease: Lease, actor: Actor, ttl_s: int = 30) -> Lease: ...

    async def record_operation(
        self,
        lease: Lease,
        actor: Actor,
        operation_id: str,
        expected_version: int,
        receipt: ApplyReceipt,
    ) -> PlanView: ...

    async def finish(
        self,
        lease: Lease,
        actor: Actor,
        expected_version: int,
        outcome: PlanOutcome,
        events: tuple[ResourceEvent, ...] = (),
    ) -> PlanView: ...

    async def mark_uncertain(
        self,
        plan_id: str,
        actor: Actor,
        expected_version: int,
        reason: str,
    ) -> PlanView: ...

    async def check_ready(self) -> None: ...

    async def close(self) -> None: ...


class SyncToAsyncPlanStoreAdapter:
    """AsyncPlanStore adapter wrapping a synchronous SQLitePlanStore."""

    def __init__(
        self,
        sync_store: PlanStore,
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._sync_store = sync_store
        self._event_bus = event_bus
        self._lock = asyncio.Lock()
        self._versions: dict[str, int] = {}
        self._fences: dict[str, int] = {}

    async def create(self, plan: WritePlan, actor: Actor) -> PlanView:
        async with self._lock:
            await asyncio.to_thread(
                self._sync_store.save_plan,
                plan,
                owner_principal=actor.principal_key,
            )
            self._versions[plan.plan_id] = 1
            return await self._read_unlocked(plan.plan_id, actor)

    async def read(self, plan_id: str, actor: Actor) -> PlanView:
        async with self._lock:
            return await self._read_unlocked(plan_id, actor)

    async def _read_unlocked(self, plan_id: str, actor: Actor) -> PlanView:
        record = await asyncio.to_thread(self._sync_store.get_plan_record, plan_id)
        if record is None:
            raise PlanNotFoundError(f"Write plan {plan_id!r} not found")
        owner = str(record.get("owner_principal") or "")
        if actor.issuer == "local-stdio":
            if owner not in {"", actor.principal_key}:
                # Return PlanNotFoundError to avoid leaking plan existence across principals.
                raise PlanNotFoundError(f"Write plan {plan_id!r} not found")
        elif owner != actor.principal_key:
            # Return PlanNotFoundError to avoid leaking plan existence across principals.
            raise PlanNotFoundError(f"Write plan {plan_id!r} not found")
        plan = await asyncio.to_thread(self._sync_store.get_plan, plan_id)
        if plan is None:
            raise PlanNotFoundError(f"Write plan {plan_id!r} not found")
        version = self._versions.get(plan_id, 1)
        receipts = tuple(record.get("receipts") or ())
        if not receipts:
            receipts = tuple(
                op["receipt"]
                for op in (record.get("operations") or ())
                if isinstance(op, dict) and op.get("receipt") is not None
            )
        operations = tuple(
            {
                "operation_id": op.operation_id,
                "kind": op.kind,
                "target": dict(op.target),
            }
            for op in plan.operations
        )
        return PlanView(
            plan_id=plan.plan_id,
            tool_name=plan.tool_name,
            status=plan.status,
            owner_tenant=actor.tenant,
            owner_subject=actor.subject,
            graphspace=plan.graph_target.graphspace,
            graph=plan.graph_target.graph_name,
            expires_at=plan.expires_at,
            version=version,
            operations=operations,
            receipts=receipts,
            summary={"operation_count": len(operations), "status": plan.status.value},
        )

    async def claim(
        self,
        plan_id: str,
        actor: Actor,
        holder: str,
        ttl_s: int = 30,
    ) -> Lease:
        async with self._lock:
            view = await self._read_unlocked(plan_id, actor)
            owner_token = f"{holder}:{uuid.uuid4().hex[:8]}"
            try:
                claimed_plan, is_new = await asyncio.to_thread(
                    self._sync_store.claim_plan,
                    plan_id,
                    owner_token=owner_token,
                    lease_seconds=ttl_s,
                    resume=False,
                )
            except PlanTransitionError as exc:
                raise LeaseConflictError(str(exc)) from exc
            if not is_new:
                raise LeaseConflictError(f"Plan {plan_id!r} cannot be claimed (status={claimed_plan.status.value})")
            fence = self._fences.get(plan_id, 0) + 1
            version = self._versions.get(plan_id, view.version) + 1
            self._fences[plan_id] = fence
            self._versions[plan_id] = version
            return Lease(
                plan_id=plan_id,
                holder=owner_token,
                fence=fence,
                expires_at=time.time() + ttl_s,
                plan_version=version,
            )

    async def renew(self, lease: Lease, actor: Actor, ttl_s: int = 30) -> Lease:
        async with self._lock:
            await self._read_unlocked(lease.plan_id, actor)
            if self._fences.get(lease.plan_id) != lease.fence:
                raise LeaseConflictError(f"Lease fenced out for plan {lease.plan_id!r}")
            if time.time() > lease.expires_at:
                raise LeaseConflictError(f"Lease expired for plan {lease.plan_id!r}")
            return replace(lease, expires_at=time.time() + ttl_s)

    async def record_operation(
        self,
        lease: Lease,
        actor: Actor,
        operation_id: str,
        expected_version: int,
        receipt: ApplyReceipt,
    ) -> PlanView:
        async with self._lock:
            await self._read_unlocked(lease.plan_id, actor)
            current_version = self._versions.get(lease.plan_id, 1)
            if current_version != expected_version or self._fences.get(lease.plan_id) != lease.fence:
                raise LeaseConflictError(f"Stale version/fence for plan {lease.plan_id!r}")
            attempt_token = receipt.attempt_token or f"att_{uuid.uuid4().hex[:12]}"
            try:
                attempt = await asyncio.to_thread(
                    self._sync_store.claim_operation,
                    lease.plan_id,
                    operation_id,
                    owner_token=lease.holder,
                    attempt_token=attempt_token,
                    lease_seconds=30,
                )
                bound_receipt = replace(receipt, attempt=attempt, attempt_token=attempt_token)
                await asyncio.to_thread(
                    self._sync_store.record_receipt,
                    bound_receipt,
                    owner_token=lease.holder,
                    attempt_token=attempt_token,
                )
            except PlanTransitionError as exc:
                raise LeaseConflictError(str(exc)) from exc
            self._versions[lease.plan_id] = current_version + 1
            return await self._read_unlocked(lease.plan_id, actor)

    async def finish(
        self,
        lease: Lease,
        actor: Actor,
        expected_version: int,
        outcome: PlanOutcome,
        events: tuple[ResourceEvent, ...] = (),
    ) -> PlanView:
        async with self._lock:
            view = await self._read_unlocked(lease.plan_id, actor)
            current_version = self._versions.get(lease.plan_id, 1)
            if current_version != expected_version or self._fences.get(lease.plan_id) != lease.fence:
                raise LeaseConflictError(f"Stale version/fence for plan {lease.plan_id!r}")
            if view.status != outcome.status:
                try:
                    await asyncio.to_thread(
                        self._sync_store.transition_plan,
                        lease.plan_id,
                        expected=PlanStatus.EXECUTING,
                        target=outcome.status,
                    )
                except PlanTransitionError as exc:
                    raise LeaseConflictError(str(exc)) from exc
            self._versions[lease.plan_id] = current_version + 1
            view = await self._read_unlocked(lease.plan_id, actor)
        if self._event_bus is not None:
            for event in events:
                await self._event_bus.publish(event)
        return view

    async def mark_uncertain(
        self,
        plan_id: str,
        actor: Actor,
        expected_version: int,
        reason: str,
    ) -> PlanView:
        async with self._lock:
            view = await self._read_unlocked(plan_id, actor)
            current_version = self._versions.get(plan_id, view.version)
            if current_version != expected_version:
                raise LeaseConflictError(f"Version mismatch for plan {plan_id!r}")
            try:
                await asyncio.to_thread(
                    self._sync_store.transition_plan,
                    plan_id,
                    expected=view.status,
                    target=PlanStatus.UNKNOWN,
                )
            except PlanTransitionError as exc:
                raise LeaseConflictError(str(exc)) from exc
            self._versions[plan_id] = current_version + 1
            return await self._read_unlocked(plan_id, actor)

    async def check_ready(self) -> None:
        await asyncio.to_thread(self._sync_store.prepare)

    async def close(self) -> None:
        return None
