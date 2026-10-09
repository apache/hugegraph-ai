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

"""Small helpers for dry-run -> plan_hash -> confirm write workflows."""

import time
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.confirmation_store import (
    ConfirmationAlreadyUsedError,
    ConfirmationNotIssuedError,
    ConfirmationPlanExpiredError,
    ConfirmationPlanMismatchError,
    ConfirmationStore,
    ConfirmationStoreUnavailableError,
)
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.plan_hash import PlanContext, verify_plan_hash
from hugegraph_mcp.write_plan import ApplyStatus, PlanStatus


def issue_plan(
    context: PlanContext,
    plan_hash: str,
    *,
    plan_payload: Any | None = None,
) -> dict[str, Any] | None:
    """Persist a server-issued plan before its dry-run response is returned."""
    try:
        ConfirmationStore.from_config().issue(
            nonce=context.nonce,
            plan_hash=plan_hash,
            expires_at=context.expires_at,
            plan_payload=plan_payload,
        )
    except ConfirmationPlanExpiredError:
        return plan_hash_error(
            error_type=ErrorType.PLAN_EXPIRED,
            details={"reason": "The generated plan TTL is outside the allowed window."},
            mismatch_message="The generated confirmation plan is invalid.",
            expired_message="The generated confirmation plan is invalid.",
            suggestion="Run dry_run again.",
        )
    except ConfirmationPlanMismatchError:
        return plan_hash_error(
            error_type=ErrorType.PLAN_HASH_MISMATCH,
            details={"reason": "The nonce is already bound to another issued plan."},
            mismatch_message="The confirmation nonce conflicts with another plan.",
            suggestion="Run dry_run again without supplying a nonce.",
        )
    except ConfirmationStoreUnavailableError:
        return plan_hash_error(
            error_type=ErrorType.SERVER_ERROR,
            details={"reason": "Confirmation state is unavailable."},
            mismatch_message="Confirmation state could not be recorded safely.",
            suggestion="Restore writable persistent confirmation state, then retry.",
        )
    return None


def load_issued_plan(
    *, nonce: str | None, plan_hash: str | None, expires_at: float | None
) -> tuple[Any | None, dict[str, Any] | None]:
    """Load a server-issued payload without consuming its one-shot confirmation."""
    if not nonce or not plan_hash or expires_at is None:
        return None, plan_hash_error(
            error_type=ErrorType.PLAN_HASH_MISMATCH,
            details={"reason": "Plan confirmation fields are incomplete."},
            mismatch_message="No server-issued dry-run plan matches this confirmation.",
            suggestion="Run dry_run again and use all returned confirmation fields.",
        )
    try:
        normalized_expires_at = int(expires_at)
    except (TypeError, ValueError, OverflowError):
        return None, plan_hash_error(
            error_type=ErrorType.PLAN_HASH_MISMATCH,
            details={"reason": "Plan expiry is invalid."},
            mismatch_message="The confirmation plan expiry is invalid.",
            suggestion="Run dry_run again and use the returned confirmation plan.",
        )
    if normalized_expires_at < int(time.time()):
        return None, plan_hash_error(
            error_type=ErrorType.PLAN_EXPIRED,
            details={"reason": "The server-issued plan has expired."},
            mismatch_message="The server-issued plan has expired.",
            expired_message="The server-issued plan has expired.",
            suggestion="Run dry_run again and use the returned confirmation plan.",
        )
    try:
        payload = ConfirmationStore.from_config().issued_payload(
            nonce=nonce,
            plan_hash=plan_hash,
            expires_at=normalized_expires_at,
        )
    except ConfirmationNotIssuedError:
        error_type = ErrorType.PLAN_HASH_MISMATCH
        reason = "No server-issued dry-run plan matches this confirmation."
    except ConfirmationPlanMismatchError:
        error_type = ErrorType.PLAN_HASH_MISMATCH
        reason = "The confirmation does not match the server-issued plan."
    except ConfirmationPlanExpiredError:
        error_type = ErrorType.PLAN_EXPIRED
        reason = "The server-issued plan has expired."
    except ConfirmationStoreUnavailableError:
        error_type = ErrorType.SERVER_ERROR
        reason = "Confirmation state is unavailable."
    else:
        return payload, None
    return None, plan_hash_error(
        error_type=error_type,
        details={"reason": reason},
        mismatch_message="No server-issued dry-run plan matches this confirmation.",
        expired_message="The server-issued plan has expired.",
        suggestion="Run dry_run again and use the returned confirmation plan.",
    )


