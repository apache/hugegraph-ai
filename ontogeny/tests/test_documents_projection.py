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

"""Asserted (document) links reach the graph projection like any other edge."""

from __future__ import annotations

from ontogeny.projection import ProjectionWorker


class FakeGraphStore:
    def __init__(self):
        self.vertices: dict[str, list[dict]] = {}
        self.edges: list[tuple[str, str, str, list[tuple[str, str]]]] = []

    async def ensure_graph(self):
        return True

    async def ensure_schema(self, schema):
        return None

    async def exists(self):
        return True

    async def clear(self):
        self.vertices.clear()
        self.edges.clear()

    async def dialect(self):
        return "fake"

    async def labels(self):
        return {"vertices": [], "edges": []}

    async def counts(self):
        return {"vertices": {}, "edges": {}}

    async def sample_vertices(self, label, limit=20):
        return self.vertices.get(label, [])[:limit]

    async def sample_edges(self, label, limit=20):
        return []

    async def upsert_vertices(self, label, pk_prop, items):
        self.vertices.setdefault(label, [])
        by_id = {str(v[pk_prop]): v for v in self.vertices[label]}
        for item in items:
            by_id[str(item[pk_prop])] = item
        self.vertices[label] = list(by_id.values())

    async def upsert_edges(self, link_name, src_label, dst_label, pairs):
        self.edges.append((link_name, src_label, dst_label, list(pairs)))

    async def delete_vertex(self, label, vertex_id):
        return None


async def test_rebuild_projects_extracted_links(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier-note")
    projection = sc.compiled.projections["supplier-graph"]
    store = FakeGraphStore()
    worker = ProjectionWorker(sc.compiled, projection, store)
    async with sc.sessionmaker() as session:
        counts = await worker.rebuild(sc.repo, session)
    assert counts["vertices"] == 5  # 3 suppliers + 2 notes
    assert counts["edges"] == 2
    labelled = [e for e in store.edges if e[0] == "supplier-risk-note"]
    assert labelled and labelled[0][1] == "supplier" and labelled[0][2] == "supplier-note"
    pairs = labelled[0][3]
    assert all(src.startswith("SUP-") for src, _ in pairs)
    note_ids = {str(v["note_id"]) for v in store.vertices["supplier-note"]}
    assert {dst for _, dst in pairs} == note_ids


async def test_incremental_projection_of_one_note(doc_context):
    sc, _, _ = doc_context
    summary = await sc.sync("supplier-note")
    projection = sc.compiled.projections["supplier-graph"]
    store = FakeGraphStore()
    worker = ProjectionWorker(sc.compiled, projection, store)
    async with sc.sessionmaker() as session:
        rows = await sc.repo.query(session, "supplier-note", limit=1)
        note = rows[0][0]
        await worker.project_object(sc.repo, session, "supplier-note", note["note_id"])
        pairs = await worker._link_pairs(sc.repo, session, "supplier-risk-note", dst_id=note["note_id"])
    assert store.vertices["supplier-note"][0]["note_id"] == note["note_id"]
    assert pairs and pairs[0][1] == note["note_id"]
    assert summary["links"] == 2
