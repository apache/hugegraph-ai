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

"""Resource subscription registry and per-session notification dispatcher."""

from __future__ import annotations

import contextlib
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from hugegraph_mcp.events import ResourceEvent

NotifyCallback = Callable[[str], Awaitable[None]]


@dataclass
class _SessionSubscription:
    session_id: str
    notify: NotifyCallback
    uris: set[str] = field(default_factory=set)
    seen_versions: dict[str, int] = field(default_factory=dict)


class SubscriptionManager:
    """Tracks per-session resource subscriptions and deduplicates notifications."""

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionSubscription] = {}

    def subscribe(self, session_id: str, uri: str, notify: NotifyCallback) -> None:
        sub = self._sessions.get(session_id)
        if sub is None:
            sub = _SessionSubscription(session_id=session_id, notify=notify)
            self._sessions[session_id] = sub
        else:
            sub.notify = notify
        sub.uris.add(uri)

    def unsubscribe(self, session_id: str, uri: str) -> None:
        sub = self._sessions.get(session_id)
        if sub is None:
            return
        sub.uris.discard(uri)
        if not sub.uris:
            self._sessions.pop(session_id, None)

    def remove_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def subscribed_uris(self, session_id: str) -> frozenset[str]:
        sub = self._sessions.get(session_id)
        if sub is None:
            return frozenset()
        return frozenset(sub.uris)

    def subscribe_session(self, session_id: str, uri: str, session: Any) -> None:
        """Bind a FastMCP / MCP ServerSession to receive notifications/resources/updated."""
        try:
            session_ref = weakref.ref(session)
        except TypeError:
            session_ref = None
        target = getattr(session, "_connection", session)
        with contextlib.suppress(TypeError):
            weakref.finalize(target, self.remove_session, session_id)

        async def _notify(updated_uri: str) -> None:
            resolved = session_ref() if session_ref is not None else session
            if resolved is None:
                self.remove_session(session_id)
                return
            sender = getattr(resolved, "send_resource_updated", None)
            if sender is None:
                return
            try:
                from pydantic import AnyUrl

                await sender(AnyUrl(updated_uri))
            except TypeError:
                await sender(updated_uri)

        self.subscribe(session_id, uri, _notify)

    async def dispatch(self, event: ResourceEvent) -> int:
        """Deliver notifications/resources/updated to subscribed sessions with version dedup."""
        delivered = 0
        for sub in tuple(self._sessions.values()):
            if event.uri not in sub.uris:
                continue
            last_version = sub.seen_versions.get(event.uri, 0)
            if event.resource_version <= last_version:
                continue
            sub.seen_versions[event.uri] = event.resource_version
            try:
                await sub.notify(event.uri)
                delivered += 1
            except Exception:
                self.remove_session(sub.session_id)
        return delivered
