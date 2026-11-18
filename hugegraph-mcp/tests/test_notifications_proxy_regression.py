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

from __future__ import annotations

import asyncio
import gc

from hugegraph_mcp.events import ResourceEvent
from hugegraph_mcp.notifications import SubscriptionManager


def test_subscription_manager_survives_per_request_proxy_and_cleans_up_on_connection_drop() -> None:
    mgr = SubscriptionManager()
    uri = "hugegraph://default/DEFAULT/hugegraph/schema"
    delivered: list[str] = []

    class _PersistentConnection:
        async def send_resource_updated(self, updated_uri) -> None:
            delivered.append(str(updated_uri))

    class _RequestSessionProxy:
        def __init__(self, conn: _PersistentConnection) -> None:
            self._connection = conn

        async def send_resource_updated(self, updated_uri) -> None:
            await self._connection.send_resource_updated(updated_uri)

    conn = _PersistentConnection()
    # Pass an ephemeral proxy instance (simulating per-request ctx.session).
    mgr.subscribe_session("sess-proxy", uri, _RequestSessionProxy(conn))
    gc.collect()

    assert len(mgr._sessions) == 1

    asyncio.run(
        mgr.dispatch(
            ResourceEvent.create(
                deployment="default",
                graphspace="DEFAULT",
                graph="hugegraph",
                uri=uri,
                kind="updated",
                resource_version=1,
            )
        )
    )
    assert delivered == [uri]

    # Dropping the persistent connection should clean up the session via finalizer.
    del conn
    gc.collect()
    assert len(mgr._sessions) == 0


def test_live_standalone_session_receives_updates_until_unsubscribe() -> None:
    mgr = SubscriptionManager()
    uri = "hugegraph://default/DEFAULT/hugegraph/schema"
    delivered: list[str] = []

    class _FakeSession:
        async def send_resource_updated(self, updated_uri) -> None:
            delivered.append(str(updated_uri))

    session = _FakeSession()
    mgr.subscribe_session("sess-inline", uri, session)
    gc.collect()
    assert len(mgr._sessions) == 1

    asyncio.run(
        mgr.dispatch(
            ResourceEvent.create(
                deployment="default",
                graphspace="DEFAULT",
                graph="hugegraph",
                uri=uri,
                kind="updated",
                resource_version=1,
            )
        )
    )
    assert delivered == [uri]

    mgr.unsubscribe("sess-inline", uri)
    assert len(mgr._sessions) == 0
