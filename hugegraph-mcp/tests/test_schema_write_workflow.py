# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

import sqlite3

import pytest
from hugegraph_mcp.plan_store import plan_store_from_config
from hugegraph_mcp.reconciler import reconcile_write
from hugegraph_mcp.tools import manage_schema as manage_schema_module
from hugegraph_mcp.tools.manage_schema import manage_schema
from hugegraph_mcp.write_executor import confirm_write


def _empty_schema():
    return {
        "schema": {
            "propertykeys": [],
            "vertexlabels": [],
            "edgelabels": [],
            "indexlabels": [],
        },
        "simple_schema": {},
        "readonly": False,
    }


def _operation():
    return {"type": "create_property_key", "name": "age", "data_type": "INT"}


class _PropertyBuilder:
    def __init__(self, state):
        self.state = state
        self.name = ""
        self.data_type = "TEXT"
        self.cardinality = "SINGLE"

    def asInt(self):
        self.data_type = "INT"
        return self

    def valueSingle(self):
        return self

    def create(self):
        self.state["schema"]["propertykeys"].append(
            {
                "name": self.name,
                "data_type": self.data_type,
                "cardinality": self.cardinality,
            }
        )


class _SchemaManager:
    def __init__(self, state):
        self.state = state

    def propertyKey(self, name):
        builder = _PropertyBuilder(self.state)
        builder.name = name
        return builder


def _dry_run(monkeypatch, state):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(manage_schema_module.schema_tools, "get_live_schema", lambda: state)
    return manage_schema(
        mode="dry_run",
        operations=[_operation()],
        nonce="schema-canonical-plan",
    )


def test_schema_dry_run_persists_one_canonical_operation(monkeypatch):
    result = _dry_run(monkeypatch, _empty_schema())

    assert result["ok"] is True
    assert result["data"]["plan_id"].startswith("wp_")
    assert result["data"]["status"] == "ISSUED"
    plan = plan_store_from_config().get_plan(result["data"]["plan_id"])
    assert plan is not None
    assert len(plan.operations) == 1
    assert plan.operations[0].kind == "CREATE_SCHEMA"
    assert dict(plan.operations[0].target)["name"] == "age"
    assert dict(plan.operations[0].expected_state) == {"exists": False}
    assert any("LEGACY_CONFIRMATION_DEPRECATED" in warning for warning in result["warnings"])


def test_schema_plan_id_confirmation_uses_safe_apply_and_stable_receipt(monkeypatch):
    state = _empty_schema()
    dry_run = _dry_run(monkeypatch, state)
    monkeypatch.setattr(
        manage_schema_module,
        "_schema_manager",
        lambda: _SchemaManager(state),
    )

    result = confirm_write(dry_run["data"]["plan_id"])

    assert result["ok"] is True
    assert result["data"]["status"] == "APPLIED"
    operation = result["data"]["operations"][0]
    assert operation["status"] == "APPLIED"
    assert operation["receipt"]["reason_code"] == "SCHEMA_CREATED"
    assert operation["receipt"]["observed_state"]["name"] == "age"
    assert state["schema"]["propertykeys"][0]["data_type"] == "INT"


@pytest.mark.parametrize(
    ("observed", "expected_status"),
    [
        (None, "UNKNOWN"),
        ({"name": "age", "data_type": "INT", "cardinality": "SINGLE"}, "APPLIED"),
        ({"name": "age", "data_type": "TEXT", "cardinality": "SINGLE"}, "CONFLICT"),
    ],
)
def test_schema_reconcile_reads_identical_missing_and_conflict(
    monkeypatch,
    observed,
    expected_status,
):
    state = _empty_schema()
    dry_run = _dry_run(monkeypatch, state)
    plan_id = dry_run["data"]["plan_id"]
    store = plan_store_from_config()
    plan = store.get_plan(plan_id)
    assert plan is not None
    store.claim_plan(plan_id)
    store.claim_operation(plan_id, plan.operations[0].operation_id)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE write_plans SET lease_expires_at = 0 WHERE plan_id = ?",
            (plan_id,),
        )
    if observed is not None:
        state["schema"]["propertykeys"].append(observed)

    result = reconcile_write(plan_id)

    assert result["ok"] is True
    assert result["data"]["status"] == expected_status
    assert result["data"]["operations"][0]["status"] == expected_status
