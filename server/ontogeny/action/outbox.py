# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Transactional-outbox dispatcher: the ONLY bridge from committed state to
the outside world (webhooks, projection worker, SSE subscribers).

Each consumer advances its own cursor; failures never block other consumers.
Poison messages advance the cursor too (with failure count) so one bad event
cannot stall the pipeline; they surface via metrics/logs for manual replay.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import select

from ..config import Settings
from .models import OutboxConsumerRow, OutboxRow

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
        derivation_hook: Consumer | None = None,
        derivation_drain=None,
        http_client: httpx.AsyncClient | None = None,
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
            return True  # consumed-with-prejudice; replayed by rewinding the cursor
        allow = self.settings.webhook_allowlist
        host = httpx.URL(url).host if url else None
        if not allow or (host and not any(host == a or host.endswith("." + a) for a in allow)):
            log.warning("webhook to %r blocked by allowlist", url)
            return True  # treated as delivered-with-prejudice; audited in logs
        client = await self._client()
        resp = await client.post(url, json={
            "object_type": event.object_type, "object_id": event.object_id,
            "revision_id": event.revision_id, "payload": payload,
        })
        if 200 <= resp.status_code < 300:
            return True
        if resp.status_code >= 500:
            # the endpoint is broken, not the request: retry it (a connection
            # error raises and is retried the same way)
            log.warning("webhook %s to %r answered %s; will retry",
                        event.id, url, resp.status_code)
            return False
        # 4xx: the request itself is wrong. Retrying cannot fix it, so consume
        # the event and say so — the alternative is a poison row blocking this
        # consumer forever.
        log.warning("webhook %s to %r rejected with %s (consumed; fix the endpoint "
                    "and replay)", event.id, url, resp.status_code)
        return True

    async def _deliver_projection(self, event: OutboxRow) -> bool:
        if self.projection_hook is None:
            return True
        return bool(await self.projection_hook(event))

    async def _deliver_sse(self, event: OutboxRow) -> bool:
        # identifiers only: the payload carries full property values, and SSE
        # consumers that need them re-read through the query path (masking
        # included) instead of receiving an unmasked broadcast.
        self.sse.publish({
            "id": event.id, "object_type": event.object_type, "object_id": event.object_id,
            "op": event.op,
        })
        return True

    async def _deliver_derivation(self, event: OutboxRow) -> bool:
        if self.derivation_hook is None:
            return True
        return bool(await self.derivation_hook(event))

    # --------------------------------------------------------------- driving

    async def dispatch_pending(self, *, limit: int = 100) -> dict[str, int]:
        consumers: dict[str, Consumer] = {
            "webhook": self._deliver_webhook,
            "projection": self._deliver_projection,
            "derivation": self._deliver_derivation,
            "sse": self._deliver_sse,
        }
        stats: dict[str, int] = {}
        async with self.session_factory() as session:
            for name, deliver in consumers.items():
                cursor = (await session.execute(
                    select(OutboxConsumerRow).where(OutboxConsumerRow.consumer == name)
                )).scalar_one_or_none()
                last_id = cursor.last_id if cursor else 0
                rows = (await session.execute(
                    select(OutboxRow).where(OutboxRow.id > last_id).order_by(OutboxRow.id).limit(limit)
                )).scalars().all()
                delivered = 0
                for row in rows:
                    try:
                        ok = await deliver(row)
                    except Exception as exc:  # noqa: BLE001 -- never block the pipeline
                        log.warning("outbox consumer %s failed on #%s: %s", name, row.id, exc)
                        ok = False
                    if not ok:
                        # Do NOT move past a row that was not delivered. Consumers
                        # return False precisely to be retried (the projection
                        # worker's own docstring calls it "at-least-once, retried
                        # by cursor rewind"), and advancing anyway made that a
                        # lie: one transient HTTP error lost the event forever.
                        # Stopping leaves the cursor on this row, so the next tick
                        # tries again — safe because every consumer is idempotent
                        # (upserts, POSTs to an at-least-once endpoint). A
                        # permanently failing row stalls only its own consumer,
                        # and the log line above names it.
                        break
                    delivered += 1
                    last_id = row.id
                    # First successful delivery stamps the row; used to be a
                    # self-assignment (always NULL), so delivery latency was
                    # unobservable and "pending" counts never decreased.
                    if row.published_at is None:
                        row.published_at = _dt.datetime.now(_dt.timezone.utc)
                if cursor is None:
                    session.add(OutboxConsumerRow(consumer=name, last_id=last_id))
                else:
                    cursor.last_id = last_id
                stats[name] = delivered
            await session.commit()

        # derivation batches run AFTER cursors advance: values are eventually
        # consistent by design, and a failed batch can be drained again
        if self.derivation_drain is not None:
            try:
                await self.derivation_drain()
            except Exception as exc:  # noqa: BLE001
                log.warning("derivation drain failed: %s", exc)
        return stats

    async def run_forever(self, interval: float = 1.0) -> None:  # pragma: no cover
        while True:
            try:
                await self.dispatch_pending()
            except Exception as exc:  # noqa: BLE001
                log.warning("outbox tick failed: %s", exc)
            await asyncio.sleep(interval)
