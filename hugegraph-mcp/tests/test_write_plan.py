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

from dataclasses import FrozenInstanceError, replace

import pytest

from hugegraph_mcp.write_plan import (
    ALLOWED_PLAN_TRANSITIONS,
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
    aggregate_plan_status,
    can_transition,
    canonical_plan_digest,
    canonical_plan_json,
)


def _target() -> GraphTarget:
    return GraphTarget(
        graph_url="http://127.0.0.1:8080",
        graph_name="hugegraph",
        graphspace="DEFAULT",
    )


def _operation(
    operation_id: str = "op-1",
    *,
    depends_on: tuple[str, ...] = (),
) -> OperationPlan:
    return OperationPlan(
        operation_id=operation_id,
        kind="DELETE_VERTEX",
        target={"type": "vertex", "id": "person:alice"},
        expected_state={"exists": True, "properties": {"name": "Alice"}},
        desired_state={"exists": False},
        depends_on=depends_on,
        idempotency_key=None,
    )


def _plan(*operations: OperationPlan) -> WritePlan:
    selected = operations or (_operation(),)
    return WritePlan(
        plan_id="wp-1",
        tool_name="delete_graph_data_tool",
        graph_target=_target(),
        principal="admin",
        operations=selected,
        payload_digest="payload-digest",
        schema_fingerprint="schema-digest",
        status=PlanStatus.ISSUED,
        created_at=1_700_000_000,
        expires_at=1_700_000_600,
    )


def test_write_plan_and_nested_operation_state_are_immutable():
    operation = _operation()
    plan = _plan(operation)

    with pytest.raises(FrozenInstanceError):
        plan.plan_id = "wp-other"
    with pytest.raises(TypeError):
        operation.target["id"] = "person:bob"
    with pytest.raises(TypeError):
        operation.expected_state["properties"]["name"] = "Mallory"
    with pytest.raises(AttributeError):
        plan.operations.append(_operation("op-2"))


def test_operation_dependencies_preserve_declared_order():
    first = _operation("op-create-a")
    second = OperationPlan(
        operation_id="op-create-edge",
        kind="CREATE_EDGE",
        target={"source_operation_id": first.operation_id, "target_id": "person:bob"},
        expected_state={"exists": False},
        desired_state={"label": "knows"},
        depends_on=(first.operation_id,),
        idempotency_key="edge-request-1",
    )

    plan = _plan(first, second)

    assert tuple(item.operation_id for item in plan.operations) == (
        "op-create-a",
        "op-create-edge",
    )
    assert plan.operations[1].depends_on == ("op-create-a",)


def test_write_plan_rejects_duplicate_operation_identity():
    with pytest.raises(ValueError, match="duplicate operation_id"):
        _plan(_operation("duplicate"), _operation("duplicate"))


def test_write_plan_rejects_forward_or_missing_dependency():
    with pytest.raises(ValueError, match="depends on an earlier operation"):
        _plan(
            _operation("op-edge", depends_on=("op-vertex",)),
            _operation("op-vertex"),
        )


def test_canonical_serialization_is_independent_of_mapping_insertion_order():
    left = _operation()
    right = replace(
        left,
        target={"id": "person:alice", "type": "vertex"},
        expected_state={"properties": {"name": "Alice"}, "exists": True},
    )

    assert canonical_plan_json(_plan(left)) == canonical_plan_json(_plan(right))
    assert canonical_plan_digest(_plan(left)) == canonical_plan_digest(_plan(right))


def test_canonical_serialization_changes_for_authorized_state_change():
    original = _plan(_operation())
    changed = _plan(
        replace(
            _operation(),
            desired_state={"exists": False, "audit_reason": "duplicate"},
        )
    )

    assert canonical_plan_digest(original) != canonical_plan_digest(changed)


def test_apply_receipt_contains_stable_plan_and_operation_identity():
    receipt = ApplyReceipt(
        plan_id="wp-1",
        operation_id="op-1",
        status=ApplyStatus.UNKNOWN,
        observed_state=None,
        reason_code="RESPONSE_LOST",
        attempt=1,
        reconciliation_required=True,
        committed_at=None,
    )

    assert receipt.to_dict() == {
        "plan_id": "wp-1",
        "operation_id": "op-1",
        "status": "UNKNOWN",
        "observed_state": None,
        "reason_code": "RESPONSE_LOST",
        "attempt": 1,
        "reconciliation_required": True,
        "committed_at": None,
    }


def test_plan_transition_matrix_is_complete_and_fail_closed():
    expected = {
        PlanStatus.ISSUED: {PlanStatus.EXECUTING, PlanStatus.EXPIRED},
        PlanStatus.EXECUTING: {
            PlanStatus.APPLIED,
            PlanStatus.ALREADY_APPLIED,
            PlanStatus.REJECTED,
            PlanStatus.CONFLICT,
            PlanStatus.PARTIAL,
            PlanStatus.UNKNOWN,
        },
        PlanStatus.UNKNOWN: {
            PlanStatus.APPLIED,
            PlanStatus.CONFLICT,
            PlanStatus.RETRYABLE_NOT_APPLIED,
        },
        PlanStatus.LEGACY_UNKNOWN: {
            PlanStatus.APPLIED,
            PlanStatus.CONFLICT,
            PlanStatus.RETRYABLE_NOT_APPLIED,
        },
        PlanStatus.RETRYABLE_NOT_APPLIED: {PlanStatus.EXECUTING},
        PlanStatus.PARTIAL: {
            PlanStatus.PARTIAL,
            PlanStatus.APPLIED,
            PlanStatus.UNKNOWN,
        },
        PlanStatus.APPLIED: set(),
        PlanStatus.ALREADY_APPLIED: set(),
        PlanStatus.REJECTED: set(),
        PlanStatus.CONFLICT: set(),
        PlanStatus.EXPIRED: set(),
    }

    assert expected == ALLOWED_PLAN_TRANSITIONS
    for current in PlanStatus:
        for target in PlanStatus:
            assert can_transition(current, target) is (target in expected[current])


@pytest.mark.parametrize(
    ("operation_statuses", "expected"),
    [
        ((), PlanStatus.ISSUED),
        ((ApplyStatus.APPLIED,), PlanStatus.APPLIED),
        ((ApplyStatus.ALREADY_APPLIED,), PlanStatus.ALREADY_APPLIED),
        (
            (ApplyStatus.APPLIED, ApplyStatus.ALREADY_APPLIED),
            PlanStatus.APPLIED,
        ),
        ((ApplyStatus.REJECTED,), PlanStatus.REJECTED),
        ((ApplyStatus.CONFLICT,), PlanStatus.CONFLICT),
        ((ApplyStatus.UNKNOWN,), PlanStatus.UNKNOWN),
        (
            (ApplyStatus.RETRYABLE_NOT_APPLIED,),
            PlanStatus.RETRYABLE_NOT_APPLIED,
        ),
        ((ApplyStatus.PARTIAL,), PlanStatus.PARTIAL),
        ((ApplyStatus.APPLIED, ApplyStatus.REJECTED), PlanStatus.PARTIAL),
        ((ApplyStatus.ALREADY_APPLIED, ApplyStatus.CONFLICT), PlanStatus.PARTIAL),
        ((ApplyStatus.APPLIED, ApplyStatus.UNKNOWN), PlanStatus.PARTIAL),
    ],
)
def test_plan_status_aggregation(operation_statuses, expected):
    assert aggregate_plan_status(operation_statuses) is expected
