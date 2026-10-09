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
"""HugeGraph projection: REST dialects (1.7 graphspace / 1.5 legacy), FK edge
materialisation, and the preview surfaces the UI reads.

The service-level tests run the real ServiceContext (real repo, real files on
disk) and mock only the HTTP boundary, so the assertions cover the whole path
from object rows to graph payloads.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
import pytest_asyncio

from ontogeny.action.models import OutboxRow
from ontogeny.config import Settings
from ontogeny.demo import seed_from_package
from ontogeny.projection import ProjectionWorker, compile_projection
from ontogeny_ext_hugegraph import HugeGraphClient
from ontogeny.registry import compile_package
from ontogeny.service import ServiceContext

# every domain owns exactly one graph, named after the package, snake-cased
GRAPH = "product_manufacturing"


@pytest.fixture()
def compiled(golden_pkg):
    return compile_package(golden_pkg)


def _recorder(routes: list[tuple[str, str, httpx.Response]]):
    """MockTransport handler that routes on (method, path substring)."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        for method, needle, response in routes:
            if request.method == method and request.url.path.endswith(needle):
                return response
        return httpx.Response(200, json={})

    return handler, calls


# --------------------------------------------------------------------- 1.7


class TestDialectV17:
    @pytest_asyncio.fixture()
    async def rig(self, compiled):
        routes = [
            ("GET", "/graphspaces", httpx.Response(200, json={"graphSpaces": []})),
            ("GET", "/schema/vertexlabels", httpx.Response(200, json={"vertexlabels": [
                {"name": "product", "id": 1}, {"name": "bom", "id": 2}, {"name": "material", "id": 3},
                {"name": "work-center", "id": 4}, {"name": "production-order", "id": 5},
                {"name": "operation", "id": 6}, {"name": "quality-inspection", "id": 7},
            ]})),
        ]
        handler, calls = _recorder(routes)
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        prj = compiled.projections["production-graph"]
        client = HugeGraphClient("http://hg.test", prj.spec.graph, http=http)
        worker = ProjectionWorker(compiled, prj, client)
        yield {"client": client, "worker": worker, "calls": calls, "prj": prj}
        await http.aclose()

    async def test_auto_detects_17(self, rig):
        assert await rig["client"].dialect() == "1.7"

    async def test_ensure_schema_uses_graphspace_paths_and_valid_index_types(self, rig, compiled):
        schema = compile_projection(compiled, rig["prj"])
        await rig["client"].ensure_schema(schema)

        posts = [r for r in rig["calls"] if r.method == "POST"]
        paths = [unquote(r.url.path) for r in posts]
        assert all(p.startswith(f"/graphspaces/DEFAULT/graphs/{GRAPH}/") for p in paths), paths

        vl = next(r for r in posts if r.url.path.endswith("/schema/vertexlabels"))
        body = json.loads(vl.read())
        assert body["id_strategy"] == "PRIMARY_KEY" and body["primary_keys"] == ["product_id"]
        # the key property is not nullable, the rest are
        assert "product_id" not in body["nullable_keys"]

        # every declared index is on a TEXT prop (status) -> SECONDARY
        ix = [json.loads(r.read()) for r in posts if r.url.path.endswith("/schema/indexlabels")]
        assert {i["index_type"] for i in ix} == {"SECONDARY"}
        assert {i["base_value"] for i in ix} == {"production-order", "operation", "work-center"}

    async def test_index_type_follows_property_type(self, rig, compiled):
        schema = compile_projection(compiled, rig["prj"])
        for pk in schema["propertykeys"]:
            if pk["name"] == "status":
                pk["data_type"] = "INT"  # pretend the DSL indexed a numeric prop
        # a TEXT-prop index alongside the numeric ones, for contrast
        schema["indexes"].append({"label": "product", "property": "name"})
        await rig["client"].ensure_schema(schema)
        raw = [json.loads(r.read()) for r in rig["calls"]
               if r.method == "POST" and r.url.path.endswith("/schema/indexlabels")]
        by_name = {i["name"]: i["index_type"] for i in raw}
        assert by_name["production-order_by_status"] == "RANGE"  # numeric -> RANGE
        assert by_name["product_by_name"] == "SECONDARY"         # text -> SECONDARY

    async def test_exists_reads_the_graphspace_listing(self):
        """Load-vs-build turns on this answer, so it must be exact: a listed
        name means present, an unlisted one means absent, and an answer we
        cannot interpret means UNKNOWN (None) — never "absent", because that
        would offer to overwrite a graph we simply failed to see."""
        handler, _ = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
            ("GET", "/graphspaces/DEFAULT/graphs", httpx.Response(200, json={"graphs": ["hugegraph", GRAPH]})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        assert await client.exists() is True
        await http.aclose()

    async def test_exists_is_false_for_an_unlisted_graph(self):
        handler, _ = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
            ("GET", "/graphspaces/DEFAULT/graphs", httpx.Response(200, json={"graphs": ["hugegraph"]})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        assert await client.exists() is False
        await http.aclose()

    async def test_exists_is_unknown_when_the_probe_fails(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/graphspaces"):
                return httpx.Response(200, json={})
            return httpx.Response(503, text="backend unavailable")

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        assert await client.exists() is None
        await http.aclose()

    async def test_ensure_graph_creates_only_when_absent(self):
        """HugeGraph never creates a graph on first write (schema to an absent
        graph is a 500 from GraphManager), so a build has to ask. The name goes
        in the PATH: POSTing the collection with a body is a 405 on this API."""
        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
            ("GET", "/graphspaces/DEFAULT/graphs", httpx.Response(200, json={"graphs": ["hugegraph"]})),
            ("GET", "/graphspaces/DEFAULT/graphs/hugegraph", httpx.Response(200, json={"backend": "hstore"})),
            ("POST", f"/graphspaces/DEFAULT/graphs/{GRAPH}", httpx.Response(201, json={})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        assert await client.ensure_graph() is True
        created = [r for r in calls if r.method == "POST"]
        assert len(created) == 1
        assert created[0].url.path.endswith(f"/graphspaces/DEFAULT/graphs/{GRAPH}")
        # The body is the difference between a graph that opens and one that
        # never can: the auth proxy (without it the server refuses the config)
        # and PER-GRAPH data/wal paths (the server's default is one shared
        # directory, so a second created graph dies on "lock hold by current
        # process"). The deployment's own backend is inherited, not assumed.
        body = json.loads(created[0].read())
        assert body["gremlin.graph"] == "org.apache.hugegraph.auth.HugeFactoryAuthProxy"
        assert body["backend"] == "hstore" and body["serializer"] == "binary"
        assert body["store"] == GRAPH
        # hstore does not take rocksdb paths
        assert "rocksdb.data_path" not in body
        await http.aclose()

    async def test_created_graphs_get_their_own_data_directory(self):
        """RocksDB graphs need distinct paths or only the first one ever opens."""
        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
            ("GET", "/graphspaces/DEFAULT/graphs", httpx.Response(200, json={"graphs": ["hugegraph"]})),
            ("GET", "/graphspaces/DEFAULT/graphs/hugegraph", httpx.Response(200, json={"backend": "rocksdb"})),
            ("POST", f"/graphspaces/DEFAULT/graphs/{GRAPH}", httpx.Response(201, json={})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http,
                                 data_dir="/data/hg")
        assert await client.ensure_graph() is True
        body = json.loads([r for r in calls if r.method == "POST"][0].read())
        assert body["rocksdb.data_path"] == f"/data/hg/{GRAPH}/data"
        assert body["rocksdb.wal_path"] == f"/data/hg/{GRAPH}/wal"
        await http.aclose()

    async def test_ensure_graph_names_why_a_refusal_needs_the_operator(self):
        """A non-auth 1.7 server cannot create graphs at all (vendor-documented),
        so the failure must say what to do instead of leaking an NPE."""
        from ontogeny.errors import StoreError

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/graphspaces"):
                return httpx.Response(200, json={})
            if request.url.path.endswith("/graphs"):
                return httpx.Response(200, json={"graphs": ["hugegraph"]})
            if request.url.path.endswith("/graphs/hugegraph"):
                return httpx.Response(200, json={"backend": "rocksdb"})
            return httpx.Response(500, json={"exception": "java.lang.NullPointerException"})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        with pytest.raises(StoreError, match="graphs.yaml"):
            await client.ensure_graph()
        await http.aclose()

    async def test_ensure_graph_is_a_no_op_when_it_already_exists(self):
        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
            ("GET", "/graphspaces/DEFAULT/graphs", httpx.Response(200, json={"graphs": ["hugegraph", GRAPH]})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        assert await client.ensure_graph() is False
        assert not [r for r in calls if r.method == "POST"]
        await http.aclose()

    async def test_clear_is_a_no_op_when_the_graph_does_not_exist(self):
        """The first build's first step: clearing something that is not there
        must not be the thing that blocks creating it (1.7 answers 500 to
        /clear on an absent graph)."""
        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
            ("GET", "/graphspaces/DEFAULT/graphs", httpx.Response(200, json={"graphs": ["hugegraph"]})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        await client.clear()  # must not raise
        assert not [r for r in calls if r.method == "DELETE"]
        await http.aclose()

    async def test_schema_conflict_is_tolerated(self, compiled):
        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
            ("POST", "/schema/", httpx.Response(400, json={"message": "The property key 'x' has existed"})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        prj = compiled.projections["production-graph"]
        await client.ensure_schema(compile_projection(compiled, prj))  # must not raise
        assert calls
        await http.aclose()

    async def test_vertex_upsert_is_batch_override_with_pk_in_properties(self, rig):
        await rig["client"].upsert_vertices(
            "work-center", "work_center_id",
            [{"work_center_id": "WC-01", "name": "CNC Machining Cell", "status": "ACTIVE"}])
        req = rig["calls"][-1]
        assert req.method == "PUT" and req.url.path.endswith("/graph/vertices/batch")
        body = json.loads(req.read())
        # PRIMARY_KEY ids derive from the properties, so the key travels inside them
        assert body["vertices"] == [
            {"label": "work-center",
             "properties": {"work_center_id": "WC-01", "name": "CNC Machining Cell", "status": "ACTIVE"}}
        ]
        assert body["update_strategies"] == {
            "work_center_id": "OVERRIDE", "name": "OVERRIDE", "status": "OVERRIDE"}

    async def test_rows_without_primary_key_are_skipped(self, rig):
        await rig["client"].upsert_vertices("work-center", "work_center_id", [{"name": "no key"}])
        assert not [r for r in rig["calls"] if "vertices/batch" in r.url.path]

    async def test_edge_upsert_builds_composite_ids_and_camelcase_labels(self, rig):
        await rig["client"].upsert_edges("bom-product", "product", "bom",
                                         [("P-100", "B-1001")])
        req = rig["calls"][-1]
        assert req.method == "PUT" and req.url.path.endswith("/graph/edges/batch")
        body = json.loads(req.read())
        assert body["edges"][0]["outV"] == "1:P-100" and body["edges"][0]["inV"] == "2:B-1001"
        assert body["edges"][0]["outVLabel"] == "product" and body["edges"][0]["inVLabel"] == "bom"
        # HugeGraph rejects an empty strategy map; edges carry no properties
        assert body["update_strategies"] == {"_ignore": "OVERRIDE"}

    async def test_delete_vertex_quotes_composite_id_and_tolerates_404(self, rig):
        await rig["client"].delete_vertex("work-center", "WC-99")
        req = rig["calls"][-1]
        assert req.method == "DELETE"
        assert unquote(req.url.path).endswith('/graph/vertices/"4:WC-99"')

    async def test_counts_reads_the_async_gremlin_job(self, rig):
        async def run():
            handler, calls = _recorder([
                ("GET", "/graphspaces", httpx.Response(200, json={})),
                ("POST", "/jobs/gremlin", httpx.Response(201, json={"task_id": 7})),
                ("GET", "/tasks/7", httpx.Response(200, json={
                    "task_status": "success", "task_result": '[{"work-center": 2}]'})),
            ])
            http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            client = HugeGraphClient("http://hg.test", GRAPH, http=http)
            out = await client.gremlin("g.V().group().by(label).by(count())")
            await http.aclose()
            return out, calls

        out, calls = await run()
        assert out == [{"work-center": 2}]
        assert [c.method for c in calls] == ["GET", "POST", "GET"]


# --------------------------------------------------------------------- 1.5


class TestDialectV15Legacy:
    @pytest_asyncio.fixture()
    async def rig(self, compiled):
        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(404, json={})),  # 1.5 has no graphspaces
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg15.test", GRAPH, http=http)
        yield {"client": client, "calls": calls, "prj": compiled.projections["production-graph"]}
        await http.aclose()

    async def test_auto_detects_15_when_graphspaces_absent(self, rig):
        assert await rig["client"].dialect() == "1.5"

    async def test_legacy_paths_and_payloads(self, rig, compiled):
        await rig["client"].ensure_schema(compile_projection(compiled, rig["prj"]))
        await rig["client"].upsert_vertices("work-center", "work_center_id",
                                            [{"work_center_id": "WC-01", "name": "CNC Machining Cell"}])
        await rig["client"].delete_vertex("work-center", "WC-01")
        paths = [r.url.path for r in rig["calls"]]
        assert any(p.startswith("/apis/schema/") for p in paths)
        assert any(p == "/apis/graph/vertices/batch-upsert" for p in paths)
        # 1.5 addressed the vertex through query params, not a path id
        delete = next(r for r in rig["calls"] if r.method == "DELETE")
        assert delete.url.params["id"] == "WC-01" and delete.url.params["graph"] == GRAPH
        body = json.loads(next(r for r in rig["calls"] if "batch-upsert" in r.url.path).read())
        assert body[0]["id"] == "WC-01"  # legacy shape carried an explicit id


# ------------------------------------------------------------------- worker


class _FakeRepo:
    """Just the link surface the worker uses (FK + join-table)."""

    def __init__(self, src_id: str | None = None):
        self.src_id = src_id
        self.calls: list[tuple] = []

    async def link_members(self, session, link_name, *, src_id=None, dst_id=None, at=None):
        self.calls.append(("link_members", link_name, src_id, dst_id))
        return [("P-100", "M-101")]

    async def fk_link_pairs(self, session, link_name, *, at=None):
        self.calls.append(("fk_link_pairs", link_name))
        return [("P-100", "B-1001"), ("P-100", "B-1002")]

    async def fk_linked_ids(self, session, link_name, obj_id, *, from_source, at=None):
        self.calls.append(("fk_linked_ids", link_name, obj_id, from_source))
        return ["B-1001"] if from_source else ["P-100"]


# The golden package projects only FK links; the join-table branch of the
# worker is real coverage, so this rig bolts one join-table link onto an
# in-memory copy of the compiled package (no disk, no fixture package).
_JOIN_LINK_YAML = """\
apiVersion: ontogeny/v1
kind: LinkType
metadata:
  name: product-material-usage
  display: Product material usage
  description: Many-to-many usage relation carried by a join table
spec:
  source: product
  target: material
  cardinality: MANY_TO_MANY
  join:
    kind: join-table
    store: mes
    relation:
      schema: mes
      table: product_materials
    keys:
      source:
        product_id: product_id
      target:
        material_id: material_id
"""


@pytest.fixture()
def compiled_with_join_link(compiled):
    import yaml
    from dataclasses import replace as dc_replace

    from ontogeny.core.models import LinkTypeResource

    link = LinkTypeResource.model_validate(yaml.safe_load(_JOIN_LINK_YAML))
    prj = compiled.projections["production-graph"].model_copy(deep=True)
    prj.spec.include.links.append(link.metadata.name)
    compiled = dc_replace(compiled,
                          links={**compiled.links, link.metadata.name: link},
                          projections={"production-graph": prj})
    return compiled, prj


class TestWorkerEdges:
    @pytest_asyncio.fixture()
    async def rig(self, compiled_with_join_link):
        compiled, prj = compiled_with_join_link
        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
            ("GET", "/schema/vertexlabels", httpx.Response(200, json={"vertexlabels": [
                {"name": "product", "id": 1}, {"name": "bom", "id": 2}, {"name": "material", "id": 3},
                {"name": "work-center", "id": 4}, {"name": "production-order", "id": 5},
                {"name": "operation", "id": 6}, {"name": "quality-inspection", "id": 7},
            ]})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", prj.spec.graph, http=http)
        worker = ProjectionWorker(compiled, prj, client)
        yield {"worker": worker, "calls": calls, "repo": _FakeRepo()}
        await http.aclose()

    def _edge_batches(self, calls):
        return [json.loads(r.read()) for r in calls if "edges/batch" in r.url.path]

    async def test_link_pairs_covers_both_join_kinds(self, rig):
        repo = rig["repo"]
        assert await rig["worker"]._link_pairs(repo, None, "bom-product") == \
            [("P-100", "B-1001"), ("P-100", "B-1002")]
        assert await rig["worker"]._link_pairs(repo, None, "product-material-usage") == \
            [("P-100", "M-101")]
        # single-sided lookups go through the right FK direction
        assert await rig["worker"]._link_pairs(repo, None, "bom-product", src_id="P-100") == \
            [("P-100", "B-1001")]
        assert await rig["worker"]._link_pairs(repo, None, "bom-product", dst_id="B-1001") == \
            [("P-100", "B-1001")]

    async def test_handle_event_projects_edges_for_both_sides(self, rig, monkeypatch):
        async def fake_project_object(repo, session, object_type, obj_id):
            return None

        monkeypatch.setattr(rig["worker"], "project_object", fake_project_object)
        await rig["worker"].handle_event(rig["repo"], None, OutboxRow(
            object_type="product", object_id="P-100", op="upsert", payload={}))
        await rig["worker"].handle_event(rig["repo"], None, OutboxRow(
            object_type="bom", object_id="B-1001", op="upsert", payload={}))

        batches = self._edge_batches(rig["calls"])
        # product is the FK *source* (bom-product), bom the target: both emit the pair
        assert any(b["edges"][0]["outV"] == "1:P-100" for b in batches)
        assert any(b["edges"][0]["inV"] == "2:B-1001" for b in batches)

    async def test_unprojected_type_is_consumed_silently(self, rig):
        ok = await rig["worker"].handle_event(rig["repo"], None, OutboxRow(
            object_type="supplier", object_id="S-1", op="upsert", payload={}))
        assert ok is True and not rig["calls"]


# ------------------------------------------------- service integration (mocked HTTP)


@pytest_asyncio.fixture()
async def sc_with_graph(golden_pkg_path, tmp_path):
    """Real ServiceContext (repo + package) with only the HTTP boundary mocked."""
    pkg_root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, pkg_root)
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL so the tables
    # match the ontology exactly
    seed_from_package(golden_pkg_path, src, force=True)

    graph_calls: list[httpx.Request] = []
    gremlin_jobs = {"n": 0}  # counts() runs one job for vertices, one for edges

    def handler(request: httpx.Request) -> httpx.Response:
        graph_calls.append(request)
        path, method = request.url.path, request.method
        if path == "/graphspaces":
            return httpx.Response(200, json={"graphSpaces": []})
        if path == "/graphspaces/DEFAULT/graphs":
            # the domain's own graph (named after the domain) is already there
            return httpx.Response(200, json={"graphs": ["hugegraph", GRAPH]})
        if path.endswith("/schema/vertexlabels") and method == "GET":
            return httpx.Response(200, json={"vertexlabels": [
                {"name": "product", "id": 1}, {"name": "bom", "id": 2}, {"name": "material", "id": 3},
                {"name": "work-center", "id": 4}, {"name": "production-order", "id": 5},
                {"name": "operation", "id": 6}, {"name": "quality-inspection", "id": 7},
            ]})
        if path.endswith("/schema/edgelabels") and method == "GET":
            return httpx.Response(200, json={"edgelabels": [
                {"name": "bom-product", "source_label": "product", "target_label": "bom"},
                {"name": "bom-material", "source_label": "material", "target_label": "bom"},
                {"name": "production-order-product", "source_label": "product",
                 "target_label": "production-order"},
                {"name": "production-order-operations", "source_label": "production-order",
                 "target_label": "operation"},
                {"name": "production-order-inspections", "source_label": "production-order",
                 "target_label": "quality-inspection"},
                {"name": "operation-work-center", "source_label": "work-center",
                 "target_label": "operation"},
            ]})
        if "jobs/gremlin" in path:
            gremlin_jobs["n"] += 1
            return httpx.Response(201, json={"task_id": 11})
        if "/tasks/11" in path:
            if gremlin_jobs["n"] % 2:  # odd job: vertices, even job: edges
                result = '[{"product": 2, "work-center": 2}]'
            else:
                result = '[{"bom-product": 1, "production-order-product": 2}]'
            return httpx.Response(200, json={"task_status": "success", "task_result": result})
        if path.endswith("/graph/vertices") and method == "GET":
            return httpx.Response(200, json={"vertices": [
                {"id": "4:WC-01", "label": "work-center",
                 "properties": {"work_center_id": "WC-01"}},
                {"id": "4:WC-02", "label": "work-center",
                 "properties": {"work_center_id": "WC-02"}},
            ]})
        if path.endswith("/graph/edges") and method == "GET":
            return httpx.Response(200, json={"edges": [
                {"id": "S1:P-100>2>5>>S2:PO-1001", "label": "production-order-product",
                 "outV": "1:P-100", "inV": "5:PO-1001",
                 "outVLabel": "product", "inVLabel": "production-order"},
            ]})
        return httpx.Response(200, json={})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(
        db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}",
             "WMS_WEBHOOK": "https://wms.example.test/hook",
             "HUGEGRAPH_URL": "http://hg.test"},
    )
    sc = ServiceContext(settings, str(pkg_root), projection_http=http)
    sc._test_graph_calls = graph_calls  # so a test can assert on what reached the graph
    await sc.initialize()
    assert sc.projection_client is not None, "projection endpoint should resolve from env"
    yield sc
    await http.aclose()

@pytest.fixture()
def principal():
    return {"id": "u-planner", "Role": ["planner"], "site": "plant-north"}


class TestLoadVersusBuild:
    """One domain, one graph: the console probes for it, then loads or builds.

    "Load" is not a no-op: it means the declaration is written and attached while
    the graph's contents are left exactly as they are. Rebuilding there would
    throw away the very data the operator asked to see."""

    async def test_scaffold_loads_an_existing_graph_untouched(self, sc_with_graph):
        sc = sc_with_graph
        # the state the console offers "create projection" from: nothing declared
        for f in (Path(sc.package_root) / "projections").glob("*.yaml"):
            f.unlink()
        await sc.publish(sc.package_root, created_by="test")
        assert not sc.compiled.projections

        result = await sc.scaffold_projection(name="auto-graph")

        assert result["action"] == "loaded"
        assert result["graph"] == GRAPH             # the domain's own name
        # a projection was declared and is now live
        assert sc.compiled.projections and sc.projection_worker is not None
        # ...and nothing was written into the graph: no wipe, no backfill.
        # (Label/count reads go over gremlin jobs, so they are reads, not writes.)
        calls = sc._test_graph_calls  # type: ignore[attr-defined]
        destructive = [r for r in calls if r.method == "DELETE"]
        backfilled = [r for r in calls
                      if r.method in ("POST", "PUT")
                      and ("/graph/vertices" in r.url.path or "/graph/edges" in r.url.path)]
        assert not destructive, "loading an existing graph must not clear it"
        assert not backfilled, "loading an existing graph must not re-backfill it"


class TestServicePreview:
    async def test_rebuild_projects_vertices_and_fk_edges(self, sc_with_graph, principal):
        for object_type in sc_with_graph.compiled.objects:
            await sc_with_graph.sync(object_type)

        counts = await sc_with_graph.projection_rebuild()
        # the demo source seed: 3 products + 7 BOM lines + 6 materials
        # + 3 work centres + 4 production orders + 9 operations + 3 inspections
        assert counts["vertices"] == 35
        # all six projected links are FK links: 7+7 BOM edges, 4 order-product,
        # 9 order-operations, 3 order-inspections, 9 operation-work-centre
        assert counts["edges"] == 39

    async def test_summary_reports_labels_counts_and_dialect(self, sc_with_graph, principal):
        summary = await sc_with_graph.projection_summary()
        assert summary["configured"] and summary["ok"]
        assert summary["graph"] == GRAPH and summary["graphspace"] == "DEFAULT"
        # the probe agrees with the listing: this domain's graph is on the server
        assert summary["graph_name"] == GRAPH and summary["graph_exists"] is True
        assert summary["dialect"] == "1.7"
        assert {v["name"] for v in summary["labels"]["vertices"]} == {
            "product", "bom", "material", "work-center",
            "production-order", "operation", "quality-inspection"}
        assert summary["counts"]["vertices"] == {"product": 2, "work-center": 2}

    async def test_graph_rows_are_reassembled_through_the_engine(self, sc_with_graph, principal):
        await sc_with_graph.sync("work-center")
        out = await sc_with_graph.projection_vertices("work-center", principal, limit=5)
        assert out["label"] == "work-center" and out["hidden"] == 0
        rows = {r["work_center_id"]: r for r in out["rows"]}
        assert set(rows) == {"WC-01", "WC-02"}
        # exactly what the object API returns: masking applied, graph has no say
        async with sc_with_graph.sessionmaker() as session:
            object_row = await sc_with_graph.query.get(session, "work-center", "WC-01", principal)
        assert rows["WC-01"] == object_row

    async def test_graph_edges_are_reassembled_and_named(self, sc_with_graph, principal):
        await sc_with_graph.sync("product")
        await sc_with_graph.sync("production-order")
        out = await sc_with_graph.projection_edges("production-order-product", principal, limit=5)
        assert len(out["rows"]) == 1
        edge = out["rows"][0]
        assert edge["source"] == {"type": "product", "id": "P-100",
                                  "display": "CNC Milling Machine"}
        assert edge["target"]["type"] == "production-order" and edge["target"]["id"] == "PO-1001"

    async def test_data_preview_lists_every_type_with_counts(self, sc_with_graph, principal):
        for t in sc_with_graph.compiled.objects:
            await sc_with_graph.sync(t)
        out = await sc_with_graph.data_preview(principal, limit=2)
        by_type = {o["type"]: o for o in out["objects"]}
        assert {"work-center", "production-order", "material"} <= set(by_type)
        assert by_type["work-center"]["total"] == 3
        assert len(by_type["work-center"]["rows"]) == 2
        assert out["total"] >= 35


class TestAuthMode:
    """A HugeGraph in auth mode is the only 1.7 server that both refuses
    anonymous access and allows the platform to create a graph, so credentials
    are load-bearing infrastructure rather than an optional extra."""

    async def test_credentials_travel_on_every_request(self, compiled):
        import base64

        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http,
                                 user="admin", password="s3cret")
        await client.dialect()
        expected = "Basic " + base64.b64encode(b"admin:s3cret").decode()
        assert calls and all(r.headers.get("authorization") == expected for r in calls)
        assert client.authenticated is True
        await http.aclose()

    async def test_no_credentials_sends_no_header(self):
        handler, calls = _recorder([
            ("GET", "/graphspaces", httpx.Response(200, json={})),
        ])
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        await client.dialect()
        assert all("authorization" not in r.headers for r in calls)
        assert client.authenticated is False
        await http.aclose()

    async def test_a_401_on_a_read_names_the_fix(self):
        """The one auth failure an operator meets must point at the setting that
        fixes it, not at a Java stack trace."""
        from ontogeny.errors import StoreError

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/graphspaces"):
                return httpx.Response(200, json={})
            if request.url.path.endswith("/schema/vertexlabels"):
                return httpx.Response(401, text="Unauthorized")
            return httpx.Response(200, json={"vertexlabels": [], "edgelabels": []})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        with pytest.raises(StoreError, match="no credentials configured"):
            await client.labels()
        await http.aclose()

    async def test_a_401_makes_existence_UNKNOWN_not_absent(self):
        """A probe we were not allowed to make must never be reported as "the
        graph is gone" — that answer is what offers a destructive build."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/graphspaces"):
                return httpx.Response(200, json={})
            return httpx.Response(401, text="Unauthorized")

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HugeGraphClient("http://hg.test", GRAPH, http=http)
        assert await client.exists() is None
        await http.aclose()
