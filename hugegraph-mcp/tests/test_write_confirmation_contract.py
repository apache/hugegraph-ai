# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

import inspect
import json
from pathlib import Path

import pytest
from hugegraph_mcp import server
from hugegraph_mcp.write_contract import (
    LEGACY_DEPRECATION_CODE,
    ConfirmationProtocol,
    resolve_confirmation_protocol,
    resolve_optional_legacy_locator,
)

CONTRACT_PATH = Path(__file__).parent / "contracts" / "write_confirmation_v2.json"
LEGACY_FIELDS = {"plan_hash", "nonce", "expires_at"}
LEGACY_PUBLIC_TOOLS = (
    server.apply_schema_tool,
    server.mutate_graph_properties_tool,
    server.import_graph_data_tool,
    server.delete_graph_data_tool,
)
CANONICAL_OUTCOMES = {
    "APPLIED",
    "ALREADY_APPLIED",
    "REJECTED",
    "CONFLICT",
    "PARTIAL",
    "UNKNOWN",
}


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_canonical_confirmation_uses_only_plan_id():
    canonical = _contract()["canonical"]

    assert canonical["confirm_request_fields"] == ["plan_id"]
    assert canonical["authoritative_source"] == "server_persisted_plan"
    assert canonical["client_payload_authoritative"] is False
    assert canonical["repeated_confirmation"] == "return_persisted_status"
    assert canonical["mixed_protocol"] == "reject"
    assert canonical["confirm_tool"] == "confirm_write_tool"
    assert canonical["status_tool"] == "get_write_status_tool"
    assert canonical["reconcile_tool"] == "reconcile_write_tool"


def test_legacy_confirmation_fields_are_one_deprecated_locator_group():
    legacy = _contract()["legacy"]

    assert set(legacy["locator_fields"]) == LEGACY_FIELDS
    assert legacy["fields_are_all_or_nothing"] is True
    assert legacy["accepted_for_releases"] == 1
    assert legacy["authoritative_source"] == "server_persisted_plan"
    assert legacy["client_payload_authoritative"] is False
    assert legacy["response_warning_code"] == "LEGACY_CONFIRMATION_DEPRECATED"


def test_current_public_write_tools_retain_complete_legacy_locator_group():
    for tool in LEGACY_PUBLIC_TOOLS:
        parameters = set(inspect.signature(tool).parameters)
        assert parameters >= LEGACY_FIELDS, tool.__name__
        assert "plan_id" not in parameters, tool.__name__


@pytest.mark.parametrize(
    "tool",
    (
        server.confirm_write_tool,
        server.get_write_status_tool,
        server.reconcile_write_tool,
    ),
)
def test_canonical_write_lifecycle_tools_accept_only_plan_id(tool):
    assert set(inspect.signature(tool).parameters) == {"plan_id"}


def test_contract_defines_complete_non_retryable_outcome_vocabulary():
    contract = _contract()

    assert set(contract["outcomes"]) == CANONICAL_OUTCOMES
    assert contract["direct_retryable_outcomes"] == []
    assert contract["errors"] == {
        "ambiguous": "WRITE_OUTCOME_UNKNOWN",
        "conflict": "WRITE_CONFLICT",
        "partial": "PARTIAL_APPLY",
        "unsupported_atomic_primitive": "FEATURE_DISABLED",
    }


def test_plan_id_and_legacy_fields_are_distinct_protocols():
    contract = _contract()
    canonical_fields = set(contract["canonical"]["confirm_request_fields"])
    legacy_fields = set(contract["legacy"]["locator_fields"])

    assert canonical_fields.isdisjoint(legacy_fields)


def test_canonical_confirmation_resolution_has_no_deprecation_warning():
    resolution, error = resolve_confirmation_protocol(plan_id="wp-1")

    assert error is None
    assert resolution.protocol is ConfirmationProtocol.CANONICAL
    assert resolution.plan_id == "wp-1"
    assert resolution.warnings == ()


def test_complete_legacy_locator_has_structured_deprecation_warning():
    resolution, error = resolve_confirmation_protocol(
        plan_hash="hash",
        nonce="nonce",
        expires_at=100,
    )

    assert error is None
    assert resolution.protocol is ConfirmationProtocol.LEGACY
    assert resolution.warnings[0].startswith(LEGACY_DEPRECATION_CODE)


def test_absent_optional_legacy_locator_is_valid_for_dry_run():
    resolution, error = resolve_optional_legacy_locator()

    assert resolution is None
    assert error is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"plan_hash": "hash"},
        {"nonce": "nonce", "expires_at": 100},
    ],
)
def test_optional_legacy_locator_is_all_or_nothing(arguments):
    resolution, error = resolve_optional_legacy_locator(**arguments)

    assert resolution is None
    assert error["error"]["type"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"plan_hash": "hash"},
        {"nonce": "nonce", "expires_at": 100},
        {
            "plan_id": "wp-1",
            "plan_hash": "hash",
            "nonce": "nonce",
            "expires_at": 100,
        },
    ],
)
def test_missing_partial_or_mixed_confirmation_protocol_is_rejected(arguments):
    resolution, error = resolve_confirmation_protocol(**arguments)

    assert resolution is None
    assert error["error"]["type"] == "VALIDATION_ERROR"
