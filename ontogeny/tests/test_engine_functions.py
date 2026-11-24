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

SUPER = {"id": "u", "Role": {"product"}, "site": "hq"}
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
    sync = SyncEngine(
        compiled, settings, repo, lambda st: make_source(st, settings.resolve_env_ref(st.spec.connection))
    )
    async with maker() as s:
        await repo.ensure(s)
        for t in compiled.objects:
            await sync.sync(s, t)
        await s.commit()
    query = QueryService(compiled, repo, PolicyEngine(compiled))
    sandbox = FunctionSandbox(compiled, repo, timeout_s=15)
    yield {"maker": maker, "compiled": compiled, "repo": repo, "query": query, "sandbox": sandbox, "pkg": pkg}
    await engine.dispose()


@pytest_asyncio.fixture()
async def join_env(tmp_path, request):
    """Exercise text-backed membership with configurable endpoint types."""
    from pathlib import Path

    src_key, dst_key, join_kind = getattr(request, "param", ("string", "string", "join-table"))
    root = tmp_path / "join-pkg"
    root.mkdir()
    (root / "ontology.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Ontology\nmetadata: {name: join-table-demo}\nspec: {imports: []}\n",
        encoding="utf-8",
    )
    (root / "stores").mkdir()
    (root / "stores" / "mes.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Store\nmetadata: {name: mes}\n"
        "spec: {type: sqlite, connection: '${ERP_DSN}', access: read-write}\n",
        encoding="utf-8",
    )
    (root / "objects").mkdir()
    for name, table, key_type in (("container", "containers", src_key), ("item", "items", dst_key)):
        (root / "objects" / f"{name}.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: ObjectType\n"
            f"metadata: {{name: {name}}}\n"
            "spec:\n"
            f"  primaryKey: [{name}_id]\n"
            "  properties:\n"
            f"    {name}_id: {{type: {key_type}, required: true}}\n"
            "    name: {type: string}\n"
            "  backing:\n"
            "    store: mes\n"
            "    mode: materialized\n"
            "    source: {schema: mes, table: " + table + "}\n"
            "    mapping: {}\n",
            encoding="utf-8",
        )
    (root / "links").mkdir()
    join_table = (
        "    kind: join-table\n"
        "    store: mes\n"
        "    relation: {schema: mes, table: container_items}\n"
        "    keys:\n"
        "      source: {container_id: container_id}\n"
        "      target: {item_id: item_id}\n"
    )
    (root / "links" / "container-items.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: LinkType\nmetadata: {name: container-items}\n"
        "spec:\n"
        "  source: container\n"
        "  target: item\n"
        "  cardinality: MANY_TO_MANY\n"
        "  join:\n" + (join_table if join_kind == "join-table" else "    kind: extracted\n"),
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
        INSERT INTO containers VALUES ('C-2', 'Bin');
        INSERT INTO items VALUES ('I-1', 'Bolt');
        INSERT INTO items VALUES ('I-2', 'Nut');
        INSERT INTO items VALUES ('I-3', 'Washer');
        INSERT INTO items VALUES ('I-4', 'Screw');
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
    sync = SyncEngine(
        compiled, settings, repo, lambda st: make_source(st, settings.resolve_env_ref(st.spec.connection))
    )
    async with maker() as s:
        await repo.ensure(s)
        if src_key == dst_key == "string":
            await sync.sync(s, "container")
            await sync.sync(s, "item")
        await s.commit()
    query = QueryService(compiled, repo, PolicyEngine(compiled))
    yield {"maker": maker, "compiled": compiled, "repo": repo, "query": query, "join_kind": join_kind}
    await engine.dispose()


class TestQuery:
    async def test_filter_and_masking(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            out = await q.query(s, "tapeout-version", SUPER, filt={"field": "version_id", "op": "eq", "value": "TO-A0"})
            assert out["total"] == 1
            assert out["objects"][0]["mask_cost"] == "__masked__"  # marking hidden for SUPER

            out2 = await q.query(
                s, "tapeout-version", {"id": "claim", "markings": ["internal"]}, filt={"version_id": "TO-A1"}
            )
            assert out2["total"] == 1
            assert out2["objects"][0]["mask_cost"] == 420000.0

    async def test_derived_property_computed(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            obj = await q.get(s, "tapeout-version", "TO-A0", SUPER)
        assert obj["status"] == "FAB"
        assert obj["fab_lag_h"] == pytest.approx(936.0)  # (taped_out_at-created_at)/3600000

    async def test_link_expansion_fk(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            out = await q.query(s, "equipment", SUPER, filt={"equipment_id": "EQ-02"}, links=["step-equipment"])
            linked = out["links"]["step-equipment"]["EQ-02"]
            assert {o["step_id"] for o in linked} == {"PS-7111", "PS-7121", "PS-7131"}

            tests = await q.links(s, "wafer-lot", "LOT-2417", "lot-tests", SUPER)
            assert [i["test_id"] for i in tests] == ["WT-501"]

    async def test_link_expansion_over_a_join_table(self, join_env):
        """The join-table link shape: membership lives in a relation table and is
        written by the engine (repo.link_add), not by a source-system FK."""
        import datetime as dt

        q, repo = join_env["query"], join_env["repo"]
        async with join_env["maker"]() as s:
            # ontology-owned link membership (join table is engine-managed)
            await repo.link_add(s, "container-items", "C-1", "I-2", dt.datetime.now(dt.UTC))
            await s.commit()
            members = await repo.link_members(s, "container-items", src_id="C-1")
        assert members == [("C-1", "I-2")]

        async with join_env["maker"]() as s:
            items = await q.links(s, "container", "C-1", "container-items", SUPER)
        assert [i["item_id"] for i in items] == ["I-2"]

    @pytest.mark.parametrize(
        "join_env", [("integer", "timestamp", "join-table"), ("integer", "timestamp", "extracted")], indirect=True
    )
    async def test_text_backed_links_resolve_typed_anchor_aliases(self, join_env):
        import datetime as dt

        q, repo = join_env["query"], join_env["repo"]
        now = dt.datetime.now(dt.UTC)
        canonical = dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC)
        legacy_item = dt.datetime(2026, 1, 2, 12, tzinfo=dt.UTC)
        offset = "2026-01-01T20:00:00+08:00"
        link = "container-items"
        async with join_env["maker"]() as s:
            await repo.action_insert(s, "container", {"container_id": 42}, now)
            await repo.action_insert(s, "item", {"item_id": canonical}, now)
            if join_env["join_kind"] == "extracted":
                await repo.link_assert(s, link, "42", str(canonical), {"doc_id": "document"}, now)
            else:
                await repo.link_add(s, link, "42", str(canonical), now)

            assert await repo.link_members_by_ids(s, link, ["0042", "42", "99"], from_source=True) == {
                "0042": [str(canonical)],
                "42": [str(canonical)],
                "99": [],
            }
            assert await repo.link_members_by_ids(s, link, [offset], from_source=False) == {offset: ["42"]}
            assert [item["item_id"] for item in await q.links(s, "container", "0042", link, SUPER)] == [canonical]
            assert [obj["container_id"] for obj in await q.links(s, "item", offset, link, SUPER)] == [42]

            # Existing raw spellings are still addressable, and a second
            # spelling of the same edge must not duplicate its related object.
            await repo.link_add(s, link, "0042", str(canonical), now)
            await repo.action_insert(s, "item", {"item_id": legacy_item}, now)
            await repo.link_add(s, link, "0042", str(legacy_item), now)
            members = await repo.link_members_by_ids(s, link, ["0042"], from_source=True)
            assert sorted(members["0042"]) == [str(canonical), str(legacy_item)]
            assert sorted(item["item_id"] for item in await q.links(s, "container", "0042", link, SUPER)) == [
                canonical,
                legacy_item,
            ]

    async def test_text_backed_links_distinguish_string_ids_with_leading_zeros(self, join_env):
        import datetime as dt

        repo = join_env["repo"]
        now = dt.datetime.now(dt.UTC)
        async with join_env["maker"]() as s:
            await repo.link_add(s, "container-items", "0042", "I-1", now)
            await repo.link_add(s, "container-items", "42", "I-2", now)
            assert await repo.link_members_by_ids(s, "container-items", ["0042", "42"], from_source=True) == {
                "0042": ["I-1"],
                "42": ["I-2"],
            }

    async def test_link_expansion_batches_fk_reads(self, env, monkeypatch):
        """Expand only the anchors on the requested page for a foreign key."""
        q, repo = env["query"], env["repo"]
        async with env["maker"]() as s:
            baseline = await q.query(s, "equipment", SUPER, limit=2)
            expected = {}
            for obj in baseline["objects"]:
                rows = await q.links(s, "equipment", obj["equipment_id"], "step-equipment", SUPER)
                expected[obj["equipment_id"]] = sorted(r["step_id"] for r in rows)

            calls = []

            async def forbidden(*args, **kwargs):
                raise AssertionError("list expansion must use scoped membership reads")

            real_members = repo.link_members_by_ids

            async def counting_members(session, link_name, ids, *, from_source):
                calls.append((list(ids), from_source))
                return await real_members(session, link_name, ids, from_source=from_source)

            monkeypatch.setattr(repo, "fk_linked_ids", forbidden)
            monkeypatch.setattr(repo, "fk_link_pairs", forbidden)
            monkeypatch.setattr(repo, "link_members_by_ids", counting_members)
            out = await q.query(s, "equipment", SUPER, limit=2, links=["step-equipment"])

        expanded = out["links"]["step-equipment"]
        assert {pid: sorted(o["step_id"] for o in rows) for pid, rows in expanded.items()} == expected
        assert calls == [(list(expected), True)]

    async def test_link_expansion_batches_join_reads(self, join_env, monkeypatch):
        """Bound membership and object reads without changing the page's results."""
        import datetime as dt

        from sqlalchemy import event

        q, repo = join_env["query"], join_env["repo"]
        fixed_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        async with join_env["maker"]() as s:
            await repo.link_add(s, "container-items", "C-1", "I-2", fixed_at)
            await repo.link_add(s, "container-items", "C-1", "I-1", fixed_at)
            await repo.link_add(s, "container-items", "C-2", "I-3", fixed_at)
            # Dangling target: both the per-object and the batched path must
            # drop it during assembly.
            await repo.link_add(s, "container-items", "C-2", "I-404", fixed_at)
            await s.commit()

        async with join_env["maker"]() as s:
            # Baseline on the same snapshot: per-object link reads.
            containers = await q.query(s, "container", SUPER)
            expected = {}
            for obj in containers["objects"]:
                rows = await q.links(s, "container", obj["container_id"], "container-items", SUPER)
                expected[obj["container_id"]] = sorted(r["item_id"] for r in rows)

            calls = []
            loads = []
            real_members = repo.link_members_by_ids
            real_get_many = repo.get_many

            async def counting_members(session, link_name, ids, *, from_source):
                calls.append((list(ids), from_source))
                return await real_members(session, link_name, ids, from_source=from_source)

            async def counting_loads(session, object_type, ids):
                loads.append(len(ids))
                return await real_get_many(session, object_type, ids)

            monkeypatch.setattr(repo, "link_members_by_ids", counting_members)
            monkeypatch.setattr(repo, "get_many", counting_loads)
            monkeypatch.setattr("ontogeny.engine.service._LINKED_OBJECT_BATCH_SIZE", 2)
            monkeypatch.setattr("ontogeny.stores.repo._LINK_MEMBER_BATCH_SIZE", 1)

            link_table = repo.compiled.link_table("container-items")
            membership_parameters = []

            def capture_membership(_conn, _cursor, statement, parameters, _context, _executemany):
                if link_table in statement:
                    membership_parameters.append(parameters)

            conn = await s.connection()
            event.listen(conn.sync_connection, "before_cursor_execute", capture_membership)
            out = await q.query(s, "container", SUPER, links=["container-items"])
            empty = await q.query(s, "container", SUPER, offset=2, links=["container-items"])

        expanded = out["links"]["container-items"]
        actual = {cid: sorted(item["item_id"] for item in items) for cid, items in expanded.items()}
        assert actual == expected
        assert expected == {"C-1": ["I-1", "I-2"], "C-2": ["I-3"]}
        assert empty["links"] == {"container-items": {}}
        assert calls == [(list(expected), True), ([], True)]
        assert membership_parameters == [("C-1",), ("C-2",)]
        assert loads == [2, 2]

    async def test_aggregate(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            n = await q.aggregate(s, "wafer-lot", SUPER, "count", None)
            assert n == 4.0
            n_running = await q.aggregate(s, "wafer-lot", SUPER, "count", None, filt={"status": "RUNNING"})
            assert n_running == 2.0  # LOT-2419 and LOT-2501; the rest are COMPLETE
            assert await q.aggregate(s, "wafer-lot", SUPER, "count", None, filt={"lot_id": "NONEXISTENT-LOT"}) == 0
            for fn in ("sum", "avg", "min", "max"):
                assert (
                    await q.aggregate(s, "wafer-lot", SUPER, fn, "qty_wafers", filt={"lot_id": "NONEXISTENT-LOT"})
                    is None
                )

    async def test_traverse_three_hops(self, env):
        q = env["query"]
        async with env["maker"]() as s:
            out = await q.traverse(
                s,
                "requirement",
                ["REQ-101"],
                SUPER,
                [
                    {"link": "requirement-modules", "direction": "out"},
                    {"link": "version-includes", "direction": "in"},
                    {"link": "version-lots", "direction": "out"},
                ],
            )
        assert [s_["type"] for s_ in out["steps"]] == ["requirement", "design-module", "tapeout-version", "wafer-lot"]
        assert sorted(out["final_ids"]) == ["LOT-2417", "LOT-2418", "LOT-2419"]

    async def test_traverse_batches_fk_reads_per_hop(self, env, monkeypatch):
        q, repo = env["query"], env["repo"]
        calls = []
        real_members = repo.link_members_by_ids

        async def counting_members(session, link_name, ids, *, from_source):
            calls.append((link_name, list(ids), from_source))
            return await real_members(session, link_name, ids, from_source=from_source)

        monkeypatch.setattr(repo, "link_members_by_ids", counting_members)
        async with env["maker"]() as s:
            out = await q.traverse(
                s,
                "equipment",
                ["EQ-02", "EQ-07"],
                SUPER,
                [
                    {"link": "step-equipment", "direction": "out"},
                    {"link": "step-equipment", "direction": "in"},
                ],
            )

        assert calls == [
            ("step-equipment", ["EQ-02", "EQ-07"], True),
            ("step-equipment", out["steps"][1]["ids"], False),
        ]
        assert sorted(out["steps"][1]["ids"]) == ["PS-7111", "PS-7112", "PS-7121", "PS-7131", "PS-7132"]
        assert sorted(out["final_ids"]) == ["EQ-02", "EQ-07"]
        pairs = {(edge["source"]["id"], edge["target"]["id"]) for edge in out["edges"]}
        assert ("EQ-02", "PS-7111") in pairs
        assert ("PS-7132", "EQ-07") in pairs
        assert ("EQ-02", "PS-7112") not in pairs

    async def test_traverse_join_table_in_both_directions(self, join_env):
        import datetime as dt

        q, repo = join_env["query"], join_env["repo"]
        now = dt.datetime.now(dt.UTC)
        async with join_env["maker"]() as s:
            await repo.link_add(s, "container-items", "C-1", "I-1", now)
            await repo.link_add(s, "container-items", "C-1", "I-2", now)
            await repo.link_add(s, "container-items", "C-2", "I-1", now)
            await repo.link_add(s, "container-items", "C-2", "I-3", now)
            await s.commit()
            out = await q.traverse(
                s,
                "container",
                ["C-1"],
                SUPER,
                [
                    {"link": "container-items", "direction": "out"},
                    {"link": "container-items", "direction": "in"},
                ],
            )

        assert sorted(out["steps"][1]["ids"]) == ["I-1", "I-2"]
        assert sorted(out["final_ids"]) == ["C-1", "C-2"]
        assert {(edge["source"]["id"], edge["target"]["id"]) for edge in out["edges"]} == {
            ("C-1", "I-1"),
            ("C-1", "I-2"),
            ("I-1", "C-1"),
            ("I-1", "C-2"),
            ("I-2", "C-1"),
        }


class TestSandbox:
    async def test_query_within_capability(self, env, tmp_path):
        fn = env["pkg"].find("Function", "analyze-yield-loss")
        async with env["maker"]() as s:
            value = await env["sandbox"].run(s, fn, {"test_id": "WT-501"})
        assert value["test_id"] == "WT-501"
        assert value["lot_id"] == "LOT-2417"
        assert value["lot_status"] == "COMPLETE"
        assert value["yield"] == 0.82  # 36 defects on 200 tested units
        assert value["loss"] == 0.18
        assert value["recommended_action"] == "HOLD"

    async def test_capability_denied(self, env, tmp_path):
        fn = env["pkg"].find("Function", "analyze-yield-loss")
        # strip the read-objects capability -> query must be denied
        fn.spec.capabilities = []
        async with env["maker"]() as s:
            with pytest.raises(SandboxError, match="capability denied"):
                await env["sandbox"].run(s, fn, {"test_id": "WT-501"})

    async def test_timeout_kills_runaway(self, env, tmp_path):
        from dataclasses import replace

        from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, ParamDef, ResourceMeta

        (tmp_path / "functions").mkdir()
        bad = tmp_path / "functions" / "bad.py"
        bad.write_text("import time\ndef spin(x):\n    time.sleep(60)\n    return 1\n", encoding="utf-8")
        fr = FunctionResource(
            apiVersion="ontogeny/v1",
            kind="Function",
            metadata=ResourceMeta(name="spin"),
            spec=FunctionSpec(
                runtime="python",
                entry="bad.py:spin",
                parameters={"x": ParamDef(type="integer")},
                capabilities=[Capability(**{"read-objects": ["wafer-lot"]})],
            ),
        )
        sandbox = FunctionSandbox(replace(env["compiled"], package_root=str(tmp_path)), env["repo"], timeout_s=1.5)
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
                apiVersion="ontogeny/v1",
                kind="Function",
                metadata=ResourceMeta(name="f"),
                spec=FunctionSpec(runtime="python", entry="x.py:main", parameters={}, capabilities=caps),
            )

        sandbox = FunctionSandbox(env["compiled"], env["repo"], timeout_s=10.0, llm_call_timeout_s=60.0)
        # no llm capability: the original tight budget, unchanged
        assert sandbox._budget(fn([])) == 10.0
        # a declared call budget buys one call timeout per permitted call
        assert sandbox._budget(fn([Capability(**{"llm": True})])) == 10.0 + 10 * 60.0
        assert sandbox._budget(fn([Capability(**{"llm": {"max-calls": 2}})])) == 10.0 + 2 * 60.0
        # read-objects alone does not buy anything
        assert sandbox._budget(fn([Capability(**{"read-objects": ["equipment"]})])) == 10.0


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
        entry = sc.compiled.functions["analyze-yield-loss"].spec.entry
        assert entry.endswith(".py:analyze_yield_loss")
        r = await c.get("/api/v1/functions/analyze-yield-loss/source")
        assert r.status_code == 200
        body = r.json()
        assert body["exists"] is True
        assert body["path"].endswith("functions/analyze_yield_loss.py")
        assert "def analyze_yield_loss" in body["source"]

    async def test_source_requires_admin(self, client):
        c, _ = client
        for identity in ("", '{"id": "ordinary", "is_admin": false}'):
            response = await c.get(
                "/api/v1/functions/analyze-yield-loss/source", headers={"X-Ontogeny-Principal": identity}
            )
            assert response.status_code == 403

    async def test_source_rejects_escape_even_for_admin(self, client, tmp_path):
        c, sc = client
        fn = sc.compiled.functions["analyze-yield-loss"]
        outside = tmp_path / "secret.py"
        secret = "ontogeny_unique_source_escape_marker_93f5"
        outside.write_text(secret, encoding="utf-8")
        for entry in (f"{outside}:main", "../../secret.py:main"):
            fn.spec.entry = entry
            response = await c.get("/api/v1/functions/analyze-yield-loss/source")
            assert response.status_code != 200
            assert secret not in response.text

    async def test_symlink_escape_rejected_by_validator_and_source(self, client, tmp_path):
        from pathlib import Path

        from ontogeny.core import load_package
        from ontogeny.core.validator import validate

        c, sc = client
        outside = tmp_path / "secret.py"
        secret = "ontogeny_unique_source_escape_marker_93f5"
        outside.write_text(secret, encoding="utf-8")
        (Path(sc.package_root) / "functions" / "outside.py").symlink_to(outside)
        pkg = load_package(sc.package_root)
        fn = next(fn for fn in pkg.functions() if fn.metadata.name == "analyze-yield-loss")
        fn.spec.entry = "outside.py:main"
        assert any(issue.code == "FN-ENTRY" for issue in validate(pkg).issues)
        sc.compiled.functions["analyze-yield-loss"].spec.entry = "outside.py:main"
        response = await c.get("/api/v1/functions/analyze-yield-loss/source")
        assert response.status_code != 200
        assert secret not in response.text

    async def test_missing_file_is_reported_not_hidden(self, client, tmp_path):
        from ontogeny.core.models import FunctionResource, FunctionSpec, ResourceMeta

        c, sc = client
        sc.compiled.functions["ghost"] = FunctionResource(
            apiVersion="ontogeny/v1",
            kind="Function",
            metadata=ResourceMeta(name="ghost"),
            spec=FunctionSpec(runtime="python", entry="nobody_wrote_this.py:main"),
        )
        r = await c.get("/api/v1/functions/ghost/source")
        assert r.status_code == 200
        body = r.json()
        assert body["exists"] is False and body["source"] is None
        assert body["path"].endswith("functions/nobody_wrote_this.py")
