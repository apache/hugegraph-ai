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

"""Extraction renames, task scope, and evidence spanning chunks."""

from __future__ import annotations

import base64
from copy import deepcopy

import pytest
import yaml
from doc_fixtures import DOMAIN, FakeExtractor, make_context
from sqlalchemy import select

from ontogeny.core import load_package
from ontogeny.documents.models import ExtractCandidateRow
from ontogeny.documents.protocol import ChunkResult
from ontogeny.documents.schema import compile_extraction_schema
from ontogeny.registry import compile_package


@pytest.mark.parametrize("prop", ["summary", "supplier_name"])
def test_document_schema_emits_renamed_extraction_fields(prop):
    compiled = compile_package(load_package(DOMAIN))
    obj = compiled.objects["supplier-note"]
    obj.spec.backing.mapping = {prop: "renamed"}
    bundle = compile_extraction_schema(compiled, ["supplier-note"])
    label = bundle.schema["vertexlabels"][0]
    assert "renamed" in label["properties"]
    assert prop not in label["properties"]
    assert bundle.fields["supplier-note"]["renamed"] == prop
    assert bundle.reverse["supplier-note"][prop] == "renamed"
    if prop == "supplier_name":
        assert label["primary_keys"] == ["renamed"]
    else:
        assert "renamed" in label["nullable_keys"]


@pytest.mark.parametrize("prop", ["name", "supplier_id"])
def test_reference_schema_emits_renamed_identity_fields(prop):
    compiled = compile_package(load_package(DOMAIN))
    compiled.objects["supplier"].spec.backing.mapping = {prop: "renamed"}
    bundle = compile_extraction_schema(compiled, ["supplier-note"], reference_types=["supplier"])
    label = next(v for v in bundle.schema["vertexlabels"] if v["name"] == "supplier")
    assert "renamed" in label["properties"]
    assert prop not in label["properties"]
    assert label["primary_keys"] == (["renamed"] if prop == "name" else ["name"])


def test_schema_rejects_two_properties_using_one_extraction_name():
    compiled = compile_package(load_package(DOMAIN))
    compiled.objects["supplier-note"].spec.backing.mapping = {"summary": "risk_level"}
    with pytest.raises(ValueError, match="used by two properties"):
        compile_extraction_schema(compiled, ["supplier-note"])


class GraphChunksExtractor(FakeExtractor):
    def __init__(self, graphs):
        super().__init__()
        self.graphs = graphs

    async def extract(self, request):
        return [
            ChunkResult(doc.doc_id, i, doc.text, deepcopy(graph), [], "final")
            for doc in request.docs
            for i, graph in enumerate(self.graphs)
        ]


def _note_vertex(label="supplier-note", **props):
    return {
        "id": "note",
        "label": label,
        "properties": {"supplier_name": "Acme Components", "effective_date": "2026-07-01", **props},
    }


async def _create_and_run(sc, *, scope=None):
    created = await sc.documents.tasks.create_tasks(
        "supplier-docs",
        [{"name": "review.md", "content_b64": base64.b64encode(b"Acme Components risk HIGH").decode()}],
        scope=scope,
        skill=None,
        principal="tester",
    )
    task_id = created["tasks"][0]["id"]
    return task_id, await sc.documents.tasks.run(task_id, "tester")


def _add_document_endpoint(pkg):
    obj = yaml.safe_load((pkg / "objects" / "supplier-note.yaml").read_text())
    obj["metadata"]["name"] = "risk-review"
    obj["spec"]["backing"]["source"]["table"] = "risk-reviews"
    (pkg / "objects" / "risk-review.yaml").write_text(yaml.safe_dump(obj))
    link = yaml.safe_load((pkg / "links" / "supplier-risk-note.yaml").read_text())
    link["metadata"]["name"] = "related-notes"
    link["spec"]["source"] = "supplier-note"
    link["spec"]["target"] = "risk-review"
    (pkg / "links" / "related-notes.yaml").write_text(yaml.safe_dump(link))


async def test_task_scope_excludes_link_even_when_both_endpoints_are_selected(tmp_path):
    graph = {
        "vertices": [_note_vertex(), _note_vertex("risk-review")],
        "edges": [
            {
                "label": "related-notes",
                "outV": "note",
                "outVLabel": "supplier-note",
                "inV": "note",
                "inVLabel": "risk-review",
            }
        ],
    }
    sc, _, _ = await make_context(tmp_path, extractor=GraphChunksExtractor([graph]), mutate=_add_document_endpoint)
    try:
        task_id, detail = await _create_and_run(
            sc,
            scope={"objects": {"supplier-note": [], "risk-review": []}, "links": []},
        )
        assert detail["attempt"]["validation"]["blockers"] == []
        assert detail["attempt"]["validation"]["links"] == 0
        assert any("related-notes" in gap for gap in detail["attempt"]["validation"]["gaps"])
        confirmed = await sc.documents.tasks.confirm(task_id, "tester")
        assert confirmed["summary"]["links"] == 0
        async with sc.sessionmaker() as session:
            assert await sc.repo.link_members(session, "related-notes") == []
    finally:
        await sc.engine.dispose()


async def test_repeated_vertex_retains_later_properties_and_conflicts(tmp_path):
    graphs = [
        {"vertices": [_note_vertex(summary="first")], "edges": []},
        {"vertices": [_note_vertex(summary="second", risk_level="HIGH")], "edges": []},
    ]
    sc, _, _ = await make_context(tmp_path, extractor=GraphChunksExtractor(graphs))
    try:
        task_id, detail = await _create_and_run(sc)
        # The graph preview deduplicates display IDs; staging keeps all evidence
        # so the binder can merge facts and surface disagreements.
        assert len(detail["attempt"]["graph"]["vertices"]) == 2
        assert detail["attempt"]["validation"]["blockers"] == []
        confirmed = await sc.documents.tasks.confirm(task_id, "tester")
        assert confirmed["summary"]["inserted"] == 1
        async with sc.sessionmaker() as session:
            rows, count = await sc.repo.query(session, "supplier-note", limit=10)
            assert count == 1
            assert rows[0]["risk_level"] == "HIGH"
            assert rows[0]["summary"] == "first"
            candidates = (await session.execute(select(ExtractCandidateRow))).scalars().all()
            assert any(c.reason == "CONFLICT" and c.payload["proposed"] == "second" for c in candidates)
    finally:
        await sc.engine.dispose()
