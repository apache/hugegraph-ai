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

"""Tests for plan hash verification and persistent single-use confirmation."""

import hashlib
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

from hugegraph_mcp.confirmable_workflow import (
    get_write_status,
    load_issued_plan,
    record_write_outcome,
    replayed_plan_error,
    verify_and_consume_plan,
)
from hugegraph_mcp.confirmation_store import (
    ConfirmationAlreadyUsedError,
    ConfirmationPlanExpiredError,
    ConfirmationStore,
)
from hugegraph_mcp.envelope import ErrorType
from hugegraph_mcp.plan_hash import (
    PlanContext,
    build_plan_context,
    compute_payload_digest,
    compute_plan_hash,
    verify_plan_hash,
)
from hugegraph_mcp.write_plan import ApplyStatus, PlanStatus


def _confirmation_args(context, plan_hash, **overrides):
    args = {
        "submitted_hash": plan_hash,
        "tool_name": context.tool_name,
        "mode": context.mode,
        "payload_digest": context.payload_digest,
        "schema_hash": context.schema_hash,
        "nonce": context.nonce,
        "expires_at": context.expires_at,
        "extra_context": context.extra_context,
    }
    args.update(overrides)
    return args


def _issue(context, plan_hash):
    ConfirmationStore.from_config().issue(
        nonce=context.nonce,
        plan_hash=plan_hash,
        expires_at=context.expires_at,
    )


def test_plan_hash_changes_when_graph_url_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://server-a:8080")
    _ctx_a, hash_a = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    monkeypatch.setenv("HUGEGRAPH_URL", "http://server-b:8080")
    _ctx_b, hash_b = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    assert hash_a != hash_b


def test_plan_hash_changes_when_graph_name_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "graph_a")
    _, hash_a = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    monkeypatch.setenv("HUGEGRAPH_GRAPH", "graph_b")
    _, hash_b = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    assert hash_a != hash_b
    assert len(hash_a) == 32


def test_plan_hash_changes_when_graphspace_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "space_a")
    _, hash_a = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "space_b")
    _, hash_b = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    assert hash_a != hash_b


def test_plan_hash_changes_when_principal_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_USER", "alice")
    _, hash_a = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    monkeypatch.setenv("HUGEGRAPH_USER", "bob")
    _, hash_b = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    assert hash_a != hash_b


def test_plan_hash_changes_when_readonly_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    _, hash_a = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _, hash_b = build_plan_context(tool_name="test", mode="import", payload_digest="abc123")

    assert hash_a != hash_b


def test_plan_hash_changes_when_payload_changes(monkeypatch):
    _, hash_a = build_plan_context(tool_name="test", mode="import", payload_digest="aaa")

    _, hash_b = build_plan_context(tool_name="test", mode="import", payload_digest="bbb")

    assert hash_a != hash_b


def test_plan_hash_changes_when_tool_name_changes():
    context = PlanContext(
        tool_name="import_graph_data_tool",
        mode="import",
        graph_url="http://test:8080",
        graph_name="testgraph",
        graphspace="DEFAULT",
        principal="testuser",
        readonly=True,
        payload_digest="abc",
        schema_hash="schema",
        nonce="mynonce",
        expires_at=1000,
    )
    other_tool_context = PlanContext(**{**context.__dict__, "tool_name": "delete_graph_data_tool"})

    assert compute_plan_hash(context) != compute_plan_hash(other_tool_context)


def test_plan_hash_changes_when_schema_hash_changes(monkeypatch):
    _, hash_a = build_plan_context(tool_name="test", mode="import", payload_digest="abc", schema_hash="schema1")

    _, hash_b = build_plan_context(tool_name="test", mode="import", payload_digest="abc", schema_hash="schema2")

    assert hash_a != hash_b


def test_plan_hash_changes_when_extra_context_changes():
    context = PlanContext(
        tool_name="test",
        mode="import",
        graph_url="http://test:8080",
        graph_name="testgraph",
        graphspace="DEFAULT",
        principal="testuser",
        readonly=True,
        payload_digest="abc",
        schema_hash="schema",
        nonce="mynonce",
        expires_at=1000,
        extra_context={"target": "import"},
    )
    other_context = PlanContext(**{**context.__dict__, "extra_context": {"target": "delete"}})

    assert compute_plan_hash(context) != compute_plan_hash(other_context)


