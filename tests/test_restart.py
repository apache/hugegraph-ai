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
"""Restart durability: a second ServiceContext over the same database must
behave identically -- policies keep their rules and functions keep their
sources. Regression guard: rebuilding the snapshot from DB rows used to lose
Cedar text, silently turning every policy into default-deny.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.service import ServiceContext

PLANNER = {"id": "u-planner", "Role": ["planner"]}
OPERATOR = {"id": "u-operator", "Role": ["operator"]}

# The golden package has no action governed by the package *default* policy
# (every action declares `policy: production` and the default is explicit
# deny). The default-policy semantics are exercised on a package copy that
# adds one no-policy action, permitted by the default PolicySet.
_NO_POLICY_ACTION = """\
apiVersion: ontogeny/v1
kind: Action
metadata:
  name: reopen-work-center
spec:
  target: work-center
  effects:
  - kind: create-object
    properties:
      work_center_id: newId('WC')
      name: "'Reopened Bench'"
      status: ACTIVE
      created_at: now()
"""

_DEFAULT_CEDAR = """\
// Package default policy (demo copy): the no-policy action is permitted for
// planners; everything else stays default-deny.
permit(
  principal in Role::"planner",
  action == Action::"reopen-work-center",
  resource
);
"""


@pytest_asyncio.fixture()
async def demo_env(golden_pkg_path, tmp_path):
    """Boot a demo-style context, sync, and hand back its settings."""
    from ontogeny.demo import prepare_demo

    paths = prepare_demo(tmp_path / "demo", package=golden_pkg_path)
    env = paths.as_env()
    # add the default-policy action to the package COPY (never the golden tree)
    pkg_root = Path(env["ONTOGENY_PACKAGE_ROOT"])
    (pkg_root / "actions" / "reopen-work-center.yaml").write_text(_NO_POLICY_ACTION, encoding="utf-8")
    (pkg_root / "policies" / "default.cedar").write_text(_DEFAULT_CEDAR, encoding="utf-8")

    settings = Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env)
    first = ServiceContext(settings, env["ONTOGENY_PACKAGE_ROOT"])
    await first.initialize()
    for t in first.compiled.objects:
        await first.sync(t)
    yield settings, env["ONTOGENY_PACKAGE_ROOT"], first
    if first.engine is not None:
        await first.engine.dispose()


async def _restart(settings: Settings, package_root: str) -> ServiceContext:
    """Simulate a process restart: brand-new context over the same database."""
    ctx = ServiceContext(settings, package_root)
    await ctx.initialize()
    return ctx


class TestPolicySurvivesRestart:
    async def test_cedar_texts_reloaded_from_db(self, demo_env):
        settings, package_root, first = demo_env
        assert first.compiled.cedar_texts["production"].strip(), "publish must load cedar text"

        second = await _restart(settings, package_root)
        try:
            assert "planner" in second.compiled.cedar_texts["production"], (
                "policy text must survive a DB-only rebuild"
            )
            decision = second.policy.decide(PLANNER, "release-production-order", {"status": "PLANNED"})
            assert decision.allow, f"policy degraded after restart: {decision.reason}"
            # and the explicit default-deny survives too: an operator may not
            # release orders, before or after a restart
            denied = second.policy.decide(OPERATOR, "release-production-order", {"status": "PLANNED"})
            assert not denied.allow, f"default-deny lost after restart: {denied.reason}"
        finally:
            await second.engine.dispose()

    async def test_action_executes_after_restart(self, demo_env):
        settings, package_root, first = demo_env
        await first.engine.dispose()

        second = await _restart(settings, package_root)
        try:
            async with second.sessionmaker() as s:
                rev = await second.runtime.execute(
                    s, "release-production-order", PLANNER, {}, "PO-1002",
                )
                await s.commit()
            assert rev.outcome == "executed"
        finally:
            await second.engine.dispose()

    async def test_default_policy_actions_survive_restart(self, demo_env):
        settings, package_root, first = demo_env
        await first.engine.dispose()
        second = await _restart(settings, package_root)
        try:
            async with second.sessionmaker() as s:
                rev = await second.runtime.execute(
                    s, "reopen-work-center", PLANNER, {},
                )
                await s.commit()
            assert rev.outcome == "executed"
        finally:
            await second.engine.dispose()


class TestFunctionSourcesAfterRestart:
    async def test_function_works_when_package_root_present(self, demo_env):
        settings, package_root, first = demo_env
        await first.engine.dispose()
        second = await _restart(settings, package_root)
        try:
            fn = second.compiled.functions["capacity-check"]
            async with second.sessionmaker() as s:
                value = await second.sandbox.run(s, fn, {"work_center_id": "WC-01", "qty": 10})
            assert isinstance(value, dict) and value["ok"] is True
        finally:
            await second.engine.dispose()

    async def test_missing_package_root_fails_loudly(self, demo_env):
        """DB-only deployments must say what to configure, not fail obscurely."""
        from ontogeny.errors import SandboxError

        settings, package_root, first = demo_env
        await first.engine.dispose()
        second = await _restart(settings, None)
        try:
            assert second.compiled.package_root in ("", ".", None) or not Path(second.compiled.package_root).is_dir()
            fn = second.compiled.functions["capacity-check"]
            async with second.sessionmaker() as s:
                with pytest.raises(SandboxError, match="ONTOGENY_PACKAGE_ROOT"):
                    await second.sandbox.run(s, fn, {"work_center_id": "WC-01"})
        finally:
            await second.engine.dispose()

    async def test_package_root_override_points_back_at_disk(self, demo_env):
        """When the caller knows the package directory, snapshots loaded from the
        DB must use it (functions and any future file sidecars live there)."""
        settings, package_root, first = demo_env
        await first.engine.dispose()
        second = ServiceContext(settings, None, package_root_override=package_root)
        await second.initialize()
        try:
            assert Path(second.compiled.package_root).resolve() == Path(package_root).resolve()
        finally:
            await second.engine.dispose()
