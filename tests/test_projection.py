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
"""Projection layer: schema compilation, worker delivery, rebuild (mocked HTTP)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import yaml

from ontogeny.action.models import OutboxRow
from ontogeny.core import load_package
from ontogeny.errors import StoreError
from ontogeny.registry import compile_package
from ontogeny.projection import ProjectionWorker, compile_projection
from ontogeny_ext_hugegraph import HugeGraphClient


@pytest.fixture()
def compiled(golden_pkg):
    return compile_package(golden_pkg)


class TestCompiler:
    def test_schema_shape(self, compiled):
        prj = compiled.projections["production-graph"]
        schema = compile_projection(compiled, prj)
        assert schema["graph"] == "product_manufacturing"  # the domain's own name
        labels = {v["label"] for v in schema["vertexlabels"]}
        assert labels == {"product", "bom", "material", "work-center",
                          "production-order", "operation", "quality-inspection"}
        pk = next(v for v in schema["vertexlabels"] if v["label"] == "production-order")
        assert pk["primary_keys"] == ["order_id"]
        # whitelisted properties only, marking never enters (validator enforces)
        mat = next(v for v in schema["vertexlabels"] if v["label"] == "material")
        assert "unit_cost" not in mat["properties"] and "name" in mat["properties"]
        edges = {e["name"] for e in schema["edgelabels"]}
        assert edges == {"bom-product", "bom-material", "production-order-product",
                         "production-order-operations", "production-order-inspections",
                         "operation-work-center"}
        types = {p["name"]: p["data_type"] for p in schema["propertykeys"]}
        assert types["name"] == "TEXT" and types["status"] == "TEXT"


class TestClientAndWorker:
    @pytest_asyncio.fixture()
    async def rig(self, compiled):
        prj = compiled.projections["production-graph"]
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(201)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hugegraph:8120", prj.spec.graph, http=http)
        worker = ProjectionWorker(compiled, prj, client)
        yield {"client": client, "worker": worker, "calls": calls, "prj": prj, "compiled": compiled}
        await http.aclose()

    async def test_ensure_schema_emits_rest_calls(self, rig, compiled):
        schema = compile_projection(compiled, rig["prj"])
        await rig["client"].ensure_schema(schema)
        paths = [r.url.path for r in rig["calls"]]
        assert any(p.endswith("/propertykeys") for p in paths)
        assert any(p.endswith("/vertexlabels") for p in paths)
        assert any(p.endswith("/edgelabels") for p in paths)

    async def test_clear_wipes_the_graph_and_asks_for_confirmation(self, rig):
        """A rebuild's first step.

        Regression: "rebuild" only ever upserted, so a graph that had projected
        a previous package kept those vertices forever and the label counts
        disagreed with the object tables (42 graph vertices against 5 rows).
        """
        await rig["client"].clear()
        req = rig["calls"][-1]
        assert req.method == "DELETE"
        # the mock endpoint answers 201 to the dialect probe, so this rig is the
        # legacy (1.5) shape: the graph-scoped path is bare
        assert req.url.path.endswith("/clear")
        assert "confirm_message" in str(req.url)

    async def test_upsert_vertices_body(self, rig):
        await rig["client"].upsert_vertices("work-center", "work_center_id", [
            {"work_center_id": "WC-01", "name": "CNC Machining Cell", "status": "ACTIVE"},
        ])
        import json

        body = json.loads(rig["calls"][-1].read())
        assert body[0]["label"] == "work-center" and body[0]["id"] == "WC-01"
        # the client is transport-level: it sends what it is given; whitelist
        # filtering happens in ProjectionWorker.project_object
        assert body[0]["properties"] == {"name": "CNC Machining Cell", "status": "ACTIVE"}

    async def test_archive_deletes_vertex(self, rig):
        await rig["worker"].handle_event(None, None, OutboxRow(
            object_type="work-center", object_id="WC-99", op="archive", payload={},
        ))
        last = rig["calls"][-1]
        assert last.method == "DELETE" and "WC-99" in str(last.url)

    async def test_unprojected_type_consumed_silently(self, rig):
        ok = await rig["worker"].handle_event(None, None, OutboxRow(
            object_type="not-in-projection", object_id="x", op="upsert", payload={},
        ))
        assert ok is True and not rig["calls"]


class TestScaffold:
    """The console's one-click "make the graph real" path.

    Deriving the projection is the part that has to be right: the console offers
    it when HugeGraph is selected but nothing is declared, so the result must be
    a package the validator accepts (every object, property and link it names
    must exist, and no marked property may leak into the graph)."""

    async def test_derivation_covers_the_whole_ontology(self, client):
        _, sc = client
        payload = sc._derive_projection(name="auto-graph", graph="auto", graphspace="DEFAULT")

        assert payload["kind"] == "Projection"
        assert payload["spec"]["engine"] == "hugegraph"
        assert payload["spec"]["endpoint"] == "${HUGEGRAPH_URL}"
        include = payload["spec"]["include"]
        # every object type, and every link whose endpoints are both included
        assert set(include["objects"]) == set(sc.compiled.objects)
        assert set(include["links"]) == set(sc.compiled.links)

        for obj_name, cfg in include["objects"].items():
            obj = sc.compiled.objects[obj_name]
            defined = set(obj.spec.properties)
            assert set(cfg["properties"]) <= defined
            for prop in cfg["properties"]:
                pdef = obj.spec.properties[prop]
                # marked properties never enter the graph (the validator refuses
                # them outright); derived ones have no stored column to project
                assert pdef.marking is None, f"{obj_name}.{prop} carries a marking"
                assert pdef.derived is None, f"{obj_name}.{prop} is derived"

    async def test_derived_projection_carries_the_domain_graph_name(self, client):
        """The graph name is not a choice: it is the domain's own name."""
        from ontogeny.core.models import ProjectionResource

        _, sc = client
        payload = sc._derive_projection(name="auto-graph", graph=sc.graph_name(),
                                        graphspace="DEFAULT")
        res = ProjectionResource.model_validate(payload)
        assert res.spec.graph == sc.graph_name() == "product_manufacturing"

    async def test_derived_projection_passes_the_validator(self, client):
        """It is written into the package, so validate() is the real gate."""
        from ontogeny.core import validate as _validate
        from ontogeny.core.models import ProjectionResource

        _, sc = client
        res = ProjectionResource.model_validate(
            sc._derive_projection(name="auto-graph", graph=sc.graph_name(),
                                  graphspace="DEFAULT")
        )
        # publish it into the working copy exactly as scaffold_projection does
        pkg_dir = Path(sc.package_root)
        (pkg_dir / "projections").mkdir(exist_ok=True)
        (pkg_dir / "projections" / "auto-graph.yaml").write_text(
            yaml.safe_dump(res.model_dump(mode="json", by_alias=True, exclude_none=True),
                           allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        rep = _validate(load_package(str(pkg_dir)))
        errs = [f"{i.code}:{i.message}" for i in rep.issues if i.severity == "error"]
        assert not errs, errs

    async def test_a_foreign_graph_name_is_refused_by_validate(self, client):
        """One domain, one graph: pointing elsewhere is an error, not a warning.

        Two domains naming the same graph read each other's vertices; this rule
        is what makes that unrepresentable rather than merely discouraged.
        """
        from ontogeny.core import validate as _validate
        from ontogeny.core.models import ProjectionResource

        _, sc = client
        res = ProjectionResource.model_validate(
            sc._derive_projection(name="stray", graph="someone_elses_graph",
                                  graphspace="DEFAULT")
        )
        pkg_dir = Path(sc.package_root)
        (pkg_dir / "projections" / "stray.yaml").write_text(
            yaml.safe_dump(res.model_dump(mode="json", by_alias=True, exclude_none=True),
                           allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        rep = _validate(load_package(str(pkg_dir)))
        codes = [i.code for i in rep.issues if i.severity == "error"]
        assert "PROJ-GRAPH-NAME" in codes

    async def test_scaffold_refuses_to_clobber_a_declared_projection(self, client):
        """The golden package ships a curated projection; re-deriving over it
        would discard a property whitelist no button can recover."""
        from ontogeny.errors import AlreadyDeclaredError

        _, sc = client
        with pytest.raises(AlreadyDeclaredError, match="already declares projection"):
            await sc.scaffold_projection(name="auto-graph")

    async def test_scaffold_without_a_graph_client_says_why(self, client):
        """Selecting HugeGraph in the UI is what wires the client; on the default
        (sqlite) storage the scaffold must report the configuration gap as a
        readable reason instead of a bare 500."""
        _, sc = client
        # a package with no projection at all -- the state the console offers
        # "create projection" from
        for f in (Path(sc.package_root) / "projections").glob("*.yaml"):
            f.unlink()
        await sc.publish(sc.package_root, created_by="test")
        assert not sc.compiled.projections
        assert sc.projection_worker is None  # sqlite storage: nothing to wire yet
        with pytest.raises(StoreError, match="no graph client was wired"):
            await sc.scaffold_projection(name="auto-graph")

    async def test_graph_state_is_unknown_without_a_probe_target(self, client):
        """The third answer matters: with no endpoint or no graph extension the
        state is None, never False — a caller must not offer a destructive build
        because it could not look."""
        _, sc = client
        state = await sc.graph_state()
        assert state["graph_name"] == "product_manufacturing"
        # this fixture runs sqlite storage, so nothing can be probed
        assert state["graph_exists"] is None


class TestDeclaredVersusWired:
    """The console must never offer an action the backend will refuse.

    Regression: "not wired" was reported as "no projection declared", so the
    storage card offered "create a projection" for a package that already had
    one. The only outcome was ALREADY_DECLARED — a loop with no way out, because
    each attempt produced the same advice ("create a projection").
    """

    async def test_a_declared_projection_is_reported_as_declared(self, client):
        _, sc = client
        summary = await sc.projection_summary()
        assert summary["declared"] is True
        assert summary["declared_name"] == "production-graph"

    async def test_declared_but_unwired_says_what_is_actually_missing(self, client):
        # this fixture runs sqlite storage: the projection is declared, the graph
        # layer cannot be wired, and the reason names *that*, not the declaration
        _, sc = client
        summary = await sc.projection_summary()
        assert summary["configured"] is False
        assert summary["blocked_by"] == "provider-sqlite"
        assert "sqlite" in summary["reason"]
        assert "no projection declared" not in summary["reason"]

    async def test_nothing_declared_says_so(self, client):
        _, sc = client
        for f in (Path(sc.package_root) / "projections").glob("*.yaml"):
            f.unlink()
        await sc.publish(sc.package_root, created_by="test")
        summary = await sc.projection_summary()
        assert summary["declared"] is False and summary["blocked_by"] == "not-declared"
        assert summary["reason"] == "no projection declared"

    async def test_an_unresolved_endpoint_names_the_setting_to_fix(self, golden_pkg_path, tmp_path):
        """The exact state a fresh deployment lands in: a projection that
        references ${HUGEGRAPH_URL} before anyone has set it."""
        import shutil

        from ontogeny.config import Settings
        from ontogeny.service import ServiceContext

        pkg_root = tmp_path / "pkg"
        shutil.copytree(golden_pkg_path, pkg_root)
        sc = ServiceContext(
            Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path/'m.db'}",
                     storage_provider="hugegraph"),   # hugegraph selected, no URL
            str(pkg_root),
        )
        await sc.initialize()
        summary = await sc.projection_summary()
        assert summary["declared"] is True and summary["configured"] is False
        assert summary["blocked_by"] == "endpoint-unresolved"
        assert "HUGEGRAPH_URL" in summary["reason"]

    async def test_the_console_never_offers_scaffold_when_declared(self, client):
        """The invariant behind the fix, stated as a rule: scaffold exists to
        CREATE a declaration, so its precondition is `declared == false`."""
        from ontogeny.errors import AlreadyDeclaredError

        _, sc = client
        assert (await sc.projection_summary())["declared"] is True
        with pytest.raises(AlreadyDeclaredError):
            await sc.scaffold_projection(name="auto-graph")
