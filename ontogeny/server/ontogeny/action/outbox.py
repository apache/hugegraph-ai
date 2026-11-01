# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and
# limitations under the License.

"""Transactional-outbox dispatcher: the ONLY bridge from committed state to
the outside world (webhooks, projection worker, SSE subscribers).

Each consumer acknowledges events individually; a later ID can commit first,
so an ID high-water mark alone cannot represent completed deliveries. Failures
block only their own consumer and are retried on the next tick.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy import delete, exists, insert, literal, select

from ..config import Settings
from .models import OutboxConsumerRow, OutboxReceiptRow, OutboxRow

log = logging.getLogger("ontogeny.outbox")

Consumer = Callable[[OutboxRow], Awaitable[bool]]  # return True = delivered


class SseBroker:
    """In-process fan-out for /subscriptions (one queue per subscriber)."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("sse subscriber overflow, dropping event")


class OutboxDispatcher:
    def __init__(
        self,
        session_factory,
        settings: Settings,
        *,
        sse: SseBroker | None = None,
        projection_hook: Consumer | None = None,
        derivation_hook: Callable[[OutboxRow, Any], Awaitable[bool]] | None = None,
        derivation_drain=None,
        http_client: httpx.AsyncClient | None = None,
        dispatch_lock: asyncio.Lock | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.sse = sse or SseBroker()
        self.projection_hook = projection_hook
        # derivation batches: the hook queues ids, the drain applies values in
        # one subprocess + one transaction per (type, property)
        self.derivation_hook = derivation_hook
        self.derivation_drain = derivation_drain
        self.http = http_client
        self._dispatch_lock = dispatch_lock or asyncio.Lock()

    async def _client(self) -> httpx.AsyncClient:
        if self.http is None:
            self.http = httpx.AsyncClient(timeout=10.0)
        return self.http

    # ------------------------------------------------------------- consumers

    async def _deliver_webhook(self, event: OutboxRow) -> bool:
        payload = event.payload or {}
        if payload.get("kind") != "webhook":
            return True  # not ours
        template = payload.get("url_template") or payload.get("url", "")
        try:
            url = self.settings.resolve_env_ref(template)
        except KeyError as exc:
            log.warning("webhook %s not delivered: %s (fix config and replay)", event.id, exc)
            return True  # consumed-with-prejudice; replay requires deleting its receipt
        allow = self.settings.webhook_allowlist
        host = httpx.URL(url).host if url else None
        if not allow or (host and not any(host == a or host.endswith("." + a) for a in allow)):
            log.warning("webhook to %r blocked by allowlist", url)
            return True  # treated as delivered-with-prejudice; audited in logs
        client = await self._client()
        resp = await client.post(
            url,
            json={
                "object_type": event.object_type,
                "object_id": event.object_id,
                "revision_id": event.revision_id,
                "payload": payload,
            },
        )
        if 200 <= resp.status_code < 300:
            return True
        if resp.status_code >= 500:
            # the endpoint is broken, not the request: retry it (a connection
            # error raises and is retried the same way)
            log.warning("webhook %s to %r answered %s; will retry", event.id, url, resp.status_code)
            return False
        # 4xx: the request itself is wrong. Retrying cannot fix it, so consume
        # the event and say so — the alternative is a poison row blocking this
        # consumer forever.
        log.warning(
            "webhook %s to %r rejected with %s (consumed; fix the endpoint and replay)",
            event.id,
            url,
            resp.status_code,
        )
        return True

    async def _deliver_projection(self, event: OutboxRow) -> bool:
        if self.projection_hook is None:
            return True
        return bool(await self.projection_hook(event))

    async def _deliver_sse(self, event: OutboxRow) -> bool:
        # identifiers only: the payload carries full property values, and SSE
        # consumers that need them re-read through the query path (masking
        # included) instead of receiving an unmasked broadcast.
        self.sse.publish(
            {
                "id": event.id,
                "object_type": event.object_type,
                "object_id": event.object_id,
                "op": event.op,
            }
        )
        return True

    async def _deliver_derivation(self, event: OutboxRow, session) -> bool:
        if self.derivation_hook is None:
            return True
        return bool(await self.derivation_hook(event, session))

    # --------------------------------------------------------------- driving

    async def dispatch_pending(self, *, limit: int = 100) -> dict[str, int]:
        # The background loop and the admin endpoint share cursors and must
        # never dispatch the same batch concurrently in this process.
        async with self._dispatch_lock:
            return await self._dispatch_pending(limit=limit)

    async def replay(self, consumer: str, *, from_id: int, through_id: int) -> int:
        """Explicitly retry acknowledged events in a bounded inclusive range.

        Replaying a webhook may deliver it again. This also permits operators
        to recover old pre-migration gaps that legacy cursors cannot distinguish
        from completed deliveries.
        """
        if consumer not in {"webhook", "projection", "derivation", "sse"} or from_id < 1 or through_id < from_id:
            raise ValueError("invalid outbox consumer or replay range")
        async with self._dispatch_lock, self.session_factory() as session:
            cursor = await session.get(OutboxConsumerRow, consumer)
            if cursor is None or not cursor.receipts_initialized:
                raise ValueError("consumer receipts have not been initialized; dispatch first")
            result = await session.execute(
                delete(OutboxReceiptRow).where(
                    OutboxReceiptRow.consumer == consumer,
                    OutboxReceiptRow.event_id >= from_id,
                    OutboxReceiptRow.event_id <= through_id,
                )
            )
            await session.commit()
            return int(result.rowcount)

    async def _dispatch_pending(self, *, limit: int = 100) -> dict[str, int]:
        stats: dict[str, int] = {}
        async with self.session_factory() as session:
            consumers: dict[str, Consumer] = {
                "webhook": self._deliver_webhook,
                "projection": self._deliver_projection,
                "derivation": lambda event: self._deliver_derivation(event, session),
                "sse": self._deliver_sse,
            }
            for name, deliver in consumers.items():
                cursor = (
                    await session.execute(select(OutboxConsumerRow).where(OutboxConsumerRow.consumer == name))
                ).scalar_one_or_none()
                if cursor is None:
                    cursor = OutboxConsumerRow(consumer=name, last_id=0, receipts_initialized=True)
                    session.add(cursor)
                    await session.flush()
                elif not cursor.receipts_initialized:
                    # Snapshot the *visible* legacy history once. Do not replay
                    # old webhooks implicitly; a transaction that commits after
                    # this statement has no receipt even if its ID is lower.
                    await session.execute(
                        insert(OutboxReceiptRow).from_select(
                            ["consumer", "event_id"],
                            select(literal(name), OutboxRow.id).where(OutboxRow.id <= cursor.last_id),
                        )
                    )
                    cursor.receipts_initialized = True
                    await session.flush()
                rows = (
                    (
                        await session.execute(
                            select(OutboxRow)
                            .where(
                                ~exists().where(
                                    OutboxReceiptRow.consumer == name, OutboxReceiptRow.event_id == OutboxRow.id
                                )
                            )
                            .order_by(OutboxRow.id)
                            .limit(limit)
                        )
                    )
                    .scalars()
                    .all()
                )
                delivered = 0
                for row in rows:
                    try:
                        ok = await deliver(row)
                    except Exception as exc:
                        log.warning("outbox consumer %s failed on #%s: %s", name, row.id, exc)
                        ok = False
                    if not ok:
                        break
                    delivered += 1
                    session.add(OutboxReceiptRow(consumer=name, event_id=row.id))
                    cursor.last_id = max(cursor.last_id, row.id)
                    # First successful delivery stamps the row; used to be a
                    # self-assignment (always NULL), so delivery latency was
                    # unobservable and "pending" counts never decreased.
                    if row.published_at is None:
                        row.published_at = _dt.datetime.now(_dt.UTC)
                stats[name] = delivered
            await session.commit()

        # derivation batches run AFTER cursors advance: values are eventually
        # consistent by design, and a failed batch can be drained again
        if self.derivation_drain is not None:
            try:
                await self.derivation_drain()
            except Exception as exc:
                log.warning("derivation drain failed: %s", exc)
        return stats

    async def run_forever(self, interval: float = 1.0) -> None:  # pragma: no cover
        while True:
            try:
                await self.dispatch_pending()
            except Exception as exc:
                log.warning("outbox tick failed: %s", exc)
            await asyncio.sleep(interval)
