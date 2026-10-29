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

"""Builder validation and publish failures preserve the complete live package."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest
import yaml

from ontogeny.builder_ops import builder_save
from ontogeny.errors import DSLValidationError


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _product(sc):
    return yaml.safe_load((Path(sc.package_root) / "objects/product.yaml").read_text())


async def test_invalid_rename_restores_deletes_sidecars_and_layout(client):
    _c, sc = client
    root = Path(sc.package_root)
    before = _tree(root)
    compiled = sc.compiled
    renamed = _product(sc)
    renamed["metadata"]["name"] = "renamed-product"
    renamed["spec"]["backing"]["store"] = "builder-store"
    renamed["spec"]["backing"]["store_spec"] = {"kind": "sqlite", "connection": "${ERP_DSN}"}
    policy = {
        "apiVersion": "ontogeny/v1",
        "kind": "PolicySet",
        "metadata": {"name": "new-policy"},
        "spec": {"language": "cedar", "source": "permit(principal, action, resource);"},
    }
    request = copy.deepcopy([renamed, policy])
    with pytest.raises(DSLValidationError):
        await builder_save(
            sc,
            request,
            deletes=["ObjectType/product", "PolicySet/default"],
            layout={"renamed-product": {"x": 10, "y": 20}},
        )
    assert _tree(root) == before
    assert sc.compiled is compiled
    # Extracting inline store declarations must not mutate the caller's input.
    assert request == [renamed, policy]


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_publish_failure_restores_all_changed_files(client, monkeypatch, failure):
    _c, sc = client
    root = Path(sc.package_root)
    before = _tree(root)
    product = _product(sc)
    product["metadata"]["description"] = "changed"
    policy = {
        "apiVersion": "ontogeny/v1",
        "kind": "PolicySet",
        "metadata": {"name": "new-policy"},
        "spec": {"language": "cedar", "source": "permit(principal, action, resource);"},
    }

    async def fail(*args, **kwargs):
        assert (root / "policies/new-policy.cedar").exists()
        assert not (root / "policies/default.cedar").exists()
        raise failure("injected publish failure")

    monkeypatch.setattr(sc, "publish", fail)
    with pytest.raises(failure, match="injected publish failure"):
        await builder_save(sc, [product, policy], deletes=["PolicySet/default"], layout={"product": {"x": 1, "y": 2}})
    assert _tree(root) == before


@pytest.mark.parametrize("fault", ["rebuild", "ensure", "commit"])
async def test_publish_failure_rolls_back_registry_runtime_and_files(client, monkeypatch, fault):
    _c, sc = client
    root = Path(sc.package_root)
    before = _tree(root)
    compiled, repo, query = sc.compiled, sc.repo, sc.query
    product = _product(sc)
    product["metadata"]["description"] = "candidate that cannot become active"
    rebuild = sc._rebuild_services

    def fail(candidate, **kwargs):
        rebuild(candidate, **kwargs)
        raise RuntimeError("injected rebuild failure")

    if fault == "rebuild":
        monkeypatch.setattr(sc, "_rebuild_services", fail)
    else:

        async def async_fail(*args, **kwargs):
            raise RuntimeError("injected publish failure")

        if fault == "ensure":
            from ontogeny.stores.repo import ObjectRepository

            monkeypatch.setattr(ObjectRepository, "ensure", async_fail)
        else:
            from sqlalchemy.ext.asyncio import AsyncSession

            monkeypatch.setattr(AsyncSession, "commit", async_fail)
    with pytest.raises(RuntimeError, match=r"injected .* failure"):
        await builder_save(sc, [product])
    assert _tree(root) == before
    assert sc.compiled is compiled and sc.repo is repo and sc.query is query
    async with sc.sessionmaker() as session:
        persisted = await sc.registry.load_latest(session)
    assert persisted.content_hash == compiled.content_hash


async def test_concurrent_failure_cannot_undo_a_successful_save(client, monkeypatch):
    _c, sc = client
    entered, release = asyncio.Event(), asyncio.Event()
    publish = sc.publish
    calls = 0

    async def fail_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
            raise RuntimeError("first save fails")
        return await publish(*args, **kwargs)

    monkeypatch.setattr(sc, "publish", fail_first)
    first, second = _product(sc), _product(sc)
    first["metadata"]["description"] = "first"
    second["metadata"]["description"] = "second"
    failing = asyncio.create_task(builder_save(sc, [first]))
    await entered.wait()
    succeeding = asyncio.create_task(builder_save(sc, [second]))
    await asyncio.sleep(0)
    assert calls == 1
    release.set()
    results = await asyncio.gather(failing, succeeding, return_exceptions=True)
    assert isinstance(results[0], RuntimeError)
    assert results[1]["published"] is True
    assert _product(sc)["metadata"]["description"] == "second"
    assert sc.compiled.objects["product"].metadata.description == "second"


async def test_manifest_symlink_is_rejected_before_writing(client):
    _c, sc = client
    root = Path(sc.package_root)
    manifest = root / "ontology.yaml"
    outside = root.parent / "manifest.yaml"
    manifest.rename(outside)
    manifest.symlink_to(outside)
    before = outside.read_bytes()
    with pytest.raises(DSLValidationError, match="symbolic links"):
        await builder_save(sc, [])
    assert manifest.is_symlink()
    assert outside.read_bytes() == before


async def test_partial_save_preserves_worktree_git_pointer(client):
    _c, sc = client
    pointer = Path(sc.package_root) / ".git"
    pointer.write_text("gitdir: /some/worktree/metadata\n")
    await builder_save(sc, [])
    assert pointer.read_text() == "gitdir: /some/worktree/metadata\n"


@pytest.mark.parametrize("commit_succeeds", [True, False])
async def test_candidate_runtime_and_tools_remain_hidden_until_commit(client, monkeypatch, commit_succeeds):
    from sqlalchemy.ext.asyncio import AsyncSession

    from ontogeny.mcp_server import McpSurface

    _c, sc = client
    surface = sc.mcp_surface = McpSurface(sc)
    surface.build()
    server = surface.server
    original_manager = server._tool_manager
    original_runtime = sc.compiled
    commit = AsyncSession.commit
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_commit(session):
        entered.set()
        await release.wait()
        if not commit_succeeds:
            raise RuntimeError("commit rejected")
        await commit(session)

    monkeypatch.setattr(AsyncSession, "commit", blocked_commit)
    added = _product(sc)
    added["metadata"]["name"] = "builder-product"
    save = asyncio.create_task(builder_save(sc, [added]))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        assert sc.compiled is original_runtime
        assert surface.server is server
        assert server._tool_manager is original_manager
        assert "search_builder_product" not in {tool.name for tool in await server.list_tools()}
    finally:
        release.set()
    if commit_succeeds:
        await save
        assert "builder-product" in sc.compiled.objects
        assert surface.server is server
        assert server._tool_manager is not original_manager
        assert "search_builder_product" in {tool.name for tool in await server.list_tools()}
    else:
        with pytest.raises(RuntimeError, match="commit rejected"):
            await save
        assert sc.compiled is original_runtime
        assert server._tool_manager is original_manager
        assert not (Path(sc.package_root) / "objects/builder-product.yaml").exists()
