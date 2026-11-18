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

"""Runtime dependency container, FastMCP lifespan, and request Actor context."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.events import EventBus, InMemoryEventBus, OutboxEventRelay, OutboxSource
from hugegraph_mcp.notifications import SubscriptionManager
from hugegraph_mcp.plan_store import SQLitePlanStore
from hugegraph_mcp.stores.base import (
    Actor,
    AsyncPlanStore,
    SyncToAsyncPlanStoreAdapter,
    default_stdio_actor,
)
from hugegraph_mcp.stores.postgres import PostgresPlanStore

_CURRENT_RUNTIME: contextvars.ContextVar[RuntimeContainer | None] = contextvars.ContextVar(
    "hugegraph_mcp_runtime",
    default=None,
)
_CURRENT_ACTOR: contextvars.ContextVar[Actor | None] = contextvars.ContextVar(
    "hugegraph_mcp_actor",
    default=None,
)
_ACTIVE_RUNTIME: RuntimeContainer | None = None


@dataclass
class ResourceCache:
    """In-memory bounded cache keyed by (deployment, graphspace, graph, kind, principal_scope)."""

    schema_ttl_s: float = 30.0
    summary_ttl_s: float = 10.0
    embeddings_ttl_s: float = 10.0
    _entries: dict[tuple[str, str, str, str, str], tuple[float, str | None, dict[str, Any]]] = field(
        default_factory=dict
    )

    def get(
        self,
        key: tuple[str, str, str, str, str],
        *,
        now: float,
        ttl_s: float,
        expected_fingerprint: str | None = None,
    ) -> dict[str, Any] | None:
        item = self._entries.get(key)
        if item is None:
            return None
        stored_at, fingerprint, payload = item
        if now - stored_at > ttl_s:
            self._entries.pop(key, None)
            return None
        if expected_fingerprint is not None and fingerprint != expected_fingerprint:
            self._entries.pop(key, None)
            return None
        return payload

    def set(
        self,
        key: tuple[str, str, str, str, str],
        payload: dict[str, Any],
        *,
        now: float,
        fingerprint: str | None = None,
    ) -> None:
        self._entries[key] = (now, fingerprint, payload)

    def invalidate_graph(self, deployment: str, graphspace: str, graph: str) -> int:
        to_delete = [key for key in self._entries if key[0] == deployment and key[1] == graphspace and key[2] == graph]
        for key in to_delete:
            self._entries.pop(key, None)
        return len(to_delete)

    def clear(self) -> None:
        self._entries.clear()


@dataclass
class RuntimeContainer:
    config: MCPConfig
    plan_store: AsyncPlanStore
    event_bus: EventBus
    resource_cache: ResourceCache = field(default_factory=ResourceCache)
    subscription_manager: SubscriptionManager = field(default_factory=SubscriptionManager)
    outbox_relay: OutboxEventRelay | None = None
    ready: bool = False
    shutting_down: bool = False
    _inflight_writes: int = 0
    _drain_event: asyncio.Event = field(default_factory=asyncio.Event)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._drain_event.set()

    def begin_write(self) -> None:
        if self.shutting_down:
            raise RuntimeError("Server is shutting down; new writes are rejected")
        self._inflight_writes += 1
        self._drain_event.clear()

    def end_write(self) -> None:
        if self._inflight_writes > 0:
            self._inflight_writes -= 1
        if self._inflight_writes == 0:
            self._drain_event.set()

    async def drain_writes(self, timeout_s: float = 10.0) -> bool:
        self.shutting_down = True
        self.ready = False
        if self._inflight_writes == 0:
            return True
        try:
            await asyncio.wait_for(self._drain_event.wait(), timeout=timeout_s)
            return True
        except TimeoutError:
            return False

    async def check_ready(self) -> tuple[bool, dict[str, str]]:
        if self.shutting_down or not self.ready:
            return False, {"runtime": "not_ready"}
        checks: dict[str, str] = {}
        try:
            await self.plan_store.check_ready()
            checks["plan_store"] = "ok"
        except Exception as exc:
            checks["plan_store"] = f"error: {exc!s}"
            return False, checks
        try:
            await self.event_bus.check_ready()
            checks["event_bus"] = "ok"
        except Exception as exc:
            checks["event_bus"] = f"error: {exc!s}"
            return False, checks
        return True, checks


def build_runtime(config: MCPConfig | None = None) -> RuntimeContainer:
    cfg = config or MCPConfig.from_env()
    event_bus = InMemoryEventBus()
    if cfg.plan_store_backend == "postgres" and cfg.plan_store_dsn:
        plan_store: AsyncPlanStore = PostgresPlanStore(
            cfg.plan_store_dsn,
            deployment_id=cfg.deployment_id,
        )
    else:
        sync_store = SQLitePlanStore.from_config(cfg)
        plan_store = SyncToAsyncPlanStoreAdapter(sync_store, event_bus=event_bus)
    return RuntimeContainer(
        config=cfg,
        plan_store=plan_store,
        event_bus=event_bus,
    )


def create_runtime_lifespan(config: MCPConfig | None = None):
    """Create a FastMCP lifespan context manager bound to an immutable MCPConfig."""

    async def _fanout_events(runtime: RuntimeContainer) -> None:
        async for event in runtime.event_bus.subscribe():
            try:
                runtime.resource_cache.invalidate_graph(
                    event.deployment,
                    event.graphspace,
                    event.graph,
                )
                await runtime.subscription_manager.dispatch(event)
            except Exception:
                # Never let a single failing subscriber callback terminate event fan-out.
                continue

    @asynccontextmanager
    async def _lifespan(server: Any) -> AsyncIterator[RuntimeContainer]:
        global _ACTIVE_RUNTIME
        runtime = build_runtime(config)
        _ACTIVE_RUNTIME = runtime
        if server is not None:
            with contextlib.suppress(Exception):
                server._hugegraph_runtime = runtime
        token = _CURRENT_RUNTIME.set(runtime)
        actor_token = _CURRENT_ACTOR.set(default_stdio_actor())
        fanout_task: asyncio.Task[None] | None = None
        try:
            runtime._loop = asyncio.get_running_loop()
            if hasattr(runtime.plan_store, "prepare"):
                await runtime.plan_store.prepare()  # type: ignore[attr-defined]
            await runtime.plan_store.check_ready()
            fanout_task = asyncio.create_task(_fanout_events(runtime))
            await asyncio.sleep(0)
            if isinstance(runtime.plan_store, OutboxSource):
                runtime.outbox_relay = OutboxEventRelay(
                    runtime.plan_store,
                    runtime.event_bus,
                )
                runtime.outbox_relay.start()
            runtime.ready = True
            yield runtime
        finally:
            if runtime.outbox_relay is not None:
                with contextlib.suppress(Exception):
                    await runtime.outbox_relay.stop()
                runtime.outbox_relay = None
            await runtime.drain_writes(timeout_s=5.0)
            await runtime.event_bus.close()
            if fanout_task is not None:
                if not fanout_task.done():
                    fanout_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await fanout_task
            await runtime.plan_store.close()
            runtime._loop = None
            _CURRENT_ACTOR.reset(actor_token)
            _CURRENT_RUNTIME.reset(token)
            if server is not None:
                try:
                    if getattr(server, "_hugegraph_runtime", None) is runtime:
                        delattr(server, "_hugegraph_runtime")
                except Exception:
                    pass
            if _ACTIVE_RUNTIME is runtime:
                _ACTIVE_RUNTIME = None

    return _lifespan


def get_current_runtime() -> RuntimeContainer | None:
    return _CURRENT_RUNTIME.get() or _ACTIVE_RUNTIME


def set_current_runtime(
    runtime: RuntimeContainer | None,
) -> contextvars.Token[RuntimeContainer | None]:
    return _CURRENT_RUNTIME.set(runtime)


def reset_current_runtime(token: contextvars.Token[RuntimeContainer | None]) -> None:
    _CURRENT_RUNTIME.reset(token)


def get_current_actor() -> Actor:
    return _CURRENT_ACTOR.get() or default_stdio_actor()


def set_current_actor(actor: Actor) -> contextvars.Token[Actor | None]:
    return _CURRENT_ACTOR.set(actor)


def reset_current_actor(token: contextvars.Token[Actor | None]) -> None:
    _CURRENT_ACTOR.reset(token)


@dataclass(frozen=True)
class VerifiedClaims:
    issuer: str
    tenant: str
    subject: str
    scopes: frozenset[str] = frozenset({"mcp:read"})


def anonymous_readonly_actor() -> Actor:
    """Fail-closed anonymous identity with no write privileges."""
    return Actor(
        issuer="anonymous",
        tenant="anonymous",
        subject="anonymous",
        scopes=frozenset({"mcp:read"}),
        is_anonymous=True,
    )


def actor_from_claims(claims: VerifiedClaims | None) -> Actor:
    """Construct an Actor strictly from verifier-validated claims (never raw client headers)."""
    if claims is None:
        return anonymous_readonly_actor()
    return Actor(
        issuer=claims.issuer,
        tenant=claims.tenant,
        subject=claims.subject,
        scopes=claims.scopes,
        is_anonymous=False,
    )
