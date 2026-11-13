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

"""Marked values cannot be inferred through queries or aggregate filters."""

import json

import httpx


async def test_marked_filters_require_claims_for_all_query_shapes(client):
    admin, sc = client
    assert (await admin.post("/api/v1/admin/sync/tapeout-version")).status_code == 200
    filters = [
        {"mask_cost": 1850000.0},
        {"field": "mask-cost", "op": "gt", "value": 0},  # normalized SQL name
        {"and": [{"project": "X1"}, {"or": [{"not": {"mask_cost": 1850000.0}}, {"project": "X1"}]}]},
    ]
    ordinary = {"X-Ontogeny-Principal": json.dumps({"id": "visitor"})}
    authorized = {"X-Ontogeny-Principal": json.dumps({"id": "cost-controller", "markings": ["internal"]})}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=admin._transport.app), base_url="http://anon") as c:
        for filt in filters:
            for headers in ({}, ordinary):
                response = await c.post("/api/v1/objects/tapeout-version/query", json={"filter": filt}, headers=headers)
                assert response.status_code == 403
                assert response.json()["code"] == "POLICY_DENIED"
                response = await c.post(
                    "/api/v1/objects/tapeout-version/aggregate",
                    json={"fn": "count", "filter": filt},
                    headers=headers,
                )
                assert response.status_code == 403
                assert response.json()["code"] == "POLICY_DENIED"

            response = await c.post("/api/v1/objects/tapeout-version/query", json={"filter": filt}, headers=authorized)
            assert response.status_code == 200
            response = await c.post(
                "/api/v1/objects/tapeout-version/aggregate", json={"fn": "count", "filter": filt}, headers=authorized
            )
            assert response.status_code == 200

        response = await c.post(
            "/api/v1/objects/tapeout-version/query", json={"filter": {"field": "version_id", "op": "ne", "value": ""}}
        )
        assert response.status_code == 200 and response.json()["total"] > 0

        filt = {"field": "mask-cost", "op": "gt", "value": 0}
        response = await c.post("/api/v1/objects/tapeout-version/query", json={"filter": filt}, headers=authorized)
        assert response.status_code == 200
        assert response.json()["total"] > 0
        assert all(obj["mask_cost"] != "__masked__" for obj in response.json()["objects"])
        response = await c.post(
            "/api/v1/objects/tapeout-version/aggregate", json={"fn": "count", "filter": filt}, headers=authorized
        )
        assert response.status_code == 200
        assert response.json()["value"] > 0

        response = await c.post(
            "/api/v1/objects/tapeout-version/query", json={"sort": [["mask-cost", "asc"]]}, headers=ordinary
        )
        assert response.status_code == 403
        response = await c.post(
            "/api/v1/objects/tapeout-version/aggregate", json={"fn": "avg", "field": "mask-cost"}, headers=ordinary
        )
        assert response.status_code == 403

    # Internal repository callers intentionally omit a principal and can read
    # real values for projection/function execution.
    async with sc.sessionmaker() as session:
        rows, total = await sc.repo.query(session, "tapeout-version", filt=filt)
        assert total > 0 and rows[0]["mask_cost"] is not None
