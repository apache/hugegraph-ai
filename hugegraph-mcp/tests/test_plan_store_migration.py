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

import hashlib
import json
import sqlite3

import pytest

from hugegraph_mcp.plan_store import (
    SCHEMA_VERSION,
    PlanStoreUnavailableError,
    PlanTransitionError,
    SQLitePlanStore,
)
from hugegraph_mcp.reconciler import ReconcileReaderRegistry, WriteReconciler
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
    canonical_plan_json,
)


def _legacy_database(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "confirmations.sqlite3"


def _nonce_digest(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _create_legacy_schema(database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE issued_confirmations (
                nonce_digest TEXT PRIMARY KEY,
                plan_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                issued_at INTEGER NOT NULL,
                plan_payload_json TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE consumed_confirmations (
                nonce_digest TEXT PRIMARY KEY,
                plan_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE write_operations (
                plan_hash TEXT PRIMARY KEY,
                nonce_digest TEXT NOT NULL UNIQUE,
                plan_payload_json TEXT,
                status TEXT NOT NULL,
                receipt_json TEXT,
                updated_at INTEGER NOT NULL
            )
            """
        )


def _write_plan() -> WritePlan:
    return WritePlan(
        plan_id="wp-new",
        tool_name="delete_graph_data_tool",
        graph_target=GraphTarget("http://127.0.0.1:8080", "hugegraph", "DEFAULT"),
        principal="admin",
        operations=(
            OperationPlan(
                operation_id="op-new",
                kind="DELETE_VERTEX",
                target={"type": "vertex", "id": "person:alice"},
                expected_state={"exists": True},
                desired_state={"exists": False},
            ),
        ),
        payload_digest="payload-digest",
        schema_fingerprint="schema-digest",
        status=PlanStatus.ISSUED,
        created_at=100,
        expires_at=200,
    )


def test_fresh_plan_store_has_versioned_plan_and_operation_tables(tmp_path):
    store = SQLitePlanStore(tmp_path)

    store.prepare()

    with sqlite3.connect(store.database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        plan_columns = {row[1] for row in connection.execute("PRAGMA table_info(write_plans)")}
        operation_columns = {row[1] for row in connection.execute("PRAGMA table_info(write_operations)")}
    assert version == SCHEMA_VERSION
    assert {
        "plan_id",
        "tool_name",
        "graph_target_json",
        "principal",
        "payload_json",
        "payload_digest",
        "schema_fingerprint",
        "status",
        "created_at",
        "expires_at",
        "confirmed_at",
        "lease_owner",
        "lease_expires_at",
    } <= plan_columns
    assert {
        "operation_id",
        "plan_id",
        "ordinal",
        "kind",
        "payload_json",
        "status",
        "attempt",
        "attempt_token",
        "reconciled",
        "receipt_json",
        "updated_at",
    } <= operation_columns


def test_rejects_database_from_newer_unsupported_schema(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store._prepare_storage()
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(PlanStoreUnavailableError, match="newer than supported"):
        store.prepare()


def test_additively_migrates_v1_database_to_current_schema(tmp_path):
    store = SQLitePlanStore(tmp_path)
    store._prepare_storage()
    with sqlite3.connect(store.database_path) as connection:
        store._ensure_v1_schema(connection)
        connection.execute("PRAGMA user_version = 1")

    store.prepare()

    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        plan_columns = {row[1] for row in connection.execute("PRAGMA table_info(write_plans)")}
        operation_columns = {row[1] for row in connection.execute("PRAGMA table_info(write_operations)")}
    assert {"lease_owner", "lease_expires_at"} <= plan_columns
    assert "attempt_token" in operation_columns
    assert "reconciled" in operation_columns


def test_migrates_issued_legacy_plan_with_immutable_payload(tmp_path):
    database_path = _legacy_database(tmp_path)
    _create_legacy_schema(database_path)
    payload = {"operations": [{"op": "delete_vertex", "target_id": 7}]}
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO issued_confirmations VALUES (?, ?, ?, ?, ?)",
            (_nonce_digest("issued"), "hash-issued", 200, 100, json.dumps(payload)),
        )

    store = SQLitePlanStore(tmp_path)
    store.prepare()
    record = store.get_plan_record(store.legacy_plan_id("hash-issued"))

    assert record["status"] == "ISSUED"
    assert record["payload"] == payload
    assert record["payload_digest"] == "hash-issued"
    assert record["operations"][0]["status"] == "ISSUED"


def test_consumed_only_legacy_plan_migrates_to_legacy_unknown(tmp_path):
    database_path = _legacy_database(tmp_path)
    _create_legacy_schema(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO consumed_confirmations VALUES (?, ?, ?, ?)",
            (_nonce_digest("consumed"), "hash-consumed", 200, 150),
        )

    store = SQLitePlanStore(tmp_path)
    store.prepare()
    record = store.get_plan_record(store.legacy_plan_id("hash-consumed"))

    assert record["status"] == "LEGACY_UNKNOWN"
    assert record["operations"][0]["status"] == "LEGACY_UNKNOWN"
    assert record["operations"][0]["receipt"] is None
    assert store.get_plan(store.legacy_plan_id("hash-consumed")) is None

    result = WriteReconciler(store=store, readers=ReconcileReaderRegistry()).reconcile(
        store.legacy_plan_id("hash-consumed")
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert result["error"]["details"]["reason_code"] == "LEGACY_PLAN_NOT_RECONCILABLE"


def test_migrates_existing_legacy_receipt_and_status(tmp_path):
    database_path = _legacy_database(tmp_path)
    _create_legacy_schema(database_path)
    payload = {"operations": [{"op": "delete_edge", "target_id": "edge-1"}]}
    receipt = {"status": "APPLIED", "target_id": "edge-1"}
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO consumed_confirmations VALUES (?, ?, ?, ?)",
            (_nonce_digest("applied"), "hash-applied", 200, 150),
        )
        connection.execute(
            "INSERT INTO write_operations VALUES (?, ?, ?, ?, ?, ?)",
            (
                "hash-applied",
                _nonce_digest("applied"),
                json.dumps(payload),
                "APPLIED",
                json.dumps(receipt),
                160,
            ),
        )

    store = SQLitePlanStore(tmp_path)
    store.prepare()
    record = store.get_plan_record(store.legacy_plan_id("hash-applied"))

    assert record["status"] == "APPLIED"
    assert record["operations"][0]["status"] == "APPLIED"
    assert record["operations"][0]["receipt"] == receipt


def test_corrupt_legacy_json_migrates_fail_closed(tmp_path):
    database_path = _legacy_database(tmp_path)
    _create_legacy_schema(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO consumed_confirmations VALUES (?, ?, ?, ?)",
            (_nonce_digest("corrupt"), "hash-corrupt", 200, 150),
        )
        connection.execute(
            "INSERT INTO write_operations VALUES (?, ?, ?, ?, ?, ?)",
            (
                "hash-corrupt",
                _nonce_digest("corrupt"),
                "{not-json",
                "APPLIED",
                "{not-json",
                160,
            ),
        )

    store = SQLitePlanStore(tmp_path)
    store.prepare()
    record = store.get_plan_record(store.legacy_plan_id("hash-corrupt"))

    assert record["status"] == "LEGACY_UNKNOWN"
    assert record["payload"] is None
    assert record["operations"][0]["status"] == "LEGACY_UNKNOWN"
    assert record["operations"][0]["receipt"]["reason_code"] == ("CORRUPT_LEGACY_STATE")


def test_legacy_migration_is_idempotent_across_restart(tmp_path):
    database_path = _legacy_database(tmp_path)
    _create_legacy_schema(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO consumed_confirmations VALUES (?, ?, ?, ?)",
            (_nonce_digest("restart"), "hash-restart", 200, 150),
        )

    SQLitePlanStore(tmp_path).prepare()
    restarted = SQLitePlanStore(tmp_path)
    restarted.prepare()

    with sqlite3.connect(restarted.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM write_plans").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM write_operations").fetchone()[0] == 1


def test_save_and_reload_canonical_plan_preserves_exact_payload(tmp_path):
    store = SQLitePlanStore(tmp_path)
    plan = _write_plan()

    store.save_plan(plan)
    reloaded = store.get_plan(plan.plan_id)

    assert canonical_plan_json(reloaded) == canonical_plan_json(plan)
    assert store.get_plan_record(plan.plan_id)["operations"][0]["operation_id"] == ("op-new")


def test_plan_transition_is_atomic_and_rejects_invalid_transition(tmp_path):
    store = SQLitePlanStore(tmp_path)
    plan = _write_plan()
    store.save_plan(plan)

    executing = store.transition_plan(
        plan.plan_id,
        expected=PlanStatus.ISSUED,
        target=PlanStatus.EXECUTING,
    )

    assert executing.status is PlanStatus.EXECUTING
    with pytest.raises(PlanTransitionError):
        store.transition_plan(
            plan.plan_id,
            expected=PlanStatus.ISSUED,
            target=PlanStatus.EXECUTING,
        )


def test_record_receipt_updates_operation_and_plan_status(tmp_path):
    store = SQLitePlanStore(tmp_path)
    plan = _write_plan()
    store.save_plan(plan)
    store.claim_plan(plan.plan_id)
    attempt = store.claim_operation(plan.plan_id, "op-new")
    receipt = ApplyReceipt(
        plan_id=plan.plan_id,
        operation_id="op-new",
        status=ApplyStatus.APPLIED,
        observed_state={"exists": False},
        reason_code=None,
        attempt=attempt,
        reconciliation_required=False,
        committed_at=150,
    )

    store.record_receipt(receipt)
    record = store.get_plan_record(plan.plan_id)

    assert record["status"] == "APPLIED"
    assert record["operations"][0]["status"] == "APPLIED"
    assert record["operations"][0]["attempt"] == 1
    assert record["operations"][0]["receipt"] == receipt.to_dict()


def test_known_prior_write_plus_later_rejection_remains_partial(tmp_path):
    store = SQLitePlanStore(tmp_path)
    base = _write_plan()
    second = OperationPlan(
        operation_id="op-second",
        kind="CREATE_EDGE",
        target={"source_id": "v-1", "target_id": "v-2"},
        expected_state={"exists": False},
        desired_state={"exists": True},
        depends_on=("op-new",),
    )
    plan = WritePlan(
        plan_id=base.plan_id,
        tool_name=base.tool_name,
        graph_target=base.graph_target,
        principal=base.principal,
        operations=(*base.operations, second),
        payload_digest=base.payload_digest,
        schema_fingerprint=base.schema_fingerprint,
        status=base.status,
        created_at=base.created_at,
        expires_at=base.expires_at,
    )
    store.save_plan(plan)
    store.claim_plan(plan.plan_id)
    first_attempt = store.claim_operation(plan.plan_id, "op-new")
    store.record_receipt(
        ApplyReceipt(
            plan_id=plan.plan_id,
            operation_id="op-new",
            status=ApplyStatus.APPLIED,
            attempt=first_attempt,
            committed_at=150,
        )
    )
    second_attempt = store.claim_operation(plan.plan_id, "op-second")
    store.record_receipt(
        ApplyReceipt(
            plan_id=plan.plan_id,
            operation_id="op-second",
            status=ApplyStatus.REJECTED,
            attempt=second_attempt,
            reason_code="TARGET_MISSING",
        )
    )

    record = store.get_plan_record(plan.plan_id)

    assert record["status"] == "PARTIAL"
    assert [operation["status"] for operation in record["operations"]] == [
        "APPLIED",
        "REJECTED",
    ]


def test_first_rejected_operation_with_no_writes_rejects_workflow(tmp_path):
    store = SQLitePlanStore(tmp_path)
    base = _write_plan()
    second = OperationPlan(
        operation_id="op-never-attempted",
        kind="CREATE_EDGE",
        target={"source_id": "v-1", "target_id": "v-2"},
        expected_state={"exists": False},
        desired_state={"exists": True},
        depends_on=("op-new",),
    )
    plan = WritePlan(
        plan_id=base.plan_id,
        tool_name=base.tool_name,
        graph_target=base.graph_target,
        principal=base.principal,
        operations=(*base.operations, second),
        payload_digest=base.payload_digest,
        schema_fingerprint=base.schema_fingerprint,
        status=base.status,
        created_at=base.created_at,
        expires_at=base.expires_at,
    )
    store.save_plan(plan)
    store.claim_plan(plan.plan_id)
    attempt = store.claim_operation(plan.plan_id, "op-new")

    store.record_receipt(
        ApplyReceipt(
            plan_id=plan.plan_id,
            operation_id="op-new",
            status=ApplyStatus.REJECTED,
            attempt=attempt,
            reason_code="VALIDATION_REJECTED",
        )
    )

    assert store.get_plan_record(plan.plan_id)["status"] == "REJECTED"
