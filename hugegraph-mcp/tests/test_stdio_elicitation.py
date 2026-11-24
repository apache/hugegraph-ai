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

import asyncio
import time

from hugegraph_mcp.approvals import InMemoryApprovalStore
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.elicitation import confirm_plan_via_elicitation
from hugegraph_mcp.plan_store import SQLitePlanStore
from hugegraph_mcp.write_plan import GraphTarget, OperationPlan, PlanStatus, WritePlan


def _save_issued_plan(tmp_path, *, expires_at: int = 4_102_444_800) -> tuple[MCPConfig, SQLitePlanStore, WritePlan]:
    cfg = MCPConfig(state_dir=tmp_path, readonly=False, confirmation_mode="elicitation", transport="stdio")
    store = SQLitePlanStore(tmp_path)
    plan = WritePlan(
        plan_id="wp-elicit-1",
        tool_name="prepare_write_tool",
        graph_target=GraphTarget("http://127.0.0.1:8080", "hugegraph", "DEFAULT"),
        principal="admin",
        operations=(
            OperationPlan(
                operation_id="op-1",
                kind="DELETE_EDGE",
                target={"id": "e-1"},
                expected_state={"exists": True},
                desired_state={"exists": False},
            ),
        ),
        payload_digest="digest-123",
        schema_fingerprint=None,
        status=PlanStatus.ISSUED,
        created_at=100,
        expires_at=expires_at,
    )
    store.save_plan(plan)
    return cfg, store, plan


def test_elicitation_decline_and_cancel_leave_plan_unclaimed(tmp_path):
    cfg, store, _plan = _save_issued_plan(tmp_path)

    class _DeclineCtx:
        async def elicit(self, message, response_type=bool):
            return type("_Resp", (), {"action": "decline", "data": False})()

    approved, err, rec = asyncio.run(confirm_plan_via_elicitation(_DeclineCtx(), "wp-elicit-1", cfg=cfg))
    assert approved is False
    assert err["error"]["details"]["reason_code"] == "ELICITATION_DECLINED"
    assert rec is None
    assert store.get_plan("wp-elicit-1").status is PlanStatus.ISSUED
    assert store.get_plan_record("wp-elicit-1")["lease_owner"] is None


def test_elicitation_unsupported_and_timeout_do_not_consume_plan(tmp_path):
    cfg, store, _plan = _save_issued_plan(tmp_path)

    approved, err, _ = asyncio.run(confirm_plan_via_elicitation(object(), "wp-elicit-1", cfg=cfg))
    assert approved is False
    assert err["error"]["details"]["reason_code"] == "ELICITATION_UNSUPPORTED"

    class _SlowCtx:
        async def elicit(self, message, response_type=bool):
            await asyncio.sleep(0.2)
            return True

    approved2, err2, _ = asyncio.run(
        confirm_plan_via_elicitation(_SlowCtx(), "wp-elicit-1", cfg=cfg, timeout_seconds=0.01)
    )
    assert approved2 is False
    assert err2["error"]["details"]["reason_code"] == "ELICITATION_TIMEOUT"
    assert store.get_plan("wp-elicit-1").status is PlanStatus.ISSUED


def test_elicitation_accept_records_approval_and_checks_expiry_during_wait(tmp_path):
    cfg, store, _plan = _save_issued_plan(tmp_path, expires_at=int(time.time()) + 5)
    approvals = InMemoryApprovalStore()

    class _AcceptCtx:
        async def elicit(self, message, response_type=bool):
            assert store.get_plan_record("wp-elicit-1")["lease_owner"] is None
            return type("_Resp", (), {"action": "accept", "data": True})()

    approved, err, rec = asyncio.run(
        confirm_plan_via_elicitation(_AcceptCtx(), "wp-elicit-1", cfg=cfg, approval_store=approvals)
    )
    assert approved is True
    assert err is None
    assert rec is not None
    assert rec.method == "stdio_elicitation"
    assert len(approvals.for_plan("wp-elicit-1")) == 1
