# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

import inspect
import json
from pathlib import Path

import pytest
from pyhugegraph.api.graph import GraphManager
from pyhugegraph.api.property_cas import (
    PropertyCASAdapter,
    PropertyCASReceipt,
    PropertyCASStatus,
)


def _contract() -> dict:
    path = Path(__file__).parents[1] / "contracts" / "conditional_property_cas.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_property_cas_protocol_has_exact_atomic_request_shape():
    parameters = inspect.signature(PropertyCASAdapter.replace_properties_if_match).parameters

    assert tuple(parameters) == (
        "self",
        "target_type",
        "target_id",
        "expected_properties",
        "desired_properties",
        "operation_id",
    )
    assert all(parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in tuple(parameters)[1:])
    assert _contract()["request_fields"] == list(tuple(parameters)[1:])


def test_property_cas_receipt_statuses_match_result_contract():
    contract = _contract()

    assert set(contract["result_mapping"].values()) == {status.value for status in PropertyCASStatus}
    receipt = PropertyCASReceipt(
        operation_id="mutation-123",
        status=PropertyCASStatus.CONFLICT,
        observed_properties={"name": "concurrent-value"},
        reason_code="EXPECTED_STATE_MISMATCH",
    )
    assert receipt.operation_id == "mutation-123"
    assert receipt.status is PropertyCASStatus.CONFLICT


def test_hugegraph_1_7_graph_manager_does_not_claim_property_cas_support():
    contract = _contract()

    assert contract["status"] == "verified_unsupported"
    assert not hasattr(GraphManager, contract["method"])


CAS_VERIFIED = _contract()["status"] == "verified_supported"


@pytest.mark.parametrize("cardinality", ["SINGLE", "LIST", "SET"])
@pytest.mark.skipif(
    not CAS_VERIFIED,
    reason="HugeGraph 1.7 has no backend-enforced property CAS primitive",
)
def test_two_clients_cannot_both_replace_the_same_expected_state(cardinality):
    """Activation gate: replace with a real two-client backend test first.

    Merely changing the capability fixture to ``verified_supported`` must make
    this test fail, preventing activation without a real concurrent proof for
    every supported cardinality.
    """

    pytest.fail(
        f"Implement the two-client backend concurrency scenario before enabling property CAS for {cardinality}."
    )