def test_plan_hash_changes_when_expires_at_changes():
    context = PlanContext(
        tool_name="test",
        mode="import",
        graph_url="http://test:8080",
        graph_name="testgraph",
        graphspace="DEFAULT",
        principal="testuser",
        readonly=True,
        payload_digest="abc",
        schema_hash="schema",
        nonce="mynonce",
        expires_at=1000,
    )
    extended_context = PlanContext(**{**context.__dict__, "expires_at": 2000})

    assert compute_plan_hash(context) != compute_plan_hash(extended_context)


def test_verify_plan_hash_accepts_matching_hash(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://test:8080")
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "testgraph")
    monkeypatch.setenv("HUGEGRAPH_USER", "testuser")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    context, plan_hash = build_plan_context(tool_name="test", mode="import", payload_digest="abc123", nonce="mynonce")

    valid, error_type, _details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=context.expires_at,
    )

    assert valid is True
    assert error_type is None


def test_verify_plan_hash_rejects_mismatched_hash(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://test:8080")
    context, _ = build_plan_context(tool_name="test", mode="import", payload_digest="abc123", nonce="mynonce")

    valid, error_type, details = verify_plan_hash(
        submitted_hash="wrong_hash",
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=context.expires_at,
    )

    assert valid is False
    assert error_type == ErrorType.PLAN_HASH_MISMATCH
    assert "expected_hash" not in details
    assert details["provided_hash"] == "wrong_hash"


def test_verify_plan_hash_rejects_mismatched_tool_name(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://test:8080")
    context, plan_hash = build_plan_context(
        tool_name="import_graph_data_tool",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
    )

    valid, error_type, _details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="delete_graph_data_tool",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=context.expires_at,
    )

    assert valid is False
    assert error_type == ErrorType.PLAN_HASH_MISMATCH


def test_verify_plan_hash_rejects_mismatched_extra_context(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://test:8080")
    context, plan_hash = build_plan_context(
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        extra_context={"plan_tool_name": "import_graph_data_tool"},
    )

    valid, error_type, _details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=context.expires_at,
        extra_context={"plan_tool_name": "delete_graph_data_tool"},
    )

    assert valid is False
    assert error_type == ErrorType.PLAN_HASH_MISMATCH


def test_verify_plan_hash_rejects_missing_nonce(monkeypatch):
    valid, error_type, _details = verify_plan_hash(
        submitted_hash="any_hash",
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce=None,
    )

    assert valid is False
    assert error_type == ErrorType.PLAN_HASH_MISMATCH


def test_verify_plan_hash_rejects_missing_expires_at(monkeypatch):
    context, plan_hash = build_plan_context(tool_name="test", mode="import", payload_digest="abc123", nonce="mynonce")

    valid, error_type, _details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce=context.nonce,
        expires_at=None,
    )

    assert valid is False
    assert error_type == ErrorType.PLAN_EXPIRED


def test_compute_payload_digest_is_stable():
    d1 = compute_payload_digest({"a": 1, "b": 2})
    d2 = compute_payload_digest({"b": 2, "a": 1})

    assert d1 == d2
    assert len(d1) == 32


def test_plan_context_is_frozen():
    context, _ = build_plan_context(tool_name="test", mode="import", payload_digest="abc")

    try:
        context.tool_name = "other"
        raise AssertionError("Should be frozen")
    except AttributeError:
        pass


def test_verify_plan_hash_rejects_expired_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://test:8080")

    _context, plan_hash = build_plan_context(tool_name="test", mode="import", payload_digest="abc123", nonce="mynonce")

    # Set expires_at to the past
    valid, error_type, _details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=0.0,  # expired long ago
    )

    assert valid is False
    assert error_type == ErrorType.PLAN_EXPIRED


def test_verify_plan_hash_rejects_extended_expires_at(monkeypatch):
    context, plan_hash = build_plan_context(tool_name="test", mode="import", payload_digest="abc123", nonce="mynonce")

    valid, error_type, _details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=context.expires_at + 600,
    )

    assert valid is False
    assert error_type == ErrorType.PLAN_HASH_MISMATCH


