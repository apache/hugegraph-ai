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

"""Connection lifecycle regressions for the durable confirmation ledger."""

import sqlite3
import time

import pytest

from hugegraph_mcp.confirmation_store import ConfirmationStore, ConfirmationStoreUnavailableError
from hugegraph_mcp.write_plan import PlanStatus


@pytest.mark.parametrize(
    "operation", ["issue", "issued_payload", "consume", "has_consumed", "operation_for_plan", "record_outcome"]
)
@pytest.mark.parametrize("fail_query", [False, True], ids=["success", "query_failure"])
def test_connections_close_after_each_operation(tmp_path, monkeypatch, operation, fail_query):
    store = ConfirmationStore(tmp_path)
    args = {"nonce": "nonce", "plan_hash": "plan", "expires_at": int(time.time()) + 60}
    store.issue(**args, plan_payload={"vertices": []})
    if operation in {"has_consumed", "operation_for_plan", "record_outcome"}:
        store.consume(**args)

    connections = []
    real_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            if fail_query:
                raise sqlite3.OperationalError("injected query failure")
            return super().execute(*args, **kwargs)

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs, factory=Connection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    calls = {
        "issue": lambda: store.issue(**args, plan_payload={"vertices": []}),
        "issued_payload": lambda: store.issued_payload(**args),
        "consume": lambda: store.consume(**args),
        "has_consumed": lambda: store.has_consumed(args["nonce"]),
        "operation_for_plan": lambda: store.operation_for_plan(args["plan_hash"]),
        "record_outcome": lambda: store.record_outcome(
            plan_hash=args["plan_hash"], status=PlanStatus.APPLIED, receipt={"written": 0}
        ),
    }
    if fail_query:
        with pytest.raises(ConfirmationStoreUnavailableError):
            calls[operation]()
    else:
        calls[operation]()

    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            sqlite3.Connection.execute(connection, "SELECT 1")
