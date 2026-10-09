# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Error taxonomy shared by every layer.

Each error carries a stable machine code, an HTTP status for the API shell and
a human message. Governance paths (rules, policy, optimistic locking,
idempotency, budgets, constitution) raise dedicated subclasses so callers can
react precisely instead of string-matching.
"""
from __future__ import annotations

from typing import Any


class OOError(Exception):
    code: str = "ONTOGENY_ERROR"
    http_status: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_payload(self, trace_id: str | None = None) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "trace_id": trace_id,
        }


class DSLValidationError(OOError):
    """Package does not pass structural/semantic validation."""

    code = "DSL_INVALID"
    http_status = 400


class NotFoundError(OOError):
    code = "NOT_FOUND"
    http_status = 404


class TypeMismatchError(OOError):
    """A raw value cannot be coerced to the declared property type (sync quarantine)."""

    code = "TYPE_MISMATCH"
    http_status = 422


class RuleRejectedError(OOError):
    code = "RULE_REJECTED"
    http_status = 422


class PolicyDeniedError(OOError):
    code = "POLICY_DENIED"
    http_status = 403


class ConflictError(OOError):
    """Optimistic-lock conflict: object revision moved under the writer."""

    code = "REVISION_CONFLICT"
    http_status = 409


class AlreadyDeclaredError(OOError):
    """A create-style action collided with something an author already wrote.

    Distinct from ConflictError (which is about a revision moving under a
    writer): here nothing is concurrent, and the caller is asking the platform
    to generate something that already exists. Overwriting would discard
    deliberate choices -- a curated property whitelist, a chosen graph name --
    so the honest answer is "change that instead".
    """

    code = "ALREADY_DECLARED"
    http_status = 409


class StoreError(OOError):
    code = "STORE_ERROR"
    http_status = 503


class SandboxError(OOError):
    code = "SANDBOX_ERROR"
    http_status = 500


class CapabilityDeniedError(OOError):
    """Sandboxed function attempted an undeclared capability."""

    code = "CAPABILITY_DENIED"
    http_status = 403


class InteropError(OOError):
    code = "INTEROP_ERROR"
    http_status = 422


class EvalFailedError(OOError):
    code = "EVAL_FAILED"
    http_status = 422


class BudgetExceededError(OOError):
    code = "BUDGET_EXCEEDED"
    http_status = 429


class ConstitutionViolationError(OOError):
    """Proposal touches the constitution surface; never automatable (T3)."""

    code = "CONSTITUTION_VIOLATION"
    http_status = 403


class AuthenticationError(OOError):
    code = "UNAUTHENTICATED"
    http_status = 401


class ExpressionError(OOError):
    """mini-expr parse/eval failure."""

    code = "EXPR_ERROR"
    http_status = 422
