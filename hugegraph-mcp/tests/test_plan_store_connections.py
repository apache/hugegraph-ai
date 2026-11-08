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

import sqlite3

import pytest

from hugegraph_mcp import plan_store as plan_store_module
from hugegraph_mcp.plan_store import SQLitePlanStore
from hugegraph_mcp.reconciler import ReconcileReaderRegistry, WriteReconciler
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)


def _plan(plan_id: str) -> WritePlan:
    return WritePlan(
        plan_id=plan_id,
        tool_name="mutate_graph_properties_tool",
        graph_target=GraphTarget("http://127.0.0.1:8080", "hugegraph", "DEFAULT"),
        principal="admin",
        operations=(
            OperationPlan(
                operation_id=f"{plan_id}-op",
                kind="REPLACE_PROPERTIES",
                target={"id": "v-1"},
                expected_state={"properties": {"age": 20}},
                desired_state={"properties": {"age": 21}},
            ),
        ),
        payload_digest="digest",
        schema_fingerprint=None,
        status=PlanStatus.ISSUED,
        created_at=100,
        expires_at=4_102_444_800,
    )


@pytest.fixture
def opened_connections(monkeypatch):
    connections = []
    connect = sqlite3.connect

    def recording_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(plan_store_module.sqlite3, "connect", recording_connect)
    return connections


def _assert_all_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


def test_plan_store_closes_every_connection_it_opens(tmp_path, opened_connections):
    store = SQLitePlanStore(tmp_path)

    store.save_plan(_plan("wp-transition"))
    store.transition_plan("wp-transition", expected=PlanStatus.ISSUED, target=PlanStatus.EXECUTING)

    store.save_plan(_plan("wp-apply"))
    store.claim_plan("wp-apply")
    attempt = store.claim_operation("wp-apply", "wp-apply-op")
    store.record_receipt(
        ApplyReceipt(
            plan_id="wp-apply",
            operation_id="wp-apply-op",
            status=ApplyStatus.UNKNOWN,
            attempt=attempt,
            reconciliation_required=True,
        )
    )
    readers = ReconcileReaderRegistry()
    readers.register("REPLACE_PROPERTIES", lambda _plan, _operation: {"properties": {"age": 21}})
    result = WriteReconciler(store=store, readers=readers).reconcile("wp-apply")

    assert result["data"]["status"] == "APPLIED"
    assert store.get_plan("wp-apply") is not None
    assert store.get_plan_record("wp-apply")["status"] == "APPLIED"
    _assert_all_closed(opened_connections)
