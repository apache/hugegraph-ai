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

"""M3: AgentCase eval -- scripted trajectories replayed through the real
broker as a deterministic selection function for agent-affecting changes.
"""

from __future__ import annotations

import shutil

import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.demo import seed_from_package
from ontogeny.service import ServiceContext

PLUGIN = """\
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata:
  name: product-copilot
  display: Product copilot
spec:
  principal:
    id: "agent:product-copilot"
    Role: [product]
    site: hq
  transport: { kind: local }
  tools:
    allow: [describe_ontology, search_tapeout_version, act_tapeout]
  approval: { writes: auto, auto_actions: [act_tapeout] }
  budget: { steps: 25, wall_ms: 60000, writes_per_session: 5 }
"""

SUITE = """\
apiVersion: ontogeny/v1
kind: EvalSuite
metadata:
  name: planning-suite
spec:
  agents:
  - name: copilot-tapes-out-and-is-idempotent
    plugin: product-copilot
    script:
    - tool: search_tapeout_version
      args: { filter: { field: status, op: eq, value: PLANNED }, limit: 5 }
    - tool: act_tapeout
      args: { parameters: {}, target_id: TO-A1 }
    expect:
      outcomes: [ok, ok]
      idempotent: true
"""


@pytest_asyncio.fixture()
async def sc(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    # the package ships its own plugins; these tests exercise one injected
    # plugin in isolation, so start the copy from an empty agents/ dir
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(PLUGIN, encoding="utf-8")
    (root / "evals" / "planning.yaml").write_text(SUITE, encoding="utf-8")
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL so the tables
    # match the ontology exactly
    seed_from_package(golden_pkg_path, src, force=True)
    settings = Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}", "FAB_WEBHOOK": "https://fab-portal.example.test/hook"},
    )
    ctx = ServiceContext(settings, str(root))
    await ctx.initialize()
    for t in ctx.compiled.objects:
        await ctx.sync(t)
    return ctx


class TestAgentEval:
    async def test_scripted_replay_passes_and_detects_double_apply(self, sc):
        suite = sc.compiled.eval_suites["planning-suite"]
        async with sc.sessionmaker() as s:
            report = await sc.eval_runner.run(s, suite)
        case = report["cases"][0]
        assert case["kind"] == "agent"
        assert case["ok"], case
        assert case["outcomes"] == ["ok", "ok"]
        # idempotency: the replay must show the second tapeout refused by rules
        # (TO-A1 is FAB after the first run, and only PLANNED versions tape out)
        assert "replay" in case
        assert case["replay"][1] == "rejected"

    async def test_outcome_mismatch_fails_the_case(self, sc):
        """A candidate that changes behaviour (here: the write tool leaves the
        plugin's allow list) must turn the suite red -- the selection function
        biting. The broker serves the COMPILED snapshot, so that is what the
        test swaps, exactly like a promotion would."""
        from dataclasses import replace as dc_replace

        suite = sc.compiled.eval_suites["planning-suite"]
        plug = sc.compiled.agent_plugins["product-copilot"]
        stripped = plug.model_copy(deep=True)
        stripped.spec.tools.allow = [t for t in stripped.spec.tools.allow if t != "act_tapeout"]
        original_compiled = sc.compiled
        sc.compiled = dc_replace(original_compiled, agent_plugins={"product-copilot": stripped})
        try:
            async with sc.sessionmaker() as s:
                report = await sc.eval_runner.run(s, suite)
            case = report["cases"][0]
            assert not case["ok"], case
            assert case["actual"] == ["ok", "denied"]
        finally:
            sc.compiled = original_compiled
