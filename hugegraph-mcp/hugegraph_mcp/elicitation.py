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

"""Interactive MCP stdio elicitation gate before write execution."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from hugegraph_mcp.approvals import (
    ApprovalRecord,
    InMemoryApprovalStore,
    build_approval_record,
    get_default_approval_store,
)
from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err
from hugegraph_mcp.plan_store import plan_store_from_config
from hugegraph_mcp.runtime import get_current_actor
from hugegraph_mcp.stores.base import Actor, default_stdio_actor
from hugegraph_mcp.target_context import resolve_target_from_config, target_mismatch_details
from hugegraph_mcp.write_plan import PlanStatus


def _format_elicitation_message(plan: Any) -> str:
    op_kinds = ", ".join(op.kind for op in plan.operations)
    return (
        f"Confirm HugeGraph write plan {plan.plan_id}?\n"
        f"- Target: {plan.graph_target.graph_url} ({plan.graph_target.graphspace}/{plan.graph_target.graph_name})\n"
        f"- Operations: {op_kinds}\n"
        f"- Digest: {plan.payload_digest}\n"
        f"- Expires at: {plan.expires_at}\n"
        "This mutation may be irreversible."
    )


async def confirm_plan_via_elicitation(
    ctx: Any,
    plan_id: str,
    *,
    cfg: MCPConfig | None = None,
    actor: Actor | None = None,
    approval_store: InMemoryApprovalStore | None = None,
    timeout_seconds: float = 60.0,
) -> tuple[bool, dict[str, Any] | None, ApprovalRecord | None]:
    """Request explicit user confirmation via MCP elicitation without holding a DB lease.

    Returns ``(approved, error_envelope, approval_record)``.
    """

    effective_cfg = cfg or get_effective_config()
    effective_actor = actor or get_current_actor() or default_stdio_actor()
    store = plan_store_from_config(effective_cfg)
    plan = await asyncio.to_thread(store.get_plan, plan_id)
    if plan is None:
        return (
            False,
            envelope_err(
                ErrorType.NOT_FOUND,
                "No server-issued write plan matches this plan_id.",
                retryable=False,
                source="confirm_write_tool",
            ),
            None,
        )

    # Terminal or non-ISSUED plans are handled idempotently by WriteExecutor.confirm.
    if plan.status is not PlanStatus.ISSUED:
        return True, None, None

    resolved = resolve_target_from_config(effective_cfg)
    mismatch = target_mismatch_details(resolved, plan)
    if mismatch is not None:
        return (
            False,
            envelope_err(
                ErrorType.WRITE_CONFLICT,
                "Active HugeGraph target does not match the persisted write plan.",
                retryable=False,
                source="confirm_write_tool",
                details=mismatch,
            ),
            None,
        )

    if int(time.time()) > plan.expires_at:
        return (
            False,
            envelope_err(
                ErrorType.WRITE_CONFLICT,
                "The write plan has expired before confirmation.",
                retryable=False,
                source="confirm_write_tool",
                details={"reason_code": "PLAN_EXPIRED"},
            ),
            None,
        )

    if ctx is None or not hasattr(ctx, "elicit"):
        return (
            False,
            envelope_err(
                ErrorType.FEATURE_DISABLED,
                "Interactive elicitation is enabled, but the MCP client context does not support elicit().",
                suggestion="Use a client that supports MCP elicitation or set HUGEGRAPH_MCP_CONFIRMATION_MODE=manual.",
                retryable=False,
                source="confirm_write_tool",
                details={"reason_code": "ELICITATION_UNSUPPORTED"},
            ),
            None,
        )

    message = _format_elicitation_message(plan)
    try:
        response = await asyncio.wait_for(
            ctx.elicit(message, response_type=bool),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        return (
            False,
            envelope_err(
                ErrorType.TIMEOUT,
                "Interactive confirmation timed out; the write plan was not executed.",
                retryable=True,
                source="confirm_write_tool",
                details={"reason_code": "ELICITATION_TIMEOUT"},
            ),
            None,
        )
    except Exception as exc:
        return (
            False,
            envelope_err(
                ErrorType.FEATURE_DISABLED,
                f"Interactive elicitation failed or is unsupported by the client: {exc}",
                retryable=False,
                source="confirm_write_tool",
                details={"reason_code": "ELICITATION_UNSUPPORTED"},
            ),
            None,
        )

    action = getattr(response, "action", None)
    data = getattr(response, "data", response)
    store_ref = approval_store or get_default_approval_store()
    if action in {"decline", "cancel"} or data is not True:
        reason = "ELICITATION_CANCELLED" if action == "cancel" else "ELICITATION_DECLINED"
        decision = "cancelled" if action == "cancel" else "declined"
        store_ref.record(
            build_approval_record(
                plan_id=plan.plan_id,
                actor_key=effective_actor.principal_key,
                payload_digest=plan.payload_digest,
                target=resolved.as_tuple(),
                expires_at=plan.expires_at,
                method="stdio_elicitation",
                decision=decision,
            )
        )
        return (
            False,
            envelope_err(
                ErrorType.WRITE_CONFLICT,
                "Write plan confirmation was declined or cancelled by the user.",
                retryable=False,
                source="confirm_write_tool",
                details={"reason_code": reason, "action": action},
            ),
            None,
        )

    # Re-verify latest plan, target, and expiry after user response before allowing execution.
    latest_plan = await asyncio.to_thread(store.get_plan, plan_id) or plan
    recheck_cfg = get_effective_config() if cfg is None else cfg
    recheck_target = resolve_target_from_config(recheck_cfg)
    recheck_mismatch = target_mismatch_details(recheck_target, latest_plan)
    if recheck_mismatch is not None:
        return (
            False,
            envelope_err(
                ErrorType.WRITE_CONFLICT,
                "Active HugeGraph target changed while awaiting confirmation.",
                retryable=False,
                source="confirm_write_tool",
                details=recheck_mismatch,
            ),
            None,
        )

    if int(time.time()) > latest_plan.expires_at:
        return (
            False,
            envelope_err(
                ErrorType.WRITE_CONFLICT,
                "The write plan expired while awaiting confirmation.",
                retryable=False,
                source="confirm_write_tool",
                details={"reason_code": "PLAN_EXPIRED"},
            ),
            None,
        )

    approval = build_approval_record(
        plan_id=latest_plan.plan_id,
        actor_key=effective_actor.principal_key,
        payload_digest=latest_plan.payload_digest,
        target=recheck_target.as_tuple(),
        expires_at=latest_plan.expires_at,
        method="stdio_elicitation",
        decision="accepted",
    )
    store_ref.record(approval)
    return True, None, approval
