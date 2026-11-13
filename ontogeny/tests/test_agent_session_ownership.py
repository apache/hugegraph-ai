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
# specific language governing permissions and
# limitations under the License.

"""Cross-user authorization on the REST and MCP session protocols."""

from __future__ import annotations

import json

from ontogeny.mcp_server import _MCP_DRIVER, in_process_mcp_session


def headers(name, **extra):
    return {"X-Ontogeny-Principal": json.dumps({"id": name, **extra})}


async def test_rest_sessions_are_private_to_driver_or_admin(client):
    c, sc = client
    plugin = next(iter(sc.compiled.agent_plugins))
    own = (
        await c.post("/api/v1/agent/sessions", json={"plugin": plugin, "task": "alice"}, headers=headers("alice"))
    ).json()
    other = (
        await c.post("/api/v1/agent/sessions", json={"plugin": plugin, "task": "bob"}, headers=headers("bob"))
    ).json()
    legacy = await sc.agents.open_session(plugin, "legacy without a driver")
    anonymous = await sc.agents.open_session(plugin, "old anonymous demo", driver={"id": "anonymous"})
    from ontogeny.agent.models import AgentApprovalRow

    async with sc.sessionmaker() as db:
        for owner in (own, other):
            db.add(
                AgentApprovalRow(
                    session_id=owner["id"],
                    plugin=plugin,
                    tool="act_example",
                    action="example",
                    parameters={"private": owner["task"]},
                )
            )
        await db.commit()
    approval_list = (await c.get("/api/v1/agent/approvals", headers=headers("alice"))).json()["approvals"]
    assert [a["session_id"] for a in approval_list] == [own["id"]]
    assert len((await c.get("/api/v1/agent/approvals")).json()["approvals"]) == 2
    sid = other["id"]
    listing = await c.get("/api/v1/agent/sessions?limit=1", headers=headers("alice"))
    assert [s["id"] for s in listing.json()["sessions"]] == [own["id"]]
    for session_id in (sid, legacy["id"], anonymous["id"]):
        base = f"/api/v1/agent/sessions/{session_id}"
        for method, suffix, body in (
            ("GET", "", None),
            ("POST", "/run", {}),
            ("POST", "/finish", {"result": {"forged": True}}),
            ("POST", "/tools/describe_ontology", {}),
            ("DELETE", "", None),
        ):
            response = await c.request(method, base + suffix, json=body, headers=headers("alice"))
            assert response.status_code == 403, (suffix, response.text)
    unchanged = await sc.agents.get_session(sid)
    assert unchanged["status"] == "open"
    assert unchanged["budget"]["steps_used"] == 0
    assert unchanged["run_count"] == 0
    assert (await c.get(f"/api/v1/agent/sessions/{sid}", headers=headers("bob"))).status_code == 200
    assert (await c.get(f"/api/v1/agent/sessions/{legacy['id']}")).status_code == 200
    assert (
        await c.post(
            f"/api/v1/agent/sessions/{sid}/finish", json={"result": {}}, headers=headers("admin", is_admin=True)
        )
    ).status_code == 200


async def test_mcp_sessions_enforce_same_ownership_and_private_engine_path(client):
    _, sc = client
    plugin = next(iter(sc.compiled.agent_plugins))
    alice = await sc.agents.open_session(plugin, "alice", driver={"id": "alice"})
    bob = await sc.agents.open_session(plugin, "bob", driver={"id": "bob"})
    legacy = await sc.agents.open_session(plugin, "legacy")
    token = _MCP_DRIVER.set({"id": "alice", "authenticated": True})
    try:
        async with in_process_mcp_session(sc, engine_mode=False) as mcp:
            listing = await mcp.call_tool("agent_list_sessions", {})
            assert [s["id"] for s in listing["sessions"]] == [alice["id"]]
            assert (await mcp.call_tool("agent_get_session", {"session_id": alice["id"]}))["id"] == alice["id"]
            for session_id in (bob["id"], legacy["id"]):
                for name, params in (
                    ("agent_get_session", {}),
                    ("agent_finish_session", {"result": {}}),
                    ("describe_ontology", {}),
                ):
                    out = await mcp.call_tool(name, {"session_id": session_id, **params})
                    assert out["outcome"] == "MCP_TOOL_ERROR", out
    finally:
        _MCP_DRIVER.reset(token)
    unchanged = await sc.agents.get_session(bob["id"])
    assert unchanged["status"] == "open"
    assert unchanged["budget"]["steps_used"] == 0
    token = _MCP_DRIVER.set({"id": "administrator", "is_admin": True})
    try:
        async with in_process_mcp_session(sc, engine_mode=False) as admin:
            listing = await admin.call_tool("agent_list_sessions", {})
            assert {s["id"] for s in listing["sessions"]} == {alice["id"], bob["id"], legacy["id"]}
            assert (await admin.call_tool("agent_get_session", {"session_id": legacy["id"]}))["id"] == legacy["id"]
    finally:
        _MCP_DRIVER.reset(token)
    token = _MCP_DRIVER.set(None)
    try:
        async with in_process_mcp_session(sc, engine_mode=False) as external:
            assert (await external.call_tool("agent_list_sessions", {}))["sessions"] == []
            denied = await external.call_tool("agent_get_session", {"session_id": legacy["id"]})
            assert denied["outcome"] == "MCP_TOOL_ERROR"
        async with in_process_mcp_session(sc, engine_mode=True) as internal:
            out = await internal.call_tool("describe_ontology", {"session_id": legacy["id"]})
            assert out["outcome"] == "ok"
    finally:
        _MCP_DRIVER.reset(token)
