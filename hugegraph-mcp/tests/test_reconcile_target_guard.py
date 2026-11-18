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

from hugegraph_mcp.plan_store import SQLitePlanStore
from hugegraph_mcp.reconciler import ReconcileReaderRegistry, WriteReconciler
from hugegraph_mcp.write_plan import GraphTarget, OperationPlan, PlanStatus, WritePlan


def test_reconcile_rejects_mismatched_target_without_reading_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://other-host:8080")
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "other_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "DEFAULT")
    monkeypatch.setenv("HUGEGRAPH_USER", "admin")

    store = SQLitePlanStore(tmp_path)
    plan = WritePlan(
        plan_id="wp-target-mismatch",
        tool_name="test",
        graph_target=GraphTarget("http://127.0.0.1:8080", "hugegraph", "DEFAULT"),
        principal="admin",
        operations=(
            OperationPlan(
                operation_id="op-1",
                kind="DELETE_EDGE",
                target={"id": "e-1"},
                expected_state={"exists": True, "id": "e-1"},
                desired_state={"exists": False},
            ),
        ),
        payload_digest="digest",
        schema_fingerprint=None,
        status=PlanStatus.ISSUED,
        created_at=100,
        expires_at=4_102_444_800,
    )
    store.save_plan(plan)
    store.claim_plan("wp-target-mismatch")
    store.claim_operation("wp-target-mismatch", "op-1")
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE write_plans SET lease_expires_at = 0 WHERE plan_id = 'wp-target-mismatch'")

    reads = []
    readers = ReconcileReaderRegistry()
    readers.register("DELETE_EDGE", lambda *_: reads.append(True) or {"exists": False})

    result = WriteReconciler(store=store, readers=readers).reconcile("wp-target-mismatch")

    assert result["ok"] is False
    assert result["error"]["type"] == "WRITE_CONFLICT"
    assert result["error"]["details"]["reason_code"] == "TARGET_CHANGED"
    assert reads == []
    persisted = store.get_plan_record("wp-target-mismatch")
    assert persisted is not None
    assert persisted["status"] == PlanStatus.EXECUTING.value
