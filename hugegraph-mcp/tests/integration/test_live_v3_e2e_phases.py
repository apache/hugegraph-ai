# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""End-to-end live integration test covering Phase 0-6 capabilities against real HugeGraph & PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp import Client
from jwt.algorithms import RSAAlgorithm
from starlette.testclient import TestClient

from hugegraph_mcp import server
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.oauth_verifier import OAuthBearerVerifier
from hugegraph_mcp.stores.base import Actor, ActorAuthorizationError
from hugegraph_mcp.target_context import resolve_authorized_target

pytestmark = [pytest.mark.integration, pytest.mark.real_hugegraph]

PG_DSN = os.getenv("HUGEGRAPH_MCP_TEST_PG_DSN", "postgresql://postgres:mcp_test_pass@127.0.0.1:15432/hugegraph_mcp")
HG_URL = os.getenv("HUGEGRAPH_URL", "http://127.0.0.1:8080")


def _extract_tool_json(result) -> dict:
    if hasattr(result, "data") and isinstance(result.data, dict):
        return result.data
    content = getattr(result, "content", None) or []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"Could not extract JSON from tool result: {result!r}")


def _resolve_llm_python(repo_root: str) -> str:
    """Resolve the Python interpreter for the local hugegraph-llm subprocess."""
    override = os.getenv("HUGEGRAPH_MCP_TEST_LLM_PYTHON")
    if override:
        return shutil.which(override) or override
    if sys.platform == "win32":
        return os.path.join(repo_root, ".venv-llm", "Scripts", "python.exe")
    return os.path.join(repo_root, ".venv-llm", "bin", "python")


def _build_llm_env(repo_root: str) -> dict[str, str]:
    """Build subprocess environment with platform-native PYTHONPATH and HUGEGRAPH_URL."""
    llm_env = os.environ.copy()
    llm_env["PYTHONPATH"] = os.pathsep.join(
        [
            os.path.join(repo_root, "hugegraph-llm", "src"),
            os.path.join(repo_root, "hugegraph-python-client", "src"),
            os.path.join(repo_root, "hugegraph-llm-sdk", "src"),
        ]
    )
    llm_env["HUGEGRAPH_URL"] = HG_URL
    return llm_env


