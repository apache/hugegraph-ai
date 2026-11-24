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
# specific language governing permissions and limitations
# under the License.

"""Kinetic layer end-to-end: rules, policy, effects, audit, idempotency,
optimistic locking, outbox webhook delivery -- exercised against the
chip-lifecycle domain (tape out a planned version as the product role)."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI

from ontogeny.action.outbox import SseBroker
from ontogeny.api.routes_data import register


def test_overflow_notifies_and_detaches_only_slow_subscriber():
    broker = SseBroker()
    slow, fast = broker.subscribe(), broker.subscribe()
    for i in range(257):
        event = {"id": i, "object_type": "demo"}
        broker.publish(event)
        assert fast.get_nowait() == event
    assert slow.get_nowait() == {"resync_required": True}
    assert slow.empty()
    broker.publish({"id": 257, "object_type": "demo"})
    assert slow.empty()
    assert fast.get_nowait()["id"] == 257
    broker.unsubscribe(slow)
    broker.unsubscribe(slow)


def test_full_queue_without_overflow_keeps_events():
    broker = SseBroker()
    q = broker.subscribe()
    for i in range(256):
        broker.publish({"id": i})
    assert [q.get_nowait()["id"] for _ in range(256)] == list(range(256))


async def response_for(broker):
    app = FastAPI()
    register(app, APIRouter(), SimpleNamespace(sse=broker))
    route = next(r for r in app.routes if r.path == "/api/v1/subscriptions/objects/{object_type}")
    return await route.endpoint("demo", {})


@pytest.mark.asyncio
async def test_stream_signals_overflow_even_for_other_object_type_and_closes():
    broker = SseBroker()
    response = await response_for(broker)
    for i in range(257):
        broker.publish({"id": i, "object_type": "other"})
    chunk = await asyncio.wait_for(anext(response.body_iterator), timeout=1)
    assert chunk == 'event: resync_required\ndata: {"reason": "subscriber_overflow"}\n\n'
    with pytest.raises(StopAsyncIteration):
        await anext(response.body_iterator)
    assert not broker._subs


@pytest.mark.asyncio
async def test_normal_stream_and_disconnect_cleanup():
    broker = SseBroker()
    response = await response_for(broker)
    event = {"id": 1, "object_type": "demo"}
    broker.publish(event)
    assert await anext(response.body_iterator) == f"data: {json.dumps(event)}\n\n"
    await response.body_iterator.aclose()
    assert not broker._subs
