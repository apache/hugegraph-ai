# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Action policies see derived state and identity remains stable."""

import pytest
from test_agent_approval import PLANNER
from test_agent_approval import client as _approval_client

from ontogeny.core.models import FunctionExecution, ModifyTargetEffect, PropertyDef, Rule
from ontogeny.errors import PolicyDeniedError, RuleRejectedError
from ontogeny.policy.engine import PermitRule

approval_client = _approval_client


def _with_derived_policy(sc):
    sc.compiled.objects["tapeout-version"].spec.properties["restricted"] = PropertyDef(
        type="boolean", derived="target.status == 'PLANNED'"
    )
    sc.runtime.policy._sets = {"default": [PermitRule(None, "tapeout", "target.restricted != true")]}
    sc.runtime.policy._forbids = {}


async def test_derived_property_is_used_for_policy_and_rule_validation(approval_client):
    _, sc = approval_client
    _with_derived_policy(sc)
    action = sc.compiled.actions["tapeout"]
    action.spec.rules = [Rule(expr="target.restricted == true")]
    async with sc.sessionmaker() as session:
        result = await sc.runtime.validate(session, "tapeout", PLANNER, {}, "TO-A1")
        assert result["rules"][0]["ok"] is True
        assert result["policy"]["allow"] is False
        with pytest.raises(PolicyDeniedError):
            await sc.runtime.execute(session, "tapeout", PLANNER, {}, "TO-A1")
        row = await sc.repo.get(session, "tapeout-version", "TO-A1")
        assert row["status"] == "PLANNED"


async def test_derived_property_is_recomputed_between_effects(approval_client):
    _, sc = approval_client
    _with_derived_policy(sc)
    sc.runtime.policy._sets = {"default": [PermitRule(None, "tapeout", None)]}
    action = sc.compiled.actions["tapeout"]
    action.spec.rules = [Rule(expr="target.restricted == true")]
    action.spec.effects = [
        ModifyTargetEffect(kind="modify-target", set={"status": "FAB"}),
        ModifyTargetEffect(kind="modify-target", when="target.restricted == false", set={"project": "X2"}),
    ]
    async with sc.sessionmaker() as session:
        revision = await sc.runtime.execute(session, "tapeout", PLANNER, {}, "TO-A1")
        await session.commit()
        assert revision.before["restricted"] is True
        assert revision.after["status"] == "FAB"
        assert revision.after["restricted"] is False
        assert revision.after["project"] == "X2"


@pytest.mark.parametrize("function_plan", [False, True])
async def test_action_cannot_change_primary_key(approval_client, function_plan):
    _, sc = approval_client
    action = sc.compiled.actions["tapeout"]
    sc.compiled.objects["tapeout-version"].spec.properties["version_id"].owner = "ontology"
    if function_plan:
        action.spec.execution = FunctionExecution(kind="function", entry="plan.py:main")

        async def run_plan(*args):
            return [{"kind": "modify-target", "set": {"version_id": "TO-NEW"}}]

        sc.runtime.function_runner = run_plan
    else:
        action.spec.effects = [ModifyTargetEffect(kind="modify-target", set={"version_id": "'TO-NEW'"})]
    async with sc.sessionmaker() as session:
        before = await sc.repo.get(session, "tapeout-version", "TO-A1")
        history = await sc.repo.history(session, "tapeout-version", "TO-A1")
        with pytest.raises(RuleRejectedError, match="cannot change the primary key"):
            await sc.runtime.execute(session, "tapeout", PLANNER, {}, "TO-A1")
        await session.commit()
        assert await sc.repo.get(session, "tapeout-version", "TO-A1") == before
        assert await sc.repo.get(session, "tapeout-version", "TO-NEW") is None
        assert await sc.repo.history(session, "tapeout-version", "TO-A1") == history
