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
# specific language governing permissions and
# limitations under the License.
"""PR #380 security-pack regression tests: Cedar forbid semantics,
derived-property marking propagation, agent-session deletion guards."""

from __future__ import annotations

import copy

import pytest

from ontogeny.core import load_package, validate
from ontogeny.policy.engine import PolicyEngine, parse_forbids, parse_policy_set


class TestForbidSemantics:
    def _engine(self, cedar: str):
        from ontogeny.registry.compiled import compile_package

        pkg = copy.deepcopy(load_package("domains/product-manufacturing"))
        pkg.source_texts[("PolicySet", "default")] = cedar
        return PolicyEngine(compile_package(pkg))

    def test_forbid_overrides_permit(self):
        eng = self._engine(
            'permit(principal, action == Action::"release-production-order", resource);\n'
            'forbid(principal, action == Action::"release-production-order", resource)\n'
            '  when { resource.status == "RELEASED" };'
        )
        d = eng.decide({"id": "u", "Role": ["planner"]}, "release-production-order", {"status": "RELEASED"})
        assert d.allow is False and "forbid overrides permit" in d.reason

    def test_forbid_not_matching_still_permits(self):
        eng = self._engine(
            'permit(principal, action == Action::"release-production-order", resource);\n'
            'forbid(principal, action == Action::"release-production-order", resource)\n'
            '  when { resource.status == "RELEASED" };'
        )
        d = eng.decide({"id": "u", "Role": ["planner"]}, "release-production-order", {"status": "PLANNED"})
        assert d.allow is True

    def test_forbid_role_scoped(self):
        eng = self._engine(
            'permit(principal, action == Action::"release-production-order", resource);\n'
            'forbid(principal in Role::"auditor", action == Action::"release-production-order", resource);'
        )
        assert eng.decide({"id": "u", "Role": ["auditor"]}, "release-production-order", {}).allow is False
        assert eng.decide({"id": "u", "Role": ["planner"]}, "release-production-order", {}).allow is True

    def test_parse_forbids_counts(self):
        assert len(parse_forbids('forbid(principal, action == Action::"x", resource);')) == 1
        assert parse_forbids('permit(principal, action == Action::"x", resource);') == []

    def test_unparseable_forbid_refused_at_publish(self):
        pkg = copy.deepcopy(load_package("domains/product-manufacturing"))
        pkg.source_texts[("PolicySet", "default")] = (
            'forbid(principal, action == Action::"release-production-order", resource) when {{ broken'
        )
        rep = validate(pkg)
        assert any(i.code == "POLICY-FORBID" for i in rep.issues), (
            "an unparseable forbid must fail publish, not ride silently"
        )

    def test_grant_parsing_ignores_forbid(self):
        # parse_policy_set stays permits-only: a forbid must never appear as a grant
        rules = parse_policy_set('forbid(principal, action == Action::"x", resource);')
        assert rules == []


class TestDerivedMarkingPropagation:
    def test_derived_from_marked_requires_marking(self):
        pkg = copy.deepcopy(load_package("domains/product-manufacturing"))
        obj = pkg.find("ObjectType", "material")
        from ontogeny.core.models import PropertyDef

        obj.spec.properties["cost_hint"] = PropertyDef(
            type="decimal(10,2)",
            display="cost hint",
            derived="target.unit_cost * 1.1",  # unit_cost carries marking: internal
        )
        rep = validate(pkg)
        assert any(i.code == "DERIVED-MARKING" for i in rep.issues)

    def test_derived_with_marking_passes(self):
        pkg = copy.deepcopy(load_package("domains/product-manufacturing"))
        obj = pkg.find("ObjectType", "material")
        from ontogeny.core.models import PropertyDef

        obj.spec.properties["cost_hint"] = PropertyDef(
            type="decimal(10,2)",
            display="cost hint",
            marking="internal",
            derived="target.unit_cost * 1.1",
        )
        rep = validate(pkg)
        assert not any(i.code == "DERIVED-MARKING" for i in rep.issues)


class TestSessionDeletionGuards:
    """Directly against the broker: the conftest client fixture has no agent
    plugin installed, so sessions are seeded as rows."""

    async def _seed(self, sc, driver_id="alice"):
        from ontogeny.agent.models import AgentSessionRow

        async with sc.sessionmaker() as s:
            row = AgentSessionRow(
                plugin="planning-copilot",
                task="t",
                status="open",
                principal=f"agent:x-{driver_id}",
                catalog_hash="h",
                tools_json=[],
                budget_steps=1,
                budget_wall_ms=1000,
                budget_writes=1,
                driver={"id": driver_id},
            )
            s.add(row)
            await s.commit()
            await s.flush()
            return row.id

    async def test_foreign_driver_cannot_delete(self, client):
        from ontogeny.errors import PolicyDeniedError

        _c, sc = client
        sid = await self._seed(sc, driver_id="alice")
        with pytest.raises(PolicyDeniedError):
            await sc.agents.delete_session(sid, principal={"id": "mallory"})

    async def test_own_driver_and_admin_can_delete(self, client):
        _c, sc = client
        sid = await self._seed(sc, driver_id="alice")
        assert (await sc.agents.delete_session(sid, principal={"id": "alice"}))["deleted"] == sid
        sid2 = await self._seed(sc, driver_id="bob")
        assert (await sc.agents.delete_session(sid2, principal={"id": "root", "is_admin": True}))["deleted"] == sid2

    async def test_session_with_approvals_is_protected(self, client):
        from ontogeny.agent.models import AgentApprovalRow
        from ontogeny.errors import ConflictError

        _c, sc = client
        sid = await self._seed(sc, driver_id="alice")
        async with sc.sessionmaker() as s:
            s.add(
                AgentApprovalRow(
                    session_id=sid,
                    plugin="planning-copilot",
                    tool="act_release_production_order",
                    action="release-production-order",
                    parameters={},
                    status="pending",
                )
            )
            await s.commit()
        with pytest.raises(ConflictError):
            await sc.agents.delete_session(sid, principal={"id": "alice"})
