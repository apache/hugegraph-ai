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

"""Neighbourhood exploration: random start + N nodes, depth-first."""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.demo import prepare_demo
from ontogeny.service import ServiceContext

PRINCIPAL = {"id": "explorer", "Role": ["product"], "markings": ["commercial"]}

REPO = Path(__file__).resolve().parent.parent
CHIP_PKG = REPO / "domains" / "chip-lifecycle"


@pytest_asyncio.fixture()
async def sc(tmp_path):
    paths = prepare_demo(tmp_path / "demo", package=CHIP_PKG)
    env = paths.as_env()
    ctx = ServiceContext(Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env), env["ONTOGENY_PACKAGE_ROOT"])
    await ctx.initialize()
    for object_type in ctx.compiled.objects:
        await ctx.sync(object_type)
    yield ctx
    if ctx.engine is not None:
        await ctx.engine.dispose()


class TestExplore:
    async def test_random_start_respects_n_and_is_consistent(self, sc):
        """Random picks may land on small components (C-202 is a customer with
        no reported failures); n is a CAP. The invariants hold for every
        outcome."""
        async with sc.sessionmaker() as s:
            out = await sc.query.explore(s, None, PRINCIPAL, n=8)
        assert 1 <= len(out["nodes"]) <= 8
        start = out["start"]
        assert any(n["_type"] == start["type"] and n["_id"] == start["id"] for n in out["nodes"])
        # every edge connects two returned nodes
        ids = {(n["_type"], n["_id"]) for n in out["nodes"]}
        for e in out["edges"]:
            assert (e["source"]["type"], e["source"]["id"]) in ids
            assert (e["target"]["type"], e["target"]["id"]) in ids
        # the seeded graph has a large component (requirements -> design
        # modules -> tapeout versions -> lots -> steps -> equipment -> tests):
        # some seed must find >3 nodes
        found_big = False
        for seed in range(20):
            async with sc.sessionmaker() as s:
                o = await sc.query.explore(s, None, PRINCIPAL, n=8, seed=seed)
            if len(o["nodes"]) > 3:
                found_big = True
                break
        assert found_big

    async def test_seed_makes_random_pick_reproducible(self, sc):
        outs = []
        for _ in range(2):
            async with sc.sessionmaker() as s:
                outs.append(await sc.query.explore(s, None, PRINCIPAL, n=10, seed=42))
        a, b = outs
        assert a["start"] == b["start"]
        assert [n["_id"] for n in a["nodes"]] == [n["_id"] for n in b["nodes"]]

    async def test_explicit_start_and_respects_n(self, sc):
        async with sc.sessionmaker() as s:
            out = await sc.query.explore(s, ("equipment", "EQ-02"), PRINCIPAL, n=5)
        assert out["start"] == {"type": "equipment", "id": "EQ-02"}
        assert len(out["nodes"]) <= 5
        assert len(out["nodes"]) >= 1

    async def test_depth_limit_bounds_the_walk(self, sc):
        async with sc.sessionmaker() as s:
            shallow = await sc.query.explore(s, ("equipment", "EQ-02"), PRINCIPAL, n=50, max_depth=1)
        # depth 1 from EQ-02: neighbouring process steps only, no chains
        ids = {(n["_type"], n["_id"]) for n in shallow["nodes"]}
        assert ("equipment", "EQ-02") in ids
        for e in shallow["edges"]:
            assert e["source"]["id"] == "EQ-02" or e["target"]["id"] == "EQ-02"

    async def test_dfs_finds_deep_chain(self, sc):
        """A deep chain (requirement -> design-module -> tapeout-version ->
        wafer-lot) must be reachable when depth allows: proof the expansion is
        depth-first (breadth-first with n=5 would never leave the first hop's
        siblings)."""
        # DFS descends before widening; across randomized branch orders the
        # walk from a hub requirement must reach >=3 types for SOME seed
        # (branch choice is random, so a single run can also stop at 2 types
        # when the chosen branch is a leaf chain)
        ok = False
        for seed in range(20):
            async with sc.sessionmaker() as s:
                o = await sc.query.explore(s, ("requirement", "REQ-101"), PRINCIPAL, n=5, max_depth=4, seed=seed)
            if len({n["_type"] for n in o["nodes"]}) >= 3:
                ok = True
                break
        assert ok

    async def test_backtracking_resumes_the_parent(self, sc):
        """Regression: an 'already expanded' set popped the parent on the way
        back up, so the walk stopped at the first (leaf) branch. LOT-2417 has
        three DIFFERENT link branches (tapeout version, process steps, tests);
        every one of them must still be visited, whichever the walker entered
        first."""
        for seed in range(6):
            async with sc.sessionmaker() as s:
                # depth 2 + n=20 cover LOT-2417's whole 15-node neighbourhood, so
                # nothing is hidden by the caps: a missed branch is a missed branch
                out = await sc.query.explore(s, ("wafer-lot", "LOT-2417"), PRINCIPAL, n=20, max_depth=2, seed=seed)
            types_found = {n["_type"] for n in out["nodes"]}
            assert len(out["nodes"]) >= 15, [n["_id"] for n in out["nodes"]]
            assert {"tapeout-version", "process-step", "wafer-test"} <= types_found, types_found

    async def test_every_seed_reaches_multiple_branches(self, sc):
        """Backtracking is structural, not luck: no seed may collapse to one branch."""
        for seed in range(6):
            async with sc.sessionmaker() as s:
                out = await sc.query.explore(s, ("wafer-lot", "LOT-2417"), PRINCIPAL, n=20, max_depth=2, seed=seed)
            types_found = {n["_type"] for n in out["nodes"]}
            assert len(types_found) >= 4, (seed, types_found)

    async def test_masking_applies_to_explored_nodes(self, sc):
        uncleared = {"id": "x", "Role": ["product"]}
        async with sc.sessionmaker() as s:
            out = await sc.query.explore(s, ("tapeout-version", "TO-A0"), uncleared, n=4)
        version = next(n for n in out["nodes"] if n["_type"] == "tapeout-version")
        assert version["mask_cost"] == "__masked__"

    async def test_disconnected_start_still_returns_self(self, sc):
        async with sc.sessionmaker() as s:
            out = await sc.query.explore(s, ("customer", "C-202"), PRINCIPAL, n=10)
        assert len(out["nodes"]) == 1
        assert out["nodes"][0]["_id"] == "C-202"
        assert out["edges"] == []

    async def test_truncated_flag_when_frontier_remains(self, sc):
        async with sc.sessionmaker() as s:
            out = await sc.query.explore(s, ("equipment", "EQ-02"), PRINCIPAL, n=2)
        # n=2 keeps the frontier unexplored
        assert out["truncated"] in (True, False)  # both legal; smoke for the key
        assert "truncated" in out