@pytest.mark.integration
def test_live_e2e_phases_0_to_6_against_real_hugegraph_and_postgres(monkeypatch, tmp_path) -> None:
    if os.getenv("RUN_MCP_REAL_HUGEGRAPH_TESTS") != "1":
        pytest.skip("set RUN_MCP_REAL_HUGEGRAPH_TESTS=1 to run real HugeGraph E2E tests")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    suffix = uuid4().hex[:8]
    prop_name = f"e2e_name_{suffix}"
    note_prop = f"e2e_note_{suffix}"
    vlabel = f"e2e_person_{suffix}"
    elabel = f"e2e_knows_{suffix}"

    routes = [
        {
            "alias": "default",
            "graph_url": HG_URL,
            "graph_name": "hugegraph",
            "graphspace": "DEFAULT",
            "user": "admin",
            "route_version": 1,
            # The in-process stdio client uses the local operator's default tenant.
            "allowed_tenants": ["default", "e2e-tenant"],
            "required_scopes": ["mcp:read"],
            "readonly": False,
        },
        {
            "alias": "readonly_mirror",
            "graph_url": HG_URL,
            "graph_name": "hugegraph",
            "graphspace": "DEFAULT",
            "user": "admin",
            "route_version": 2,
            "allowed_tenants": ["e2e-tenant"],
            "required_scopes": ["mcp:read"],
            "readonly": True,
        },
    ]

    monkeypatch.setenv("HUGEGRAPH_URL", HG_URL)
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "hugegraph")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_CORE_PROFILE", "lean")
    monkeypatch.setenv("HUGEGRAPH_MCP_CONFIRMATION_MODE", "manual")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE", "postgres")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE_DSN", PG_DSN)
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HUGEGRAPH_MCP_GRAPH_ROUTES", json.dumps(routes))

    cfg = MCPConfig.from_env()
    lean_server = server.create_server(cfg)

    async def _run_mcp_flow() -> dict[str, str]:
        async with Client(lean_server) as client:
            tools = await client.list_tools()
            tool_names = {t.name for t in tools}
            # Phase 1: lean surface hides legacy/granular write tools and exposes prepare_write_tool
            assert "prepare_write_tool" in tool_names
            assert "retrieve_context_tool" in tool_names
            assert "validate_schema_tool" in tool_names
            assert "apply_schema_tool" not in tool_names

            # Phase 3: validate_schema_tool via artifact:// resource
            from hugegraph_mcp.artifacts import get_default_artifact_store
            from hugegraph_mcp.stores.base import default_stdio_actor

            actor = default_stdio_actor()
            schema_draft = {
                "propertykeys": [
                    {"name": prop_name, "data_type": "TEXT", "cardinality": "SINGLE"},
                    {"name": note_prop, "data_type": "TEXT", "cardinality": "SINGLE"},
                ],
                "vertexlabels": [
                    {
                        "name": vlabel,
                        "id_strategy": "PRIMARY_KEY",
                        "properties": [prop_name, note_prop],
                        "primary_keys": [prop_name],
                        "nullable_keys": [note_prop],
                    }
                ],
                "edgelabels": [{"name": elabel, "source_label": vlabel, "target_label": vlabel}],
                "indexlabels": [],
            }
            manifest = get_default_artifact_store(cfg).put(
                json.dumps(schema_draft),
                owner_key=actor.principal_key,
                tenant=actor.tenant,
                target_graph={"url": HG_URL, "graph": "hugegraph", "graphspace": "DEFAULT"},
                kind="schema_draft",
            )
            part_res = await client.read_resource(f"artifact://{manifest.artifact_id}/parts/0")
            assert prop_name in part_res[0].text

            val_res = _extract_tool_json(
                await client.call_tool("validate_schema_tool", {"artifact_id": manifest.artifact_id})
            )
            assert val_res["ok"] is True, val_res
            assert val_res["data"]["valid"] is True

            # Phase 1 + Real HugeGraph: prepare_write_tool(kind='schema') -> confirm_write_tool
            for schema_op in [
                {"type": "create_property_key", "name": prop_name, "data_type": "TEXT", "cardinality": "SINGLE"},
                {"type": "create_property_key", "name": note_prop, "data_type": "TEXT", "cardinality": "SINGLE"},
                {
                    "type": "create_vertex_label",
                    "name": vlabel,
                    "id_strategy": "PRIMARY_KEY",
                    "primary_keys": [prop_name],
                    "properties": [prop_name, note_prop],
                    "nullable_keys": [note_prop],
                },
                {
                    "type": "create_edge_label",
                    "name": elabel,
                    "source_label": vlabel,
                    "target_label": vlabel,
                },
            ]:
                prep_schema = _extract_tool_json(
                    await client.call_tool(
                        "prepare_write_tool",
                        {"kind": "schema", "mode": "dry_run", "operations": [schema_op]},
                    )
                )
                assert prep_schema["ok"] is True, prep_schema
                assert prep_schema["data"].get("plan_id"), prep_schema
                conf_schema = _extract_tool_json(
                    await client.call_tool("confirm_write_tool", {"plan_id": prep_schema["data"]["plan_id"]})
                )
                assert conf_schema["ok"] is True, conf_schema
                assert conf_schema["data"]["status"] == "APPLIED"

            # Phase 1 + Real HugeGraph 1.7.0 capability gate: prepare_write_tool(kind='import') is preview-only
            prep_import = _extract_tool_json(
                await client.call_tool(
                    "prepare_write_tool",
                    {
                        "kind": "import",
                        "graph_data": {
                            "vertices": [{"label": vlabel, "properties": {prop_name: "Alice"}}],
                            "edges": [],
                        },
                    },
                )
            )
            assert prep_import["ok"] is True, prep_import
            assert prep_import["data"]["valid"] is True
            assert prep_import["data"].get("plan_id") is None
            assert any("preview-only" in w for w in prep_import.get("warnings", []))

            # Seed real vertices & edges via PyHugeClient for Phase 2 & Phase 4 read/traversal/retrieval E2E
            from hugegraph_mcp.hugegraph_client import build_hugegraph_client

            g = build_hugegraph_client(cfg).graph()
            v_alice = g.addVertex(vlabel, {prop_name: "Alice"})
            v_bob = g.addVertex(vlabel, {prop_name: "Bob"})
            v_carol = g.addVertex(vlabel, {prop_name: "Carol"})
            v_dave = g.addVertex(vlabel, {prop_name: "Dave"})
            g.addEdge(elabel, v_alice.id, v_bob.id, {})
            g.addEdge(elabel, v_alice.id, v_carol.id, {})
            g.addEdge(elabel, v_bob.id, v_dave.id, {})

            # Phase 2: query_graph_data_tool with fields projection & cursor pagination against real HugeGraph
            q1 = _extract_tool_json(
                await client.call_tool(
                    "query_graph_data_tool",
                    {
                        "target": "vertex",
                        "operation": "page",
                        "label": vlabel,
                        "limit": 2,
                        "fields": [f"properties.{prop_name}"],
                    },
                )
            )
            assert q1["ok"] is True, q1
            assert q1["data"]["count"] == 2
            assert q1["data"]["has_more"] is True
            assert all(list(item["properties"].keys()) == [prop_name] for item in q1["data"]["items"])

            q2 = _extract_tool_json(
                await client.call_tool(
                    "query_graph_data_tool",
                    {
                        "target": "vertex",
                        "operation": "page",
                        "label": vlabel,
                        "limit": 2,
                        "fields": [f"properties.{prop_name}"],
                        "cursor": q1["data"]["next_cursor"],
                    },
                )
            )
            assert q2["ok"] is True, q2
            assert q2["data"]["count"] >= 1
            alice_id = next(
                item["id"]
                for item in (q1["data"]["items"] + q2["data"]["items"])
                if item["properties"].get(prop_name) == "Alice"
            )
            bob_id = next(
                item["id"]
                for item in (q1["data"]["items"] + q2["data"]["items"])
                if item["properties"].get(prop_name) == "Bob"
            )

            # Phase 2: traverse_graph_tool snapshot cursor pagination against real HugeGraph
            t1 = _extract_tool_json(
                await client.call_tool(
                    "traverse_graph_tool",
                    {
                        "operation": "neighbors",
                        "source_id": alice_id,
                        "max_depth": 1,
                        "page_size": 1,
                    },
                )
            )
            assert t1["ok"] is True, t1
            assert t1["data"]["count"] == 1
            assert t1["data"]["has_more"] is True
            t2 = _extract_tool_json(
                await client.call_tool(
                    "traverse_graph_tool",
                    {
                        "operation": "neighbors",
                        "source_id": alice_id,
                        "max_depth": 1,
                        "page_size": 1,
                        "cursor": t1["data"]["next_cursor"],
                    },
                )
            )
            assert t2["ok"] is True, t2
            assert t2["data"]["count"] == 1

            carol_id = next(
                item["id"]
                for item in (q1["data"]["items"] + q2["data"]["items"])
                if item["properties"].get(prop_name) == "Carol"
            )

            # Item 2: prepare_write_tool(kind='properties') preview-only capability gate on real HugeGraph 1.7.0
            prep_prop = _extract_tool_json(
                await client.call_tool(
                    "prepare_write_tool",
                    {
                        "kind": "properties",
                        "target": "vertex",
                        "operation": "append",
                        "id": carol_id,
                        "properties": {note_prop: "Carol_Updated"},
                    },
                )
            )
            assert prep_prop["ok"] is True, prep_prop
            assert prep_prop["data"].get("confirmable") is False, prep_prop
            assert prep_prop["data"]["after"]["properties"][note_prop] == "Carol_Updated"
            assert any("Preview only" in w for w in prep_prop.get("warnings", [])), prep_prop

            # Item 2: prepare_write_tool(kind='delete') -> confirm_write_tool on real HugeGraph
            # delete_edge issues plan_id and commits; delete_vertex is preview-only under RocksDB capability gate
            prep_del_e = _extract_tool_json(
                await client.call_tool(
                    "prepare_write_tool",
                    {
                        "kind": "delete",
                        "change_plan": {
                            "operations": [
                                {
                                    "op": "delete_edge",
                                    "label": elabel,
                                    "source_label": vlabel,
                                    "target_label": vlabel,
                                    "source_match": {prop_name: "Bob"},
                                    "target_match": {prop_name: "Dave"},
                                }
                            ]
                        },
                    },
                )
            )
            assert prep_del_e["ok"] is True, prep_del_e
            assert prep_del_e["data"].get("plan_id"), prep_del_e
            conf_del_e = _extract_tool_json(
                await client.call_tool("confirm_write_tool", {"plan_id": prep_del_e["data"]["plan_id"]})
            )
            assert conf_del_e["ok"] is True, conf_del_e
            assert conf_del_e["data"]["status"] == "APPLIED"

            bob_neighbors = _extract_tool_json(
                await client.call_tool(
                    "traverse_graph_tool",
                    {"operation": "neighbors", "source_id": bob_id, "direction": "OUT", "max_depth": 1},
                )
            )
            assert bob_neighbors["ok"] is True, bob_neighbors
            assert bob_neighbors["data"]["count"] == 0, bob_neighbors

            prep_del_v = _extract_tool_json(
                await client.call_tool(
                    "prepare_write_tool",
                    {
                        "kind": "delete",
                        "change_plan": {
                            "operations": [
                                {
                                    "op": "delete_vertex",
                                    "label": vlabel,
                                    "match": {prop_name: "Dave"},
                                    "cascade": False,
                                }
                            ]
                        },
                    },
                )
            )
            assert prep_del_v["ok"] is True, prep_del_v
            assert prep_del_v["data"].get("confirmable") is False, prep_del_v

            return {"alice_id": str(alice_id), "bob_id": str(bob_id)}

    ids = asyncio.run(_run_mcp_flow())

    # Item 3: Stdio elicitation confirmation_mode='elicitation' via FastMCP Client elicitation_handler on real HugeGraph
    from dataclasses import replace as dc_replace

    from fastmcp.client.elicitation import ElicitResult

    elicit_cfg = dc_replace(cfg, confirmation_mode="elicitation", transport="stdio")
    elicit_server = server.create_server(elicit_cfg)
    monkeypatch.setenv("HUGEGRAPH_MCP_CONFIRMATION_MODE", "elicitation")

    async def _run_elicitation_flow() -> None:
        prompts_seen: list[str] = []
        decision = {"accept": False}

        async def _handler(message, response_type, params, context):
            prompts_seen.append(message)
            if decision["accept"]:
                return ElicitResult(action="accept", content=True)
            return ElicitResult(action="decline", content=False)

        elicit_prop = f"e2e_elicit_{suffix}"
        async with Client(elicit_server, elicitation_handler=_handler, mode="legacy") as e_client:
            prep_elicit = _extract_tool_json(
                await e_client.call_tool(
                    "prepare_write_tool",
                    {
                        "kind": "schema",
                        "mode": "dry_run",
                        "operations": [
                            {
                                "type": "create_property_key",
                                "name": elicit_prop,
                                "data_type": "TEXT",
                                "cardinality": "SINGLE",
                            }
                        ],
                    },
                )
            )
            assert prep_elicit["ok"] is True, prep_elicit
            elicit_plan_id = prep_elicit["data"]["plan_id"]

            # Decline first -> must NOT mutate real HugeGraph
            declined = _extract_tool_json(await e_client.call_tool("confirm_write_tool", {"plan_id": elicit_plan_id}))
            assert declined["ok"] is False, declined
            assert len(prompts_seen) == 1, declined

            schema_before = _extract_tool_json(await e_client.call_tool("inspect_schema_tool", {}))
            assert schema_before["ok"] is True, schema_before
            pk_names_before = {pk["name"] for pk in schema_before["data"]["summary"]["property_keys"]}
            assert elicit_prop not in pk_names_before

            # Accept second -> executes real HugeGraph write
            decision["accept"] = True
            accepted = _extract_tool_json(await e_client.call_tool("confirm_write_tool", {"plan_id": elicit_plan_id}))
            assert accepted["ok"] is True, accepted
            assert accepted["data"]["status"] == "APPLIED"
            assert len(prompts_seen) == 2

            schema_after = _extract_tool_json(await e_client.call_tool("inspect_schema_tool", {}))
            assert schema_after["ok"] is True, schema_after
            pk_names_after = {pk["name"] for pk in schema_after["data"]["summary"]["property_keys"]}
            assert elicit_prop in pk_names_after

    asyncio.run(_run_elicitation_flow())
    monkeypatch.setenv("HUGEGRAPH_MCP_CONFIRMATION_MODE", "manual")

    # Phase 6: OAuth RS256 JWT + HTTP app + graph_alias authorization
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "e2e-kid"
    verifier = OAuthBearerVerifier(
        issuer="https://idp.e2e.local",
        audience="hugegraph-mcp",
        jwks_payload={"keys": [public_jwk]},
    )
    now = int(time.time())
    valid_jwt = jwt.encode(
        {
            "iss": "https://idp.e2e.local",
            "aud": "hugegraph-mcp",
            "sub": "e2e-user",
            "tenant": "e2e-tenant",
            "scope": "mcp:read mcp:write",
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "e2e-kid"},
    )
    from dataclasses import replace as dc_replace

    http_cfg = dc_replace(cfg, transport="streamable-http")
    http_app = server.create_http_app(http_cfg, require_auth=True, verifier=verifier)
    with TestClient(http_app) as http_client:
        unauth = http_client.get("/healthz")
        assert unauth.status_code == 200
        rejected = http_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert rejected.status_code == 401
        authorized = http_client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {valid_jwt}",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "e2e-test", "version": "1.0"},
                },
            },
        )
        assert authorized.status_code == 200

    # Phase 6: graph_alias route enforcement & real read via resolved target
    actor_ok = Actor(
        issuer="https://idp.e2e.local",
        tenant="e2e-tenant",
        subject="e2e-user",
        scopes=frozenset({"mcp:read", "mcp:write"}),
    )
    ro_target = resolve_authorized_target(
        cfg,
        alias="readonly_mirror",
        expected_route_version=2,
        actor=actor_ok,
        write=False,
    )
    assert ro_target.alias == "readonly_mirror"
    from hugegraph_mcp.hugegraph_client import build_hugegraph_client

    ro_client = build_hugegraph_client(
        dc_replace(
            cfg,
            url=ro_target.graph_url,
            graph=ro_target.graph_name,
            graphspace=ro_target.graphspace,
        )
    )
    ro_vertex = ro_client.graph().getVertexById(ids["alice_id"])
    assert ro_vertex.properties[prop_name] == "Alice"
    with pytest.raises(ActorAuthorizationError, match="read-only"):
        resolve_authorized_target(cfg, alias="readonly_mirror", expected_route_version=2, actor=actor_ok, write=True)

    # Phase 4: verify live local hugegraph-llm thin_api /v1/retrieve-context against real HugeGraph
    import subprocess
    import urllib.request

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    llm_python = _resolve_llm_python(repo_root)
    if not os.path.isfile(llm_python):
        pytest.skip(f"LLM python not found for live thin_api subprocess: {llm_python}")

    llm_env = _build_llm_env(repo_root)
    server_script = (
        "import os, uvicorn; from fastapi import FastAPI; "
        "from hugegraph_llm.api.thin_api import thin_router; "
        "from hugegraph_llm.config import huge_settings; "
        "huge_settings.graph_url=os.environ['HUGEGRAPH_URL']; huge_settings.graph_name='hugegraph'; "
        "app=FastAPI(); app.include_router(thin_router); "
        "uvicorn.run(app, host='127.0.0.1', port=18001, log_level='warning')"
    )
    proc = subprocess.Popen([llm_python, "-c", server_script], env=llm_env)
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18001/openapi.json", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            raise AssertionError("Live thin_api subprocess did not become ready on 18001")

        llm_cfg = MCPConfig.from_env(
            {
                "HUGEGRAPH_URL": HG_URL,
                "HUGEGRAPH_GRAPH": "hugegraph",
                "HUGEGRAPH_MCP_ALLOW_AI": "true",
                "HUGEGRAPH_AI_URL": "http://127.0.0.1:18001",
            }
        )
        from hugegraph_mcp.tools.retrieve_context import retrieve_context

        r1 = retrieve_context(
            mode="graph",
            seed_ids=[ids["alice_id"], ids["bob_id"]],
            top_k=5,
            page_size=1,
            cfg=llm_cfg,
        )
        assert r1["ok"] is True, r1
        assert r1["data"]["count"] == 1
        assert r1["data"]["has_more"] is True
        r2 = retrieve_context(
            mode="graph",
            seed_ids=[ids["alice_id"], ids["bob_id"]],
            top_k=5,
            page_size=1,
            cursor=r1["data"]["next_cursor"],
            cfg=llm_cfg,
        )
        assert r2["ok"] is True, r2
        assert r2["data"]["count"] == 1
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.mark.integration
def test_live_v3_llm_extract_with_deepseek(monkeypatch, tmp_path) -> None:
    if os.getenv("RUN_MCP_REAL_HUGEGRAPH_TESTS") != "1":
        pytest.skip("set RUN_MCP_REAL_HUGEGRAPH_TESTS=1 to run real HugeGraph E2E tests")
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("set DEEPSEEK_API_KEY or OPENAI_API_KEY to run live LLM E2E tests")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import subprocess
    import urllib.request

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    llm_python = _resolve_llm_python(repo_root)
    if not os.path.isfile(llm_python):
        pytest.skip(f"LLM python not found for live thin_api subprocess: {llm_python}")

    suffix = uuid4().hex[:8]
    prop_name = f"ds_name_{suffix}"
    vlabel = f"ds_person_{suffix}"
    elabel = f"ds_knows_{suffix}"

    llm_env = _build_llm_env(repo_root)
    llm_env["OPENAI_BASE_URL"] = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    llm_env["OPENAI_API_KEY"] = api_key
    llm_env["OPENAI_CHAT_API_BASE"] = llm_env["OPENAI_BASE_URL"]
    llm_env["OPENAI_CHAT_API_KEY"] = api_key
    llm_env["OPENAI_EXTRACT_API_BASE"] = llm_env["OPENAI_BASE_URL"]
    llm_env["OPENAI_EXTRACT_API_KEY"] = api_key
    llm_env["OPENAI_TEXT2GQL_API_BASE"] = llm_env["OPENAI_BASE_URL"]
    llm_env["OPENAI_TEXT2GQL_API_KEY"] = api_key

    server_script = (
        "import os, uvicorn; from fastapi import FastAPI; "
        "from hugegraph_llm.api.thin_api import thin_router; "
        "from hugegraph_llm.config import huge_settings, llm_settings; "
        "huge_settings.graph_url=os.environ['HUGEGRAPH_URL']; huge_settings.graph_name='hugegraph'; "
        "llm_settings.chat_llm_type='openai'; llm_settings.extract_llm_type='openai'; "
        "llm_settings.text2gql_llm_type='openai'; "
        "llm_settings.openai_chat_language_model='deepseek-chat'; "
        "llm_settings.openai_extract_language_model='deepseek-chat'; "
        "llm_settings.openai_text2gql_language_model='deepseek-chat'; "
        "app=FastAPI(); app.include_router(thin_router); "
        "uvicorn.run(app, host='127.0.0.1', port=18002, log_level='warning')"
    )
    proc = subprocess.Popen([llm_python, "-c", server_script], env=llm_env)
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18002/openapi.json", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            raise AssertionError("Live thin_api subprocess did not become ready on 18002")

        monkeypatch.setenv("HUGEGRAPH_URL", HG_URL)
        monkeypatch.setenv("HUGEGRAPH_GRAPH", "hugegraph")
        monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
        monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "true")
        monkeypatch.setenv("HUGEGRAPH_AI_URL", "http://127.0.0.1:18002")
        monkeypatch.setenv("HUGEGRAPH_MCP_CORE_PROFILE", "lean")
        monkeypatch.setenv("HUGEGRAPH_MCP_CONFIRMATION_MODE", "manual")
        monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE", "postgres")
        monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE_DSN", PG_DSN)
        monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path / "state"))

        cfg = MCPConfig.from_env()
        lean_server = server.create_server(cfg)

        async def _run_deepseek_flow() -> None:
            async with Client(lean_server) as client:
                graph_schema = {
                    "vertexlabels": [
                        {
                            "name": vlabel,
                            "id_strategy": "PRIMARY_KEY",
                            "properties": [prop_name],
                            "primary_keys": [prop_name],
                        }
                    ],
                    "edgelabels": [
                        {
                            "name": elabel,
                            "source_label": vlabel,
                            "target_label": vlabel,
                            "properties": [],
                        }
                    ],
                }
                res = _extract_tool_json(
                    await client.call_tool(
                        "extract_graph_data_tool",
                        {
                            "text": f"Alice knows Bob. Both Alice and Bob are {vlabel} entities.",
                            "graph_schema": graph_schema,
                            "output": "artifact",
                        },
                    )
                )
                assert res["ok"] is True, res
                assert res["data"].get("artifact_id"), res
                assert str(res["data"].get("artifact_uri", "")).startswith("artifact://"), res

                part = await client.read_resource(f"artifact://{res['data']['artifact_id']}/parts/0")
                part_envelope = json.loads(part[0].text)
                extracted = json.loads(part_envelope["content"])
                graph_data = extracted["graph_data"]
                assert len(graph_data["vertices"]) >= 2, extracted
                assert len(graph_data["edges"]) >= 1, extracted

        asyncio.run(_run_deepseek_flow())
    finally:
        proc.terminate()
        proc.wait(timeout=5)
