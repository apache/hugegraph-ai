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

"""Opt-in smoke test against a disposable HugeGraph default graph.

Set ONTOGENY_TEST_HUGEGRAPH_URL to an isolated server: this test creates the
chip lifecycle projection's schema and writes then removes its own test data.
"""

import os
import uuid

import pytest
from ontogeny_ext_hugegraph import HugeGraphClient

from ontogeny.projection import compile_projection
from ontogeny.registry import compile_package


@pytest.mark.skipif(not os.environ.get("ONTOGENY_TEST_HUGEGRAPH_URL"), reason="requires a disposable HugeGraph server")
async def test_live_lifecycle_schema_vertices_and_edge(golden_pkg):
    compiled = compile_package(golden_pkg)
    schema = compile_projection(compiled, compiled.projections["production-lifecycle-graph"])
    token = uuid.uuid4().hex
    requirement, module = f"smoke-requirement-{token}", f"smoke-module-{token}"
    client = HugeGraphClient(os.environ["ONTOGENY_TEST_HUGEGRAPH_URL"], "hugegraph")
    try:
        assert await client.dialect() == "1.7"
        assert await client.exists() is True
        await client.ensure_schema(schema)
        # Outbox delivery is at least once: deleting an object that never
        # existed, or replaying a successful delete, must both succeed.
        await client.delete_vertex("requirement", requirement)
        requirement_created = module_created = False
        try:
            await client.upsert_vertices(
                "requirement", "requirement_id", [{"requirement_id": requirement, "title": "Smoke"}]
            )
            requirement_created = True
            await client.upsert_vertices("design-module", "module_id", [{"module_id": module}])
            module_created = True
            assert await client.get_vertex("requirement", requirement) is not None
            assert await client.get_vertex("design-module", module) is not None
            await client.upsert_edges("requirement-modules", "requirement", "design-module", [(requirement, module)])
            edges = await client.sample_edges("requirement-modules")
            requirement_id = await client.vertex_id("requirement", requirement)
            module_id = await client.vertex_id("design-module", module)
            assert any(edge["outV"] == requirement_id and edge["inV"] == module_id for edge in edges)
            await client.delete_vertex("requirement", requirement)
            requirement_created = False
            assert await client.get_vertex("requirement", requirement) is None
            await client.delete_vertex("requirement", requirement)
            assert all(edge["outV"] != requirement_id for edge in await client.sample_edges("requirement-modules"))
            await client.delete_vertex("design-module", module)
            module_created = False
            assert await client.get_vertex("design-module", module) is None
        finally:
            if requirement_created:
                await client.delete_vertex("requirement", requirement)
            if module_created:
                await client.delete_vertex("design-module", module)
    finally:
        await client.aclose()


@pytest.mark.skipif(not os.environ.get("ONTOGENY_TEST_HUGEGRAPH_URL"), reason="requires a disposable HugeGraph server")
async def test_live_mixed_primary_key_edges_and_archive():
    token = uuid.uuid4().hex[:10]
    number, name, relation = (f"smoke_{kind}_{token}" for kind in ("number", "name", "relation"))
    schema = {
        "propertykeys": [{"name": number, "data_type": "INT"}, {"name": name, "data_type": "TEXT"}],
        "vertexlabels": [{"label": p, "primary_keys": [p], "properties": [p]} for p in (number, name)],
        "edgelabels": [{"name": relation, "source_label": number, "target_label": name}],
        "indexes": [],
    }
    client = HugeGraphClient(os.environ["ONTOGENY_TEST_HUGEGRAPH_URL"], "hugegraph")
    text_key = f"name:{token}!`>"
    try:
        assert await client.dialect() == "1.7"
        await client.ensure_schema(schema)
        try:
            await client.upsert_vertices(number, number, [{number: 64}])
            await client.upsert_vertices(name, name, [{name: text_key}])
            await client.upsert_edges(relation, number, name, [("64", text_key)])
            numeric_id = (await client.get_vertex(number, "64"))["id"]
            text_id = (await client.get_vertex(name, text_key))["id"]
            [edge] = await client.sample_edges(relation)
            assert (edge["outV"], edge["inV"]) == (numeric_id, text_id)
        finally:
            await client.delete_vertex(number, "64")
            await client.delete_vertex(name, text_key)
        assert await client.get_vertex(number, "64") is None
        assert await client.get_vertex(name, text_key) is None
    finally:
        await client.aclose()
