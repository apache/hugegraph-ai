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
"""Registry: publish (validate->persist->compile), cache, rebuild-from-DB."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from ontogeny.db import init_schema, make_engine, make_sessionmaker
from ontogeny.core import load_package
from ontogeny.registry import RegistryService, compile_package, snake
from ontogeny.errors import DSLValidationError

# the golden package: it is the one that declares a derived property in the
# wild (production-order.release_lag_h, an expression over two timestamps)
_GOLDEN_EXAMPLE = Path(__file__).resolve().parent.parent / "domains" / "product-manufacturing"


@pytest_asyncio.fixture()
async def session():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    maker = make_sessionmaker(engine)
    async with maker() as s:
        yield s
    await engine.dispose()


class TestCompile:
    def test_compile_golden(self, golden_pkg):
        compiled = compile_package(golden_pkg)
        assert compiled.package_name == "product-manufacturing"
        assert set(compiled.objects) == {
            "product", "bom", "material", "work-center", "production-order", "operation", "quality-inspection",
        }
        assert compiled.table_name("production-order") == "ontogeny_obj_production_order"
        assert compiled.owner("production-order", "product_id") == "source"
        assert compiled.owner("production-order", "status") == "ontology"
        assert compiled.owner("production-order", "released_at") == "ontology"
        assert compiled.owner("work-center", "name") == "source"  # empty mapping -> direct mode

    def test_join_table_link_gets_a_link_table(self, tmp_path):
        """The golden package is all foreign-key links; the join-table shape
        keeps its own naming contract, proven on a minimal inline package."""
        (tmp_path / "objects").mkdir()
        (tmp_path / "links").mkdir()
        (tmp_path / "ontology.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Ontology\nmetadata: {name: join-demo}\nspec: {imports: []}\n",
            encoding="utf-8",
        )
        (tmp_path / "objects" / "tool.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: ObjectType\nmetadata: {name: tool}\nspec:\n"
            "  primaryKey: [tool_id]\n"
            "  properties:\n"
            "    tool_id: {type: string, required: true}\n",
            encoding="utf-8",
        )
        (tmp_path / "objects" / "kit.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: ObjectType\nmetadata: {name: kit}\nspec:\n"
            "  primaryKey: [kit_id]\n"
            "  properties:\n"
            "    kit_id: {type: string, required: true}\n",
            encoding="utf-8",
        )
        (tmp_path / "links" / "tool-kits.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: LinkType\nmetadata: {name: tool-kits}\nspec:\n"
            "  source: tool\n  target: kit\n  cardinality: MANY_TO_MANY\n"
            "  join:\n"
            "    kind: join-table\n    store: mes\n"
            "    relation: {schema: mes, table: tool_kits}\n"
            "    keys:\n"
            "      source: {tool_id: tool_id}\n"
            "      target: {kit_id: kit_id}\n",
            encoding="utf-8",
        )
        compiled = compile_package(load_package(tmp_path))
        assert compiled.link_table("tool-kits") == "ontogeny_lnk_tool_kits"

    def test_content_hash_stable(self, golden_pkg):
        assert compile_package(golden_pkg).content_hash == compile_package(golden_pkg).content_hash

    def test_cedar_texts_loaded(self, golden_pkg):
        compiled = compile_package(golden_pkg)
        assert "planner" in compiled.cedar_texts["production"]

    def test_meta_export(self, golden_pkg):
        meta = compile_package(golden_pkg).to_meta()
        assert meta["objects"]["production-order"]["primaryKey"] == ["order_id"]
        assert "release-production-order" in meta["actions"]
        assert [lnk for lnk in meta["objects"]["production-order"]["links"]] == [
            "production-order-inspections", "production-order-operations", "production-order-product"
        ]

    def test_meta_export_carries_every_property_fact(self, golden_pkg):
        """Regression: the snapshot exported only type/required/marking, so every
        consumer could only show the machine name and the raw DSL syntax
        (`decimal(14,2)`) -- the display name, the business description
        and the field's owner were unreachable even though the model states
        them, and the i18n keys written for them stayed dead."""
        props = compile_package(golden_pkg).to_meta()["objects"]["production-order"]["properties"]

        assert props["order_id"]["display"] == "Order ID"
        assert props["status"]["owner"] == "ontology"
        # a fact the package does state survives the round trip: the material's
        # internal marking is what hides unit cost from unmarked principals
        assert compile_package(golden_pkg).to_meta()["objects"]["material"]["properties"]["unit_cost"]["marking"] == "internal"
        # every property states all facts, even when the value is null --
        # a consumer must not have to probe for a key's existence
        for name, p in props.items():
            assert set(p) >= {"type", "required", "marking", "display", "description", "owner", "derived"}, name
        # a stored property says so with a null, rather than omitting the key
        assert props["order_id"]["derived"] is None
        assert props["priority"]["derived"] is None
        # ...and a derived one carries its definition
        assert props["release_lag_h"]["derived"]["kind"] == "expr"

    def test_meta_export_describes_derivation(self):
        """A derived property reports *how* it is derived, not merely that it is."""
        meta = compile_package(load_package(_GOLDEN_EXAMPLE)).to_meta()

        lag = meta["objects"]["production-order"]["properties"]["release_lag_h"]
        assert lag["derived"]["kind"] == "expr"
        assert lag["derived"]["expr"] == "(released_at - created_at) / 3600000"

        # a cross-object count: which *other* type's changes must recompute it.
        # The golden package has no function-derived property, so declare one on
        # a copy -- same shape the demo uses for its open-order counters.
        import copy

        pkg = copy.deepcopy(load_package(_GOLDEN_EXAMPLE))
        obj = pkg.find("ObjectType", "work-center")
        obj.spec.properties["open_order_count"] = obj.spec.properties["work_center_id"].model_copy(
            update={"derived": {"kind": "function", "entry": "count.py:main", "triggers": ["production-order"]}},
        )
        count = compile_package(pkg).to_meta()["objects"]["work-center"]["properties"]["open_order_count"]
        assert count["derived"]["kind"] == "function"
        assert count["derived"]["entry"]
        assert count["derived"]["triggers"] == ["production-order"]

    def test_snake(self):
        assert snake("production-order") == "production_order"
        assert snake("Weird--Name.x") == "weird_name_x"


class TestPublish:
    async def test_publish_and_load(self, session: AsyncSession, golden_pkg):
        reg = RegistryService()
        compiled = await reg.publish(session, golden_pkg, created_by="ci")
        assert compiled.package_name == "product-manufacturing"
        await session.commit()

        # rebuild from DB only (restart path)
        reg2 = RegistryService()
        loaded = await reg2.load_latest(session)
        assert loaded is not None
        assert loaded.content_hash == compiled.content_hash
        assert set(loaded.objects) == set(compiled.objects)

    async def test_republish_increments_version(self, session: AsyncSession, golden_pkg):
        reg = RegistryService()
        await reg.publish(session, golden_pkg)
        await session.commit()
        await reg.publish(session, golden_pkg)
        await session.commit()
        from sqlalchemy import select

        from ontogeny.registry.store import ResourceRow

        rows = (await session.execute(
            select(ResourceRow).where(ResourceRow.kind == "ObjectType", ResourceRow.api_name == "work-center")
        )).scalars().all()
        assert len(rows) == 1 and rows[0].version == 2

    async def test_publish_rejects_invalid(self, session: AsyncSession, golden_pkg):
        import copy

        reg = RegistryService()
        pkg = copy.deepcopy(golden_pkg)
        pkg.find("LinkType", "operation-work-center").spec.target = "ghost"
        with pytest.raises(DSLValidationError) as ei:
            await reg.publish(session, pkg)
        assert any(i["code"] == "LINK-ENDPOINT" for i in ei.value.details.get("issues", []))

    async def test_publish_removal_soft_deletes(self, session: AsyncSession, golden_pkg):
        import copy

        reg = RegistryService()
        await reg.publish(session, golden_pkg)
        await session.commit()
        pkg2 = copy.deepcopy(golden_pkg)
        pkg2.resources = [r for r in pkg2.resources if not (r.kind == "ObjectType" and r.metadata.name == "material")]
        # force: dangling references (links/projection still mention material) would be
        # rejected by the validator; here we only exercise the soft-delete mechanics
        compiled = await reg.publish(session, pkg2, force=True)
        await session.commit()
        assert "material" not in compiled.objects
        from sqlalchemy import select

        from ontogeny.registry.store import ResourceRow

        row = (await session.execute(
            select(ResourceRow).where(ResourceRow.kind == "ObjectType", ResourceRow.api_name == "material")
        )).scalar_one()
        assert row.deleted_at is not None

    async def test_lineage_edges(self, session: AsyncSession, golden_pkg):
        reg = RegistryService()
        await reg.publish(session, golden_pkg)
        await session.commit()
        edges = await reg.lineage(session)
        pairs = {(e["src"], e["dst"]) for e in edges}
        assert ("Store/mes", "ObjectType/production-order", ) in pairs or any(
            e["src"] == "Store/mes" for e in edges
        )
        assert any(e["dst"] == "Projection/production-graph" for e in edges)


class TestSnapshotEvolution:
    """A snapshot written by an older DSL must still load.

    Regression: removing `FunctionSpec.publish` made every existing deployment
    refuse to start — the stored definition carried a key the new model forbids
    (`extra="forbid"`), so a field nobody used any more was a hard boot failure.
    Strictness belongs at publish time (the package on disk); already-accepted
    history is read tolerantly.
    """

    def test_a_removed_field_in_a_stored_snapshot_is_ignored(self):
        from ontogeny.core.models import RESOURCE_BY_KIND
        from ontogeny.registry.store import _prune_unknown

        cls = RESOURCE_BY_KIND["Function"]
        stale = {
            "apiVersion": "ontogeny/v1", "kind": "Function",
            "metadata": {"name": "legacy"},
            "spec": {
                "runtime": "python", "entry": "legacy.py:run",
                "capabilities": [], "publish": {"enabled": True},   # field since removed
            },
        }
        pruned = _prune_unknown(cls, stale)
        assert "publish" not in pruned["spec"]
        assert pruned["spec"]["entry"] == "legacy.py:run"
        cls.model_validate(pruned)          # must not raise

    def test_a_typo_in_a_fresh_package_is_still_an_error(self, golden_pkg_path):
        """The tolerance is for stored history only: a file on disk with an
        unknown key is still refused, so a typo cannot pass silently."""
        import shutil

        import pytest as _pytest

        from ontogeny.core import load_package

        root = golden_pkg_path.parent.parent / "tests-tmp-typo"
        shutil.rmtree(root, ignore_errors=True)
        shutil.copytree(golden_pkg_path, root)
        try:
            (root / "functions" / "typo.yaml").write_text(
                "apiVersion: ontogeny/v1\nkind: Function\nmetadata: {name: typo}\n"
                "spec:\n  runtime: python\n  entry: a.py:run\n  publishd: true\n",
                encoding="utf-8",
            )
            with _pytest.raises(Exception):
                load_package(str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)
