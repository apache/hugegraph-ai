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

"""Resource change events and in-memory / outbox event bus abstractions."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

EventKind = Literal["updated", "invalidated", "list_changed"]


@dataclass(frozen=True)
class ResourceEvent:
    event_id: str
    deployment: str
    graphspace: str
    graph: str
    uri: str
    kind: EventKind
    resource_version: int
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        deployment: str,
        graphspace: str,
        graph: str,
        uri: str,
        kind: EventKind = "updated",
        resource_version: int = 1,
    ) -> ResourceEvent:
        return cls(
            event_id=f"evt_{uuid.uuid4().hex}",
            deployment=deployment,
            graphspace=graphspace,
            graph=graph,
            uri=uri,
            kind=kind,
            resource_version=resource_version,
        )


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: ResourceEvent) -> None: ...

    def subscribe(self) -> AsyncIterator[ResourceEvent]: ...

    async def check_ready(self) -> None: ...

    async def close(self) -> None: ...


class InMemoryEventBus:
    """Single-process fan-out event bus with independent per-subscriber queues."""

    def __init__(self, *, max_history: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[ResourceEvent | None]] = set()
        self._history: deque[ResourceEvent] = deque(maxlen=max_history)
        self._closed = False

    async def publish(self, event: ResourceEvent) -> None:
        if self._closed:
            return
        self._history.append(event)
        for queue in tuple(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[ResourceEvent]:
        queue: asyncio.Queue[ResourceEvent | None] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        try:
            while not self._closed:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._subscribers.discard(queue)

    def recent_events(self) -> list[ResourceEvent]:
        return list(self._history)

    async def check_ready(self) -> None:
        if self._closed:
            raise RuntimeError("InMemoryEventBus is closed")

    async def close(self) -> None:
        self._closed = True
        for queue in tuple(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)
        self._subscribers.clear()


@runtime_checkable
class OutboxSource(Protocol):
    async def fetch_outbox_since(self, after_seq: int, *, limit: int = 100) -> list[tuple[int, ResourceEvent]]: ...


class OutboxEventRelay:
    """Per-instance independent cursor relay from PostgreSQL event_outbox to local EventBus."""

    def __init__(
        self,
        source: OutboxSource,
        event_bus: EventBus,
        *,
        poll_interval_s: float = 0.5,
        initial_seq: int = 0,
    ) -> None:
        self._source = source
        self._event_bus = event_bus
        self._poll_interval_s = poll_interval_s
        self._last_seq = initial_seq
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def last_seq(self) -> int:
        return self._last_seq

    async def poll_once(self, *, limit: int = 100) -> int:
        rows = await self._source.fetch_outbox_since(self._last_seq, limit=limit)
        dispatched = 0
        for seq, event in rows:
            if seq > self._last_seq:
                await self._event_bus.publish(event)
                self._last_seq = seq
                dispatched += 1
        return dispatched

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                await self.poll_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_s)
            except TimeoutError:
                continue

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
