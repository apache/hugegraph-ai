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

"""Structured approval records bound to actor, plan, digest, and target."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalRecord:
    plan_id: str
    actor_key: str
    payload_digest: str
    target: tuple[str, str, str, str]
    expires_at: int
    method: str
    decision: str
    decided_at: float


class InMemoryApprovalStore:
    def __init__(self, *, max_entries: int = 1024) -> None:
        self._lock = threading.Lock()
        self._max_entries = max(1, int(max_entries))
        self._records: OrderedDict[str, list[ApprovalRecord]] = OrderedDict()

    def record(self, approval: ApprovalRecord) -> None:
        with self._lock:
            if approval.plan_id not in self._records:
                while len(self._records) >= self._max_entries:
                    self._records.popitem(last=False)
                self._records[approval.plan_id] = []
            else:
                self._records.move_to_end(approval.plan_id)
            self._records[approval.plan_id].append(approval)

    def for_plan(self, plan_id: str, *, actor_key: str | None = None) -> list[ApprovalRecord]:
        with self._lock:
            records = list(self._records.get(plan_id, ()))
            if actor_key is not None:
                return [record for record in records if record.actor_key == actor_key]
            return records


_DEFAULT_APPROVAL_STORE = InMemoryApprovalStore()


def get_default_approval_store() -> InMemoryApprovalStore:
    return _DEFAULT_APPROVAL_STORE


def build_approval_record(
    *,
    plan_id: str,
    actor_key: str,
    payload_digest: str,
    target: tuple[str, str, str, str],
    expires_at: int,
    method: str,
    decision: str,
) -> ApprovalRecord:
    return ApprovalRecord(
        plan_id=plan_id,
        actor_key=actor_key,
        payload_digest=payload_digest,
        target=target,
        expires_at=expires_at,
        method=method,
        decision=decision,
        decided_at=time.time(),
    )