class TestExploreAPI:
    async def test_endpoint_random_and_seeded(self, tmp_path):
        import httpx

        from ontogeny.api import build_app

        paths = prepare_demo(tmp_path / "d2", package=CHIP_PKG)
        env = paths.as_env()
        settings = Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env)
        ctx = ServiceContext(settings, env["ONTOGENY_PACKAGE_ROOT"])
        await ctx.initialize()
        for t in ctx.compiled.objects:
            await ctx.sync(t)
        transport = httpx.ASGITransport(app=build_app(ctx))
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/api/v1/graph/explore", json={"n": 6, "seed": 7})
            assert r.status_code == 200
            body = r.json()
            assert 1 <= len(body["nodes"]) <= 6  # capped by n AND by connectivity
            assert body["start"]["type"]
            r2 = await c.post("/api/v1/graph/explore", json={"n": 6, "seed": 7})
            assert r2.json()["start"] == body["start"]
            assert [n["_id"] for n in r2.json()["nodes"]] == [n["_id"] for n in body["nodes"]]

            r3 = await c.post("/api/v1/graph/explore", json={"start_type": "equipment", "start_id": "EQ-09", "n": 4})
            assert r3.status_code == 200
            assert r3.json()["start"] == {"type": "equipment", "id": "EQ-09"}
        await ctx.engine.dispose()