def test_verify_and_consume_rejects_replay_across_store_instances(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(tool_name="test", mode="import", payload_digest="abc123", nonce="once")
    _issue(context, plan_hash)

    first = verify_and_consume_plan(**_confirmation_args(context, plan_hash))
    second = verify_and_consume_plan(**_confirmation_args(context, plan_hash))

    assert first == (True, None, None)
    assert second[0] is False
    assert second[1] == ErrorType.PLAN_ALREADY_USED
    assert "path" not in str(second[2]).lower()
    assert "sql" not in str(second[2]).lower()


def test_verify_and_consume_rejects_client_computed_plan_without_dry_run(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(
        tool_name="test",
        mode="import",
        payload_digest="client-computed",
        nonce="never-issued",
    )

    result = verify_and_consume_plan(**_confirmation_args(context, plan_hash))

    assert result[0] is False
    assert result[1] == ErrorType.PLAN_HASH_MISMATCH
    assert "server-issued" in result[2]["reason"]


def test_confirmation_store_rejects_far_future_expiry(monkeypatch):
    store = ConfirmationStore.from_config()

    try:
        store.issue(
            nonce="far-future",
            plan_hash="client-computed",
            expires_at=int(time.time()) + 601,
        )
        raise AssertionError("Plans beyond the server TTL must not be issued")
    except ConfirmationPlanExpiredError:
        pass


def test_server_issued_plan_survives_store_recreation(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(
        tool_name="test",
        mode="import",
        payload_digest="restart",
        nonce="restart-plan",
    )
    ConfirmationStore.from_config().issue(
        nonce=context.nonce,
        plan_hash=plan_hash,
        expires_at=context.expires_at,
    )

    assert verify_and_consume_plan(**_confirmation_args(context, plan_hash)) == (
        True,
        None,
        None,
    )


def test_server_issued_plan_payload_is_immutable_and_survives_restart(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(
        tool_name="test",
        mode="delete",
        payload_digest="compiled",
        nonce="compiled-plan",
    )
    payload = {"operations": [{"op": "delete_vertex", "target_id": 7}]}
    ConfirmationStore.from_config().issue(
        nonce=context.nonce,
        plan_hash=plan_hash,
        expires_at=context.expires_at,
        plan_payload=payload,
    )
    payload["operations"][0]["target_id"] = 8

    loaded, error = load_issued_plan(
        nonce=context.nonce,
        plan_hash=plan_hash,
        expires_at=context.expires_at,
    )

    assert error is None
    assert loaded == {"operations": [{"op": "delete_vertex", "target_id": 7}]}


def test_load_issued_plan_rejects_non_finite_expiry_without_raising():
    for expires_at in (float("nan"), float("inf"), "invalid"):
        payload, error = load_issued_plan(
            nonce="nonce",
            plan_hash="hash",
            expires_at=expires_at,
        )

        assert payload is None
        assert error["ok"] is False
        assert error["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_consumed_plan_persists_unknown_until_receipt_is_recorded(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(
        tool_name="test",
        mode="delete",
        payload_digest="durable-operation",
        nonce="durable-operation",
    )
    ConfirmationStore.from_config().issue(
        nonce=context.nonce,
        plan_hash=plan_hash,
        expires_at=context.expires_at,
        plan_payload={"operations": [{"op": "delete_vertex", "target_id": 7}]},
    )

    assert verify_and_consume_plan(**_confirmation_args(context, plan_hash))[0]
    persisted = ConfirmationStore.from_config().operation_for_plan(plan_hash)
    assert persisted is not None
    assert persisted["status"] == PlanStatus.EXECUTING.value
    replay = replayed_plan_error(context.nonce)
    assert replay["error"]["type"] == "WRITE_OUTCOME_UNKNOWN"
    assert replay["error"]["details"]["status"] == PlanStatus.UNKNOWN.value
    assert get_write_status(plan_hash)["data"]["status"] == PlanStatus.UNKNOWN.value

    assert record_write_outcome(
        plan_hash=plan_hash,
        status=ApplyStatus.APPLIED,
        receipt={"status": ApplyStatus.APPLIED.value},
    )
    status = get_write_status(plan_hash)
    assert status["data"]["status"] == PlanStatus.APPLIED.value
    assert status["data"]["receipt"] == {"status": ApplyStatus.APPLIED.value}
    assert "plan" not in status["data"]


def test_confirmation_store_persists_plan_status_enum_value(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(
        tool_name="test",
        mode="delete",
        payload_digest="enum-status",
        nonce="enum-status",
    )
    ConfirmationStore.from_config().issue(
        nonce=context.nonce,
        plan_hash=plan_hash,
        expires_at=context.expires_at,
    )
    assert verify_and_consume_plan(**_confirmation_args(context, plan_hash))[0]

    assert record_write_outcome(
        plan_hash=plan_hash,
        status=PlanStatus.CONFLICT,
        receipt={"status": ApplyStatus.CONFLICT.value},
    )

    operation = ConfirmationStore.from_config().operation_for_plan(plan_hash)
    assert operation is not None
    assert operation["status"] == PlanStatus.CONFLICT.value


def test_existing_consumed_only_database_is_migrated(monkeypatch):
    store = ConfirmationStore.from_config()
    store._prepare_storage()
    with sqlite3.connect(store.database_path) as connection:
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
    expires_at = int(time.time()) + 600

    store.issue(nonce="migrated", plan_hash="plan", expires_at=expires_at)
    store.consume(nonce="migrated", plan_hash="plan", expires_at=expires_at)

    assert store.has_consumed("migrated") is True


def test_confirmation_nonce_is_global_across_payloads(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    first_context, first_hash = build_plan_context(
        tool_name="first", mode="import", payload_digest="payload-a", nonce="shared"
    )
    second_context, second_hash = build_plan_context(
        tool_name="second", mode="delete", payload_digest="payload-b", nonce="shared"
    )
    _issue(first_context, first_hash)

    assert verify_and_consume_plan(**_confirmation_args(first_context, first_hash))[0]
    replay = verify_and_consume_plan(**_confirmation_args(second_context, second_hash))

    assert replay[0] is False
    assert replay[1] == ErrorType.PLAN_ALREADY_USED


def test_concurrent_confirmation_has_exactly_one_winner(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(tool_name="test", mode="import", payload_digest="abc123", nonce="race")
    _issue(context, plan_hash)
    args = _confirmation_args(context, plan_hash)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: verify_and_consume_plan(**args), range(8)))

    assert sum(result[0] for result in results) == 1
    assert sum(result[1] == ErrorType.PLAN_ALREADY_USED for result in results) == 7


def test_invalid_plan_does_not_consume_nonce(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123", nonce="retry-valid"
    )
    _issue(context, plan_hash)

    invalid = verify_and_consume_plan(**_confirmation_args(context, "wrong-plan-hash"))
    valid = verify_and_consume_plan(**_confirmation_args(context, plan_hash))

    assert invalid[1] == ErrorType.PLAN_HASH_MISMATCH
    assert valid == (True, None, None)


def test_expired_plan_does_not_consume_nonce(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr("hugegraph_mcp.plan_hash.time.time", lambda: 1000)
    monkeypatch.setattr("hugegraph_mcp.confirmation_store.time.time", lambda: 1000)
    expired_context, expired_hash = build_plan_context(
        tool_name="test",
        mode="import",
        payload_digest="expired",
        nonce="after-expired",
        ttl_seconds=1,
    )
    _issue(expired_context, expired_hash)
    monkeypatch.setattr("hugegraph_mcp.plan_hash.time.time", lambda: 1002)
    monkeypatch.setattr("hugegraph_mcp.confirmation_store.time.time", lambda: 1002)
    expired = verify_and_consume_plan(**_confirmation_args(expired_context, expired_hash))

    valid_context, valid_hash = build_plan_context(
        tool_name="test",
        mode="import",
        payload_digest="valid",
        nonce="after-expired",
    )
    _issue(valid_context, valid_hash)
    valid = verify_and_consume_plan(**_confirmation_args(valid_context, valid_hash))

    assert expired[1] == ErrorType.PLAN_EXPIRED
    assert valid == (True, None, None)


def test_readonly_plan_does_not_consume_nonce(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    readonly_context, readonly_hash = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123", nonce="after-readonly"
    )
    _issue(readonly_context, readonly_hash)

    blocked = verify_and_consume_plan(**_confirmation_args(readonly_context, readonly_hash))
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    writable_context, writable_hash = build_plan_context(
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="after-readonly-write",
    )
    _issue(writable_context, writable_hash)
    allowed = verify_and_consume_plan(**_confirmation_args(writable_context, writable_hash))

    assert blocked[1] == ErrorType.READONLY_VIOLATION
    assert allowed == (True, None, None)


def test_confirmation_store_permissions(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    context, plan_hash = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123", nonce="permissions"
    )
    _issue(context, plan_hash)
    assert verify_and_consume_plan(**_confirmation_args(context, plan_hash))[0]

    store = ConfirmationStore.from_config()
    if os.name == "posix":
        assert store.state_dir.stat().st_mode & 0o777 == 0o700
        assert store.database_path.stat().st_mode & 0o777 == 0o600


def test_confirmation_store_persists_nonce_digest_not_plaintext(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    nonce = "sensitive-confirmation-nonce"
    store = ConfirmationStore.from_config()
    expires_at = int(time.time()) + 600
    store.issue(nonce=nonce, plan_hash="plan", expires_at=expires_at)
    store.consume(nonce=nonce, plan_hash="plan", expires_at=expires_at)

    with sqlite3.connect(store.database_path) as connection:
        row = connection.execute(
            """
            SELECT nonce_digest, plan_hash, expires_at, consumed_at
            FROM consumed_confirmations
            """
        ).fetchone()

    assert row is not None
    assert row[0] == hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    assert nonce.encode("utf-8") not in store.database_path.read_bytes()
    assert row[1:] == ("plan", expires_at, row[3])


def test_confirmation_store_has_consumed_is_read_only(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    store = ConfirmationStore.from_config()

    assert store.has_consumed("not-consumed") is False
    assert store.database_path.exists() is False

    expires_at = int(time.time()) + 600
    store.issue(nonce="consumed", plan_hash="plan", expires_at=expires_at)
    store.consume(nonce="consumed", plan_hash="plan", expires_at=expires_at)
    assert store.has_consumed("consumed") is True
    assert store.has_consumed("not-consumed") is False


def test_confirmation_store_lazily_cleans_expired_records(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    store = ConfirmationStore.from_config()
    expires_at = int(time.time()) + 600
    store.issue(nonce="current-row", plan_hash="new", expires_at=expires_at)
    store.consume(nonce="current-row", plan_hash="new", expires_at=expires_at)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            """
            INSERT INTO consumed_confirmations
                (nonce_digest, plan_hash, expires_at, consumed_at)
            VALUES (?, ?, ?, ?)
            """,
            (hashlib.sha256(b"expired-row").hexdigest(), "old", 0, 0),
        )
    other_expiry = int(time.time()) + 600
    store.issue(nonce="cleanup-trigger", plan_hash="trigger", expires_at=other_expiry)
    store.consume(nonce="cleanup-trigger", plan_hash="trigger", expires_at=other_expiry)

    with sqlite3.connect(store.database_path) as connection:
        rows = connection.execute("SELECT plan_hash FROM consumed_confirmations ORDER BY plan_hash").fetchall()

    assert rows == [("new",), ("trigger",)]


def test_confirmation_cleanup_failure_does_not_block_current_nonce(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    store = ConfirmationStore.from_config()

    def fail_cleanup(_connection, _current_time):
        raise sqlite3.OperationalError("cleanup unavailable")

    expires_at = int(time.time()) + 600
    store.issue(
        nonce="cleanup-failure-current",
        plan_hash="current",
        expires_at=expires_at,
    )
    monkeypatch.setattr(store, "_cleanup_expired", fail_cleanup)
    store.consume(nonce="cleanup-failure-current", plan_hash="current", expires_at=expires_at)
    try:
        store.consume(
            nonce="cleanup-failure-current",
            plan_hash="current",
            expires_at=expires_at,
        )
        raise AssertionError("The current nonce must remain globally single-use")
    except ConfirmationAlreadyUsedError:
        pass


def test_unavailable_confirmation_store_fails_closed_without_internal_details(monkeypatch, tmp_path):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    unusable = tmp_path / "not-a-directory"
    unusable.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(unusable))
    context, plan_hash = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123", nonce="unavailable"
    )

    result = verify_and_consume_plan(**_confirmation_args(context, plan_hash))

    assert result[0] is False
    assert result[1] == ErrorType.SERVER_ERROR
    assert str(unusable) not in str(result[2])
    assert "sql" not in str(result[2]).lower()
