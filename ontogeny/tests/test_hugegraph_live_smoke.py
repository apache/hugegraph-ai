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
manufacturing projection's schema and writes then removes its own test data.
"""

import os
import uuid

import pytest
from ontogeny_ext_hugegraph import HugeGraphClient

from ontogeny.projection import compile_projection
from ontogeny.registry import compile_package


@pytest.mark.skipif(not os.environ.get("ONTOGENY_TEST_HUGEGRAPH_URL"), reason="requires a disposable HugeGraph server")
async def test_live_manufacturing_schema_vertices_and_edge(golden_pkg):
    compiled = compile_package(golden_pkg)
    schema = compile_projection(compiled, compiled.projections["production-graph"])
    token = uuid.uuid4().hex
    product, bom = f"smoke-product-{token}", f"smoke-bom-{token}"
    client = HugeGraphClient(os.environ["ONTOGENY_TEST_HUGEGRAPH_URL"], "hugegraph")
    try:
        assert await client.dialect() == "1.7"
        assert await client.exists() is True
        await client.ensure_schema(schema)
        # Outbox delivery is at least once: deleting an object that never
        # existed, or replaying a successful delete, must both succeed.
        await client.delete_vertex("product", product)
        product_created = bom_created = False
        try:
            await client.upsert_vertices("product", "product_id", [{"product_id": product, "name": "Smoke"}])
            product_created = True
            await client.upsert_vertices("bom", "bom_id", [{"bom_id": bom}])
            bom_created = True
            assert await client.get_vertex("product", product) is not None
            assert await client.get_vertex("bom", bom) is not None
            await client.upsert_edges("bom-product", "product", "bom", [(product, bom)])
            edges = await client.sample_edges("bom-product")
            product_id = await client.vertex_id("product", product)
            bom_id = await client.vertex_id("bom", bom)
            assert any(edge["outV"] == product_id and edge["inV"] == bom_id for edge in edges)
            await client.delete_vertex("product", product)
            product_created = False
            assert await client.get_vertex("product", product) is None
            await client.delete_vertex("product", product)
            assert all(edge["outV"] != product_id for edge in await client.sample_edges("bom-product"))
            await client.delete_vertex("bom", bom)
            bom_created = False
            assert await client.get_vertex("bom", bom) is None
        finally:
            if product_created:
                await client.delete_vertex("product", product)
            if bom_created:
                await client.delete_vertex("bom", bom)
    finally:
        await client.aclose()
