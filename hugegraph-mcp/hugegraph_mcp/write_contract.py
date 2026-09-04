# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

"""Compatibility rules for canonical and legacy confirmation locators."""

from dataclasses import dataclass
from enum import Enum

from hugegraph_mcp.envelope import ErrorType, envelope_err

LEGACY_DEPRECATION_CODE = "LEGACY_CONFIRMATION_DEPRECATED"


class ConfirmationProtocol(str, Enum):
    CANONICAL = "canonical"
    LEGACY = "legacy"


@dataclass(frozen=True)
class ConfirmationResolution:
    protocol: ConfirmationProtocol
    plan_id: str | None
    plan_hash: str | None
    nonce: str | None
    expires_at: float | None
    warnings: tuple[str, ...] = ()


def resolve_confirmation_protocol(
    *,
    plan_id: str | None = None,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> tuple[ConfirmationResolution | None, dict | None]:
    """Resolve one mutually exclusive confirmation protocol fail-closed."""

    canonical_present = bool(plan_id)
    legacy_values = (plan_hash, nonce, expires_at)
    legacy_present = any(value is not None for value in legacy_values)
    legacy_complete = all(value is not None for value in legacy_values)

    if canonical_present and legacy_present:
        return None, _protocol_error("plan_id cannot be combined with plan_hash, nonce, or expires_at.")
    if canonical_present:
        return (
            ConfirmationResolution(
                protocol=ConfirmationProtocol.CANONICAL,
                plan_id=plan_id,
                plan_hash=None,
                nonce=None,
                expires_at=None,
            ),
            None,
        )
    if legacy_present and not legacy_complete:
        return None, _protocol_error("plan_hash, nonce, and expires_at must be supplied together.")
    if legacy_complete:
        return (
            ConfirmationResolution(
                protocol=ConfirmationProtocol.LEGACY,
                plan_id=None,
                plan_hash=plan_hash,
                nonce=nonce,
                expires_at=expires_at,
                warnings=(
                    (
                        f"{LEGACY_DEPRECATION_CODE}: use plan_id with confirm_write_tool; "
                        "legacy confirmation fields will be removed after one release."
                    ),
                ),
            ),
            None,
        )
    return None, _protocol_error("A plan_id or complete legacy locator is required.")


def resolve_optional_legacy_locator(
    *,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> tuple[ConfirmationResolution | None, dict | None]:
    """Validate an optional legacy locator before a public write wrapper runs.

    Dry-run and validation calls legitimately omit confirmation fields. Once
    any legacy field is present, however, the complete deprecated locator is
    required. The returned resolution is metadata only: execution must still
    load the server-persisted plan rather than trusting the request payload.
    """

    if plan_hash is None and nonce is None and expires_at is None:
        return None, None
    return resolve_confirmation_protocol(
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
    )


def _protocol_error(reason: str) -> dict:
    return envelope_err(
        ErrorType.VALIDATION_ERROR,
        "Invalid write confirmation protocol.",
        retryable=False,
        details={"reason": reason},
    )