def replayed_plan_error(nonce: str | None, *, source: str | None = None) -> dict[str, Any] | None:
    """Return a replay error before live-state validation when already consumed."""
    try:
        store = ConfirmationStore.from_config()
        consumed = store.has_consumed(nonce)
    except ConfirmationStoreUnavailableError:
        # Unknown state is not treated as unused. Full validation continues and
        # the atomic consume remains fail-closed before the first write.
        return None
    if not consumed:
        return None
    try:
        operation = store.operation_for_nonce(nonce)
    except ConfirmationStoreUnavailableError:
        operation = None
    unresolved_statuses = {
        PlanStatus.EXECUTING.value,
        PlanStatus.UNKNOWN.value,
    }
    if operation and operation.get("status") in unresolved_statuses:
        return envelope_err(
            ErrorType.WRITE_OUTCOME_UNKNOWN,
            "The prior write attempt has no confirmed outcome; reconcile before retrying.",
            suggestion="Inspect the target state and query the persisted write status.",
            retryable=False,
            details={
                "status": PlanStatus.UNKNOWN.value,
                "plan_hash": operation.get("plan_hash"),
                "reconciliation_required": True,
            },
            source=source or "hugegraph-mcp",
        )
    return plan_hash_error(
        error_type=ErrorType.PLAN_ALREADY_USED,
        details={
            "reason": ("This confirmation has already been used. Inspect the target state and run dry_run again.")
        },
        mismatch_message="This confirmation plan has already been used.",
        suggestion="Inspect the current target state, then run dry_run again.",
        source=source,
    )


def record_write_outcome(
    *,
    plan_hash: str,
    status: PlanStatus | ApplyStatus | str,
    receipt: dict[str, Any],
) -> bool:
    """Persist an execution receipt; return False if durability is unavailable."""
    persisted_status = PlanStatus(status.value if isinstance(status, (PlanStatus, ApplyStatus)) else status)
    try:
        ConfirmationStore.from_config().record_outcome(
            plan_hash=plan_hash,
            status=persisted_status,
            receipt=receipt,
        )
    except (ConfirmationNotIssuedError, ConfirmationStoreUnavailableError):
        return False
    return True


def get_write_status(plan_hash: str) -> dict[str, Any]:
    """Read the durable state of a confirmed write without exposing its payload."""
    try:
        operation = ConfirmationStore.from_config().operation_for_plan(plan_hash)
    except ConfirmationStoreUnavailableError:
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "Write status storage is unavailable.",
            retryable=False,
        )
    if operation is None:
        return envelope_err(
            ErrorType.NOT_FOUND,
            "No persisted write operation matches this plan hash.",
            retryable=False,
        )
    public = dict(operation)
    public.pop("plan", None)
    if public.get("status") == PlanStatus.EXECUTING.value:
        public["status"] = PlanStatus.UNKNOWN.value
        public["reconciliation_required"] = True
    return envelope_ok(public)


def verify_and_consume_plan(
    *,
    submitted_hash: str,
    tool_name: str,
    mode: str,
    payload_digest: str,
    schema_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
    extra_context: dict[str, Any] | None = None,
) -> tuple[bool, ErrorType | None, dict[str, Any] | None]:
    """Validate a plan without side effects, then atomically consume its nonce."""
    valid, error_type, details, _payload = verify_and_consume_issued_plan(
        submitted_hash=submitted_hash,
        tool_name=tool_name,
        mode=mode,
        payload_digest=payload_digest,
        schema_hash=schema_hash,
        nonce=nonce,
        expires_at=expires_at,
        extra_context=extra_context,
    )
    return valid, error_type, details


