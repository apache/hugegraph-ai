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

"""Post-merge rollback persists the registry before hot-swapping runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from ontogeny.core import load_package
from ontogeny.evolve import ProposalRow

PROPERTY = "rollback-probe"


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


async def _evaluated_proposal(sc, *, drift=True):
    root = Path(sc.package_root)
    for path in (root / "evals").glob("*.yaml"):
        path.unlink()
    suite = {
        "apiVersion": "ontogeny/v1",
        "kind": "EvalSuite",
        "metadata": {"name": "rollback-probe"},
        "spec": {
            "queries": [
                {
                    "name": "products-must-exist",
                    "query": {"object": "product"},
                    "expect": {"min_rows": 1},
                }
            ]
        },
    }
    (root / "evals/rollback-probe.yaml").write_text(yaml.safe_dump(suite))
    await sc.publish(str(root))
    await sc.sync("product")
    suite = sc.compiled.eval_suites["rollback-probe"]
    async with sc.sessionmaker() as session:
        report = await sc.eval_runner.run(session, suite)
    assert report["passed"] is True
    # A previously green evaluation can become stale due to data drift. The
    # real post-merge evaluator detects this and must undo the T0 mutation.
    async with sc.sessionmaker() as session:
        if drift:
            await session.execute(sc.repo._table("product").delete())
        proposal = ProposalRow(
            gap_kind="add-optional-property",
            rationale="rollback regression",
            status="evaluated",
            diff=[{"mutation": "add-optional-property", "object": "product", "prop": PROPERTY, "type": "string"}],
            eval_report={"passed": True, "suites": {"rollback-probe": report}},
        )
        session.add(proposal)
        await session.commit()
        return proposal.id


async def test_red_postmerge_eval_restores_committed_registry_runtime_and_files(client, monkeypatch):
    _c, sc = client
    pid = await _evaluated_proposal(sc)
    root = Path(sc.package_root)
    before, content_hash = _tree(root), sc.compiled.content_hash
    reload = sc.reload
    backup_at_reload = []

    async def check_backup_survives_reload():
        backup_at_reload.append(list(root.parent.glob(f"{root.name}.evolve-backup-*")))
        assert backup_at_reload[-1]
        if len(backup_at_reload) == 1:
            # Rollback restores the exact tree, including files created after
            # its backup was taken rather than just overwriting old resources.
            (root / "post-promotion-artifact.txt").write_text("candidate artifact")
        await reload()

    monkeypatch.setattr(sc, "reload", check_backup_survives_reload)
    result = await sc.evolve_promote(pid)
    assert result["status"] == "promoted_then_rolled_back"
    assert result["rollback"]["content_hash"] == content_hash
    assert _tree(root) == before
    assert sc.compiled.content_hash == content_hash
    assert PROPERTY not in sc.compiled.objects["product"].spec.properties
    assert len(backup_at_reload) == 2
    assert not Path(result["original"]["rollback_dir"]).exists()
    async with sc.sessionmaker() as session:
        persisted = await sc.registry.load_latest(session)
        proposal = await session.get(ProposalRow, pid)
    assert persisted.content_hash == content_hash
    assert PROPERTY not in persisted.objects["product"].spec.properties
    assert proposal.status == "rolled_back"


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_rollback_commit_failure_keeps_promoted_state_and_recovery_backup(client, monkeypatch, failure):
    _c, sc = client
    pid = await _evaluated_proposal(sc)
    root = Path(sc.package_root)
    commit = AsyncSession.commit
    commits = 0

    async def fail_rollback_commit(session):
        nonlocal commits
        commits += 1
        if commits == 2:
            assert list(root.parent.glob(f"{root.name}.evolve-backup-*"))
            raise failure("rollback commit failed")
        await commit(session)

    monkeypatch.setattr(AsyncSession, "commit", fail_rollback_commit)
    with pytest.raises(failure, match="rollback commit failed"):
        await sc.evolve_promote(pid)
    backups = list(root.parent.glob(f"{root.name}.evolve-backup-*"))
    assert len(backups) == 1
    assert PROPERTY not in load_package(backups[0]).find("ObjectType", "product").spec.properties
    assert PROPERTY in load_package(root).find("ObjectType", "product").spec.properties
    assert PROPERTY in sc.compiled.objects["product"].spec.properties
    async with sc.sessionmaker() as session:
        persisted = await sc.registry.load_latest(session)
        proposal = await session.get(ProposalRow, pid)
    assert persisted.content_hash == sc.compiled.content_hash
    assert PROPERTY in persisted.objects["product"].spec.properties
    assert proposal.status == "promoted"


async def test_successful_postmerge_eval_cleans_only_its_own_backup(client):
    _c, sc = client
    pid = await _evaluated_proposal(sc, drift=False)
    root = Path(sc.package_root)
    previous_backup = root.parent / f"{root.name}.evolve-backup-previous"
    previous_backup.mkdir()
    (previous_backup / "recovery.txt").write_text("keep for another pending recovery")
    result = await sc.evolve_promote(pid)
    assert result["status"] == "promoted"
    assert PROPERTY in sc.compiled.objects["product"].spec.properties
    assert not Path(result["rollback_dir"]).exists()
    assert (previous_backup / "recovery.txt").read_text() == "keep for another pending recovery"
