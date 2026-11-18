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

"""Opaque, actor- and target-bound continuation cursor store."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

CURSOR_VERSION = 1
DEFAULT_CURSOR_TTL_SECONDS = 300.0
DEFAULT_CURSOR_CAPACITY = 512


class CursorError(ValueError):
    """Raised when a continuation cursor is invalid, expired, or mismatched."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class CursorRecord:
    cursor_id: str
    actor_key: str
    target: tuple[str, str, str, str]
    query_hash: str
    fields: tuple[str, ...] | None
    continuation_scope: str
    buffered_items: tuple[Any, ...]
    backend_next_page: str | None
    exhausted_backend: bool
    created_at: float
    expires_at: float
    route_version: int = 1


def compute_query_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InMemoryCursorStore:
    """Thread-safe bounded TTL store for opaque pagination cursors."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_CURSOR_TTL_SECONDS,
        max_entries: int = DEFAULT_CURSOR_CAPACITY,
    ) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()
        self._records: OrderedDict[str, CursorRecord] = OrderedDict()
        self._in_flight: set[str] = set()

    def _issue_locked(
        self,
        *,
        actor_key: str,
        target: tuple[str, str, str, str],
        query_hash: str,
        fields: tuple[str, ...] | None,
        continuation_scope: str,
        buffered_items: list[Any] | tuple[Any, ...],
        backend_next_page: str | None = None,
        exhausted_backend: bool = False,
        route_version: int = 1,
    ) -> str:
        now = time.time()
        cursor_id = f"cur-v{CURSOR_VERSION}-{secrets.token_urlsafe(16)}"
        record = CursorRecord(
            cursor_id=cursor_id,
            actor_key=actor_key,
            target=target,
            query_hash=query_hash,
            fields=fields,
            continuation_scope=continuation_scope,
            buffered_items=tuple(buffered_items),
            backend_next_page=backend_next_page,
            exhausted_backend=exhausted_backend,
            created_at=now,
            expires_at=now + self.ttl_seconds,
            route_version=route_version,
        )
        self._prune_expired(now)
        while len(self._records) >= self.max_entries:
            evict_id = next((cid for cid in self._records if cid not in self._in_flight), None)
            if evict_id is None:
                evict_id, _ = self._records.popitem(last=False)
                self._in_flight.discard(evict_id)
            else:
                del self._records[evict_id]
        self._records[cursor_id] = record
        return cursor_id

    def issue(
        self,
        *,
        actor_key: str,
        target: tuple[str, str, str, str],
        query_hash: str,
        fields: tuple[str, ...] | None,
        continuation_scope: str,
        buffered_items: list[Any] | tuple[Any, ...],
        backend_next_page: str | None = None,
        exhausted_backend: bool = False,
        route_version: int = 1,
    ) -> str:
        with self._lock:
            return self._issue_locked(
                actor_key=actor_key,
                target=target,
                query_hash=query_hash,
                fields=fields,
                continuation_scope=continuation_scope,
                buffered_items=buffered_items,
                backend_next_page=backend_next_page,
                exhausted_backend=exhausted_backend,
                route_version=route_version,
            )

    def _validate_locked(
        self,
        cursor_id: str,
        *,
        actor_key: str,
        target: tuple[str, str, str, str],
        query_hash: str,
        fields: tuple[str, ...] | None,
        route_version: int = 1,
    ) -> CursorRecord:
        now = time.time()
        self._prune_expired(now)
        record = self._records.get(cursor_id)
        if record is None:
            raise CursorError(
                "Continuation cursor was not found or has expired.",
                reason_code="CURSOR_EXPIRED_OR_UNKNOWN",
            )
        if record.actor_key != actor_key:
            raise CursorError("Continuation cursor belongs to a different actor.", reason_code="CURSOR_ACTOR_MISMATCH")
        if record.target != target or record.route_version != route_version:
            raise CursorError("Continuation cursor target no longer matches.", reason_code="CURSOR_TARGET_MISMATCH")
        if record.query_hash != query_hash or record.fields != fields:
            raise CursorError(
                "Continuation cursor does not match the query parameters or projection.",
                reason_code="CURSOR_QUERY_MISMATCH",
            )
        return record

    def peek(
        self,
        cursor_id: str,
        *,
        actor_key: str,
        target: tuple[str, str, str, str],
        query_hash: str,
        fields: tuple[str, ...] | None,
        route_version: int = 1,
    ) -> CursorRecord:
        if not isinstance(cursor_id, str) or not cursor_id.startswith(f"cur-v{CURSOR_VERSION}-"):
            raise CursorError("Invalid continuation cursor format.", reason_code="CURSOR_INVALID")
        with self._lock:
            return self._validate_locked(
                cursor_id,
                actor_key=actor_key,
                target=target,
                query_hash=query_hash,
                fields=fields,
                route_version=route_version,
            )

    def delete(self, cursor_id: str) -> None:
        with self._lock:
            self._in_flight.discard(cursor_id)
            self._records.pop(cursor_id, None)

    def acquire(
        self,
        cursor_id: str,
        *,
        actor_key: str,
        target: tuple[str, str, str, str],
        query_hash: str,
        fields: tuple[str, ...] | None,
        route_version: int = 1,
    ) -> CursorRecord:
        """Validate and lease a cursor for one in-flight read without consuming it."""
        if not isinstance(cursor_id, str) or not cursor_id.startswith(f"cur-v{CURSOR_VERSION}-"):
            raise CursorError("Invalid continuation cursor format.", reason_code="CURSOR_INVALID")

        with self._lock:
            record = self._validate_locked(
                cursor_id,
                actor_key=actor_key,
                target=target,
                query_hash=query_hash,
                fields=fields,
                route_version=route_version,
            )
            if cursor_id in self._in_flight:
                raise CursorError(
                    "Continuation cursor is currently in flight.",
                    reason_code="CURSOR_IN_FLIGHT",
                )
            self._in_flight.add(cursor_id)
            return record

    def release(self, cursor_id: str) -> None:
        """Release an in-flight cursor lease after a failed read so callers can retry."""
        with self._lock:
            self._in_flight.discard(cursor_id)
            self._prune_expired(time.time())

    def commit(self, cursor_id: str) -> None:
        """Consume a leased cursor once the read response has been built."""
        with self._lock:
            self._in_flight.discard(cursor_id)
            self._records.pop(cursor_id, None)

    def complete(
        self,
        cursor_id: str | None,
        *,
        actor_key: str,
        target: tuple[str, str, str, str],
        query_hash: str,
        fields: tuple[str, ...] | None,
        continuation_scope: str,
        buffered_items: list[Any] | tuple[Any, ...],
        backend_next_page: str | None = None,
        exhausted_backend: bool = False,
        route_version: int = 1,
    ) -> str:
        """Atomically consume the previous cursor (if any) and issue the next cursor."""
        with self._lock:
            if cursor_id is not None:
                self._in_flight.discard(cursor_id)
                self._records.pop(cursor_id, None)
            return self._issue_locked(
                actor_key=actor_key,
                target=target,
                query_hash=query_hash,
                fields=fields,
                continuation_scope=continuation_scope,
                buffered_items=buffered_items,
                backend_next_page=backend_next_page,
                exhausted_backend=exhausted_backend,
                route_version=route_version,
            )

    def consume(
        self,
        cursor_id: str,
        *,
        actor_key: str,
        target: tuple[str, str, str, str],
        query_hash: str,
        fields: tuple[str, ...] | None,
        route_version: int = 1,
    ) -> CursorRecord:
        if not isinstance(cursor_id, str) or not cursor_id.startswith(f"cur-v{CURSOR_VERSION}-"):
            raise CursorError("Invalid continuation cursor format.", reason_code="CURSOR_INVALID")

        with self._lock:
            record = self._validate_locked(
                cursor_id,
                actor_key=actor_key,
                target=target,
                query_hash=query_hash,
                fields=fields,
                route_version=route_version,
            )
            if cursor_id in self._in_flight:
                raise CursorError(
                    "Continuation cursor is currently in flight.",
                    reason_code="CURSOR_IN_FLIGHT",
                )
            del self._records[cursor_id]
            return record

    def _prune_expired(self, now: float) -> None:
        expired = [cid for cid, rec in self._records.items() if rec.expires_at <= now and cid not in self._in_flight]
        for cid in expired:
            del self._records[cid]


_DEFAULT_CURSOR_STORE = InMemoryCursorStore()


def get_default_cursor_store() -> InMemoryCursorStore:
    return _DEFAULT_CURSOR_STORE