def verify_and_consume_issued_plan(
    *,
    submitted_hash: str,
    tool_name: str,
    mode: str,
    payload_digest: str,
    schema_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
    extra_context: dict[str, Any] | None = None,
) -> tuple[bool, ErrorType | None, dict[str, Any] | None, Any | None]:
    """Validate, atomically consume, and return the exact persisted payload."""
    valid, error_type, details = verify_plan_hash(
        submitted_hash=submitted_hash,
        tool_name=tool_name,
        mode=mode,
        payload_digest=payload_digest,
        schema_hash=schema_hash,
        nonce=nonce,
        expires_at=expires_at,
        extra_context=extra_context,
    )
    if not valid:
        return False, error_type, details, None

    if MCPConfig.from_env().is_readonly():
        return (
            False,
            ErrorType.READONLY_VIOLATION,
            {"reason": "Write confirmation is disabled in readonly mode."},
            None,
        )

    try:
        payload = ConfirmationStore.from_config().consume(
            nonce=nonce or "",
            plan_hash=submitted_hash,
            expires_at=int(expires_at or 0),
        )
    except ConfirmationAlreadyUsedError:
        return (
            False,
            ErrorType.PLAN_ALREADY_USED,
            {"reason": ("This confirmation has already been used. Inspect the target state and run dry_run again.")},
            None,
        )
    except ConfirmationNotIssuedError:
        return (
            False,
            ErrorType.PLAN_HASH_MISMATCH,
            {"reason": "No server-issued dry-run plan matches this confirmation."},
            None,
        )
    except ConfirmationPlanMismatchError:
        return (
            False,
            ErrorType.PLAN_HASH_MISMATCH,
            {"reason": "The confirmation does not match the server-issued plan."},
            None,
        )
    except ConfirmationPlanExpiredError:
        return (
            False,
            ErrorType.PLAN_EXPIRED,
            {"reason": "The server-issued plan has expired."},
            None,
        )
    except ConfirmationStoreUnavailableError:
        return (
            False,
            ErrorType.SERVER_ERROR,
            {"reason": ("Confirmation state is unavailable. The write was blocked before execution.")},
            None,
        )
    return True, None, None, payload


def mark_readonly_preview(
    payload: dict[str, Any],
    *,
    warning: str,
    next_action: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    payload["confirmable"] = False
    payload["readonly_preview_only"] = True
    return payload, [warning], [next_action]


def confirm_required_error(
    *,
    message: str,
    suggestion: str,
    source: str | None = None,
) -> dict[str, Any]:
    return envelope_err(
        ErrorType.CONFIRM_REQUIRED,
        message,
        suggestion=suggestion,
        source=source,
    )


def plan_hash_error(
    *,
    error_type: ErrorType | None,
    details: dict[str, Any],
    mismatch_message: str,
    expired_message: str | None = None,
    suggestion: str,
    source: str | None = None,
) -> dict[str, Any]:
    resolved_error_type = error_type or ErrorType.PLAN_HASH_MISMATCH
    if resolved_error_type == ErrorType.PLAN_EXPIRED and expired_message:
        message = expired_message
    elif resolved_error_type == ErrorType.PLAN_ALREADY_USED:
        message = "This confirmation plan has already been used."
        suggestion = "Inspect the current target state, then run dry_run again and use the new confirmation plan."
    elif resolved_error_type == ErrorType.SERVER_ERROR:
        message = "Confirmation state could not be recorded safely."
        suggestion = "Restore writable persistent confirmation state, then run dry_run again."
    else:
        message = mismatch_message
    return envelope_err(
        resolved_error_type,
        message,
        suggestion=suggestion,
        source=source,
        details=details,
    )
