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

import asyncio
import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from test_function_ecosystem import _pkg_with_function_property
from test_function_ecosystem import sc as sc

from ontogeny.action.models import OutboxRow
from ontogeny.action.outbox import OutboxDispatcher
from ontogeny.api_factory import create_app_factory
from ontogeny.demo import prepare_demo
from ontogeny.service import ServiceContext


async def _eventually(check, timeout=15):
    async with asyncio.timeout(timeout):
        while not await check():
            await asyncio.sleep(0.05)


async def test_lifespan_dispatches_and_releases_resources_after_rebuild(tmp_path, monkeypatch):
    pkg = _pkg_with_function_property(tmp_path / "pkg-source")
    paths = prepare_demo(tmp_path / "demo", package=pkg)
    for key, value in paths.as_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ONTOGENY_DEMO_POPULATE", "1")
    monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", "lifespan-test-password")
    monkeypatch.setenv("ONTOGENY_WEBHOOK_ALLOWLIST", "wms.example.test")
    app = create_app_factory()
    sc = app.state.sc
    deliveries = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: deliveries.append(req) or httpx.Response(200)))

    async with app.router.lifespan_context(app):
        # Demo sync generated the events; no manual dispatch is needed for the
        # function-derived value to appear.
        async def initial_derived():
            async with sc.sessionmaker() as s:
                return (await sc.repo.get(s, "product", "P-200"))["open_order_count"] == 1

        await _eventually(initial_derived)
        old_dispatcher = sc.outbox
        await sc.publish(sc.package_root)
        assert old_dispatcher is not sc.outbox
        assert old_dispatcher._dispatch_lock is sc.outbox._dispatch_lock
        sc.outbox.http = http
        queue = sc.sse.subscribe()
        headers = {"X-Ontogeny-Principal": json.dumps({"id": "planner", "Role": ["planner"], "site": "plant-north"})}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
        ) as c:
            response = await c.post(
                "/api/v1/actions/release-production-order/execute",
                json={"target_id": "PO-1002", "parameters": {}},
            )
            assert response.status_code == 200, response.text
        async with sc.sessionmaker() as session:
            event = OutboxRow(
                object_type="product",
                object_id="P-200",
                op="event",
                payload={"kind": "webhook", "url_template": "${WMS_WEBHOOK}"},
            )
            session.add(event)
            await session.commit()
            event_id = event.id

        async def delivered_and_derived():
            async with sc.sessionmaker() as session:
                count = (await sc.repo.get(session, "product", "P-200"))["open_order_count"]
            return bool(deliveries) and count == 0

        await _eventually(delivered_and_derived)
        received = []
        async with asyncio.timeout(5):
            while event_id not in [item["id"] for item in received]:
                received.append(await queue.get())
        sc.sse.unsubscribe(queue)
        assert deliveries[0].url.host == "wms.example.test"
        task = app.state.outbox_task

    assert task.done() and task.cancelled()
    assert http.is_closed


async def test_rebuilt_dispatchers_serialize_concurrent_delivery(sc):
    await sc.outbox.dispatch_pending()
    async with sc.sessionmaker() as session:
        event = OutboxRow(object_type="product", object_id="P-200", op="upsert", payload={})
        session.add(event)
        await session.commit()
        event_id = event.id
    delivered = []

    async def projection(event):
        delivered.append(event.id)
        await asyncio.sleep(0.05)
        return True

    first = OutboxDispatcher(sc.sessionmaker, sc.settings, projection_hook=projection, dispatch_lock=sc._outbox_lock)
    second = OutboxDispatcher(sc.sessionmaker, sc.settings, projection_hook=projection, dispatch_lock=sc._outbox_lock)
    await asyncio.gather(first.dispatch_pending(), second.dispatch_pending())
    assert delivered.count(event_id) == 1


async def test_partial_startup_failure_disposes_engine(tmp_path, monkeypatch):
    pkg = _pkg_with_function_property(tmp_path / "pkg-source")
    paths = prepare_demo(tmp_path / "demo", package=pkg)
    for key, value in paths.as_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", "lifespan-test-password")
    initialize = ServiceContext.initialize
    dispose = AsyncEngine.dispose
    disposed = []

    async def track_dispose(engine, *args, **kwargs):
        disposed.append(engine)
        await dispose(engine, *args, **kwargs)

    async def fail_after_init(self):
        await initialize(self)
        raise RuntimeError("startup failed")

    monkeypatch.setattr(AsyncEngine, "dispose", track_dispose)
    monkeypatch.setattr(ServiceContext, "initialize", fail_after_init)
    app = create_app_factory()
    with pytest.raises(RuntimeError, match="startup failed"):
        async with app.router.lifespan_context(app):
            pytest.fail("startup should fail")
    assert disposed.count(app.state.sc.engine) == 1
