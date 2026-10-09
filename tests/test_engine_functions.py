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
"""Query service (assembly/derived/masking/traverse) + function sandbox."""
from __future__ import annotations

import sqlite3

import pytest
import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.db import init_schema, make_engine, make_sessionmaker
from ontogeny.engine import QueryService
from ontogeny.errors import SandboxError
from ontogeny.functions import FunctionSandbox
from ontogeny.policy import PolicyEngine
from ontogeny.registry import RegistryService
from ontogeny.stores import ObjectRepository, SyncEngine
from ontogeny.stores.sources import make_source

SUPER = {"id": "u", "Role": {"planner"}, "site": "plant-north"}
OUTSIDER = {"id": "v", "Role": {"visitor"}}


@pytest_asyncio.fixture()
async def env(golden_pkg_path, tmp_path):
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL (same path the
    # demo bootstrap uses), so tests always agree with the shipped example
    from ontogeny.demo.bootstrap import seed_from_package

    seed_from_package(golden_pkg_path, src, force=True)

    settings = Settings(env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"})
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    maker = make_sessionmaker(engine)
    pkg = load_package(golden_pkg_path)
    async with maker() as s:
        compiled = await RegistryService().publish(s, pkg)
        await s.commit()
    repo = ObjectRepository(compiled)
    sync = SyncEngine(compiled, settings, repo,
                      lambda st: make_source(st, settings.resolve_env_ref(st.spec.connection)))
    async with maker() as s:
        await repo.ensure(s)
        for t in compiled.objects:
            await sync.sync(s, t)
        await s.commit()
    query = QueryService(compiled, repo, PolicyEngine(compiled))
    sandbox = FunctionSandbox(compiled, repo, timeout_s=15)
    yield {"maker": maker, "compiled": compiled, "repo": repo, "query": query,
           "sandbox": sandbox, "pkg": pkg}
    await engine.dispose()


@pytest_asyncio.fixture()
async def join_env(tmp_path):
    """A minimal package for the one link shape product-manufacturing does not
    exercise: a MANY_TO_MANY join table whose membership is ontology-owned."""
    from pathlib import Path

    root = tmp_path / "join-pkg"
    root.mkdir()
    (root / "ontology.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Ontology\nmetadata: {name: join-table-demo}\n"
        "spec: {imports: []}\n",
        encoding="utf-8",
    )
    (root / "stores").mkdir()
    (root / "stores" / "mes.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Store\nmetadata: {name: mes}\n"
        "spec: {type: sqlite, connection: '${ERP_DSN}', access: read-write}\n",
        encoding="utf-8",
    )
    (root / "objects").mkdir()
    for name, table in (("container", "containers"), ("item", "items")):
        (root / "objects" / f"{name}.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: ObjectType\n"
            f"metadata: {{name: {name}}}\n"
            "spec:\n"
            f"  primaryKey: [{name}_id]\n"
            "  properties:\n"
            f"    {name}_id: {{type: string, required: true}}\n"
            "    name: {type: string}\n"
            "  backing:\n"
            "    store: mes\n"
            "    mode: materialized\n"
            "    source: {schema: mes, table: " + table + "}\n"
            "    mapping: {}\n",
            encoding="utf-8",
        )
    (root / "links").mkdir()
    (root / "links" / "container-items.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: LinkType\nmetadata: {name: container-items}\n"
        "spec:\n"
        "  source: container\n"
        "  target: item\n"
        "  cardinality: MANY_TO_MANY\n"
        "  join:\n"
        "    kind: join-table\n"
        "    store: mes\n"
        "    relation: {schema: mes, table: container_items}\n"
        "    keys:\n"
        "      source: {container_id: container_id}\n"
        "      target: {item_id: item_id}\n",
        encoding="utf-8",
    )

    src = tmp_path / "join.db"
    con = sqlite3.connect(str(src))
    con.executescript(
        """
        CREATE TABLE containers (container_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE items (item_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE container_items (container_id TEXT, item_id TEXT);
        INSERT INTO containers VALUES ('C-1', 'Crate');
        INSERT INTO items VALUES ('I-1', 'Bolt');
        INSERT INTO items VALUES ('I-2', 'Nut');
        """
    )
    con.commit()
    con.close()

    settings = Settings(env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"})
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    maker = make_sessionmaker(engine)
    pkg = load_package(str(Path(root)))
    async with maker() as s:
        compiled = await RegistryService().publish(s, pkg)
        await s.commit()
    repo = ObjectRepository(compiled)
    sync = SyncEngine(compiled, settings, repo,
                      lambda st: make_source(st, settings.resolve_env_ref(st.spec.connection)))
    async with maker() as s:
        await repo.ensure(s)
        await sync.sync(s, "container")
        await sync.sync(s, "item")
        await s.commit()
    query = QueryService(compiled, repo, PolicyEngine(compiled))
    yield {"maker": maker, "compiled": compiled, "repo": repo, "query": query}
    await engine.dispose()


class TestQuery:
    async def test_filter_and_masking(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            out = await q.query(s, "material", SUPER,
                                filt={"field": "material_id", "op": "eq", "value": "M-101"})
            assert out["total"] == 1
            assert out["objects"][0]["unit_cost"] == "__masked__"  # marking hidden for SUPER

            out2 = await q.query(s, "material", {"id": "claim", "markings": ["internal"]},
                                 filt={"material_id": "M-102"})
            assert out2["total"] == 1
            assert out2["objects"][0]["unit_cost"] == 8.5

    async def test_derived_property_computed(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            obj = await q.get(s, "production-order", "PO-1004", SUPER)
        assert obj["status"] == "COMPLETED"
        assert obj["release_lag_h"] == pytest.approx(24.0)  # (released_at-created_at)/3600000

    async def test_link_expansion_fk(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            out = await q.query(s, "work-center", SUPER,
                                filt={"work_center_id": "WC-01"}, links=["operation-work-center"])
            linked = out["links"]["operation-work-center"]["WC-01"]
            assert {o["operation_id"] for o in linked} == {"OP-2001", "OP-2002", "OP-2301"}

            inspections = await q.links(s, "production-order", "PO-1003",
                                        "production-order-inspections", SUPER)
            assert [i["inspection_id"] for i in inspections] == ["QI-3001"]

    async def test_link_expansion_over_a_join_table(self, join_env):
        """The join-table link shape: membership lives in a relation table and is
        written by the engine (repo.link_add), not by a source-system FK."""
        import datetime as dt

        q, repo = join_env["query"], join_env["repo"]
        async with join_env["maker"]() as s:
            # ontology-owned link membership (join table is engine-managed)
            await repo.link_add(s, "container-items", "C-1", "I-2",
                                dt.datetime.now(dt.timezone.utc))
            await s.commit()
            members = await repo.link_members(s, "container-items", src_id="C-1")
        assert members == [("C-1", "I-2")]

        async with join_env["maker"]() as s:
            items = await q.links(s, "container", "C-1", "container-items", SUPER)
        assert [i["item_id"] for i in items] == ["I-2"]

    async def test_aggregate(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            n = await q.aggregate(s, "production-order", SUPER, "count", None)
            assert n == 4.0
            n_planned = await q.aggregate(s, "production-order", SUPER, "count", None,
                                          filt={"status": "PLANNED"})
            assert n_planned == 1.0  # PO-1002; the rest are RELEASED/COMPLETED

    async def test_traverse_three_hops(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            out = await q.traverse(s, "material", ["M-103"], SUPER, [
                {"link": "bom-material", "direction": "out"},
                {"link": "bom-product", "direction": "in"},
            ])
        assert [s_["type"] for s_ in out["steps"]] == ["material", "bom", "product"]
        assert out["final_ids"] == ["P-200"]


class TestSandbox:
    async def test_query_within_capability(self, env, tmp_path):
        fn = env["pkg"].find("Function", "capacity-check")
        async with env["maker"]() as s:
            value = await env["sandbox"].run(s, fn, {"work_center_id": "WC-01", "qty": 10})
        assert value["work_center_id"] == "WC-01"
        assert value["daily_capacity"] == 800  # 400 per shift x 2 shifts
        assert value["open_orders"] == 3       # PO-1001..PO-1003 still open
        assert value["ok"] is True

    async def test_capability_denied(self, env, tmp_path):
        fn = env["pkg"].find("Function", "capacity-check")
        # strip the read-objects capability -> query must be denied
        fn.spec.capabilities = []
        async with env["maker"]() as s:
            with pytest.raises(SandboxError, match="capability denied"):
                await env["sandbox"].run(s, fn, {"work_center_id": "WC-01", "qty": 10})

    async def test_timeout_kills_runaway(self, env, tmp_path):
        from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, ParamDef, ResourceMeta

        bad = tmp_path / "bad.py"
        bad.write_text("import time\ndef spin(x):\n    time.sleep(60)\n    return 1\n", encoding="utf-8")
        fr = FunctionResource(
            apiVersion="ontogeny/v1", kind="Function",
            metadata=ResourceMeta(name="spin"),
            spec=FunctionSpec(
                runtime="python", entry=f"{bad}:spin",
                parameters={"x": ParamDef(type="integer")},
                capabilities=[Capability(**{"read-objects": ["production-order"]})],
            ),
        )
        sandbox = FunctionSandbox(env["compiled"], env["repo"], timeout_s=1.5)
        async with env["maker"]() as s:
            with pytest.raises(SandboxError, match="wall clock"):
                await sandbox.run(s, fr, {"x": 1})

    def test_llm_capability_buys_wall_clock(self, env):
        """A function that declares ``llm`` must outlive a model round trip.

        Regression: the sandbox wall clock was a flat 10s while a 27B model over
        the network answers in 10s+, so every `ontogeny.llm` call in a function was
        killed before its reply arrived — the capability was declared, enforced
        and unusable. The declared call budget now buys the time it needs.
        """
        from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, ResourceMeta

        def fn(caps):
            return FunctionResource(
                apiVersion="ontogeny/v1", kind="Function",
                metadata=ResourceMeta(name="f"),
                spec=FunctionSpec(runtime="python", entry="x.py:main",
                                  parameters={}, capabilities=caps),
            )

        sandbox = FunctionSandbox(env["compiled"], env["repo"],
                                  timeout_s=10.0, llm_call_timeout_s=60.0)
        # no llm capability: the original tight budget, unchanged
        assert sandbox._budget(fn([])) == 10.0
        # a declared call budget buys one call timeout per permitted call
        assert sandbox._budget(fn([Capability(**{"llm": True})])) == 10.0 + 10 * 60.0
        assert sandbox._budget(fn([Capability(**{"llm": {"max-calls": 2}})])) == 10.0 + 2 * 60.0
        # read-objects alone does not buy anything
        assert sandbox._budget(fn([Capability(**{"read-objects": ["work-center"]})])) == 10.0


class TestFunctionSourceEndpoint:
    """`GET /functions/{name}/source`: what code actually runs.

    The DSL only names the file; the console needs to be able to answer "what
    runs here?" — and, when a function was declared on the canvas without its
    file ever being written, to say so instead of leaving an opaque sandbox
    failure at invoke time.
    """

    async def test_reports_the_file_and_its_text(self, client):
        c, sc = client
        # a real file for a real function in the domain package
        entry = sc.compiled.functions["capacity-check"].spec.entry
        assert entry.endswith(".py:capacity_check")
        r = await c.get("/api/v1/functions/capacity-check/source")
        assert r.status_code == 200
        body = r.json()
        assert body["exists"] is True
        assert body["path"].endswith("functions/capacity.py")
        assert "def capacity_check" in body["source"]

    async def test_missing_file_is_reported_not_hidden(self, client, tmp_path):
        from ontogeny.core.models import FunctionResource, FunctionSpec, ResourceMeta

        c, sc = client
        sc.compiled.functions["ghost"] = FunctionResource(
            apiVersion="ontogeny/v1", kind="Function",
            metadata=ResourceMeta(name="ghost"),
            spec=FunctionSpec(runtime="python", entry="nobody_wrote_this.py:main"),
        )
        r = await c.get("/api/v1/functions/ghost/source")
        assert r.status_code == 200
        body = r.json()
        assert body["exists"] is False and body["source"] is None
        assert body["path"].endswith("functions/nobody_wrote_this.py")
