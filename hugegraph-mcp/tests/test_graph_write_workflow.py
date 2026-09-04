# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

from __future__ import annotations

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.plan_hash import PlanContext
from hugegraph_mcp.plan_store import SQLitePlanStore
from hugegraph_mcp.reconciler import reconcile_operation_state
from hugegraph_mcp.tools import graph_write_adapter
from hugegraph_mcp.tools.graph_write_plan import (
    CREATE_EDGE,
    CREATE_VERTEX,
    DELETE_EDGE,
    compile_graph_write_plan,
)
from hugegraph_mcp.tools.manage_graph_data import manage_graph_data
from hugegraph_mcp.write_executor import (
    DEFAULT_WRITE_EXECUTOR_REGISTRY,
    WriteExecutor,
    confirm_write,
)
from hugegraph_mcp.write_plan import ApplyStatus


def _schema():
    return {
        "schema": {
            "propertykeys": [{"name": "name", "data_type": "TEXT"}],
            "vertexlabels": [
                {
                    "name": "person",
                    "properties": ["name"],
                    "primary_keys": ["name"],
                }
            ],
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "frequency": "SINGLE",
                    "properties": [],
                }
            ],
        }
    }


def _context() -> PlanContext:
    cfg = MCPConfig.from_env()
    return PlanContext(
        tool_name="manage_graph_data",
        mode="import",
        graph_url=cfg.url,
        graph_name=cfg.graph,
        graphspace=cfg.graphspace or "DEFAULT",
        principal=cfg.user,
        readonly=False,
        payload_digest="legacy-digest",
        schema_hash="schema",
        nonce="nonce",
        expires_at=4_102_444_800,
    )


def _import_plan():
    return compile_graph_write_plan(
        {
            "operations": [
                {
                    "op": "create_vertex",
                    "label": "person",
                    "properties": {"name": "Alice"},
                },
                {
                    "op": "create_vertex",
                    "label": "person",
                    "properties": {"name": "Bob"},
                },
                {
                    "op": "create_edge",
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source_operation_index": 0,
                    "target_operation_index": 1,
                    "source_match": {"name": "Alice"},
                    "target_match": {"name": "Bob"},
                    "properties": {},
                },
            ]
        },
        plan_context=_context(),
        live_schema=_schema(),
    )


def test_import_compiles_ordered_receipt_dependencies():
    plan = _import_plan()

    assert [operation.kind for operation in plan.operations] == [
        CREATE_VERTEX,
        CREATE_VERTEX,
        CREATE_EDGE,
    ]
    edge = plan.operations[2]
    assert edge.depends_on == (
        plan.operations[0].operation_id,
        plan.operations[1].operation_id,
    )
    assert edge.target["source"] == {"operation_id": plan.operations[0].operation_id}
    assert "source_match" not in edge.target["source"]


def test_default_registry_fails_closed_for_unverified_graph_creates():
    assert DEFAULT_WRITE_EXECUTOR_REGISTRY.adapter_for(CREATE_VERTEX) is None
    assert DEFAULT_WRITE_EXECUTOR_REGISTRY.adapter_for(CREATE_EDGE) is None
    assert DEFAULT_WRITE_EXECUTOR_REGISTRY.adapter_for(DELETE_EDGE) is not None


def test_executor_persists_vertex_ids_before_dependent_edge(monkeypatch, tmp_path):
    plan = _import_plan()
    store = SQLitePlanStore(tmp_path / "state")
    store.save_plan(plan)
    monkeypatch.setattr(graph_write_adapter, "plan_store_from_config", lambda: store)
    state = {"vertices": {}, "edge": None}

    def fake_read(query):
        if ".outE('knows')" in query:
            data = [state["edge"]] if state["edge"] is not None else []
        elif query.startswith("g.V('alice-id')"):
            data = [state["vertices"]["Alice"]] if "Alice" in state["vertices"] else []
        elif query.startswith("g.V('bob-id')"):
            data = [state["vertices"]["Bob"]] if "Bob" in state["vertices"] else []
        elif ".has('name','Alice')" in query:
            data = [state["vertices"]["Alice"]] if "Alice" in state["vertices"] else []
        elif ".has('name','Bob')" in query:
            data = [state["vertices"]["Bob"]] if "Bob" in state["vertices"] else []
        else:
            data = []
        return {"ok": True, "data": {"data": data}}

    def fake_write(query, **_kwargs):
        if "addV('person')" in query and "'Alice'" in query:
            state["vertices"]["Alice"] = {
                "id": "alice-id",
                "label": "person",
                "name": "Alice",
            }
        elif "addV('person')" in query and "'Bob'" in query:
            state["vertices"]["Bob"] = {
                "id": "bob-id",
                "label": "person",
                "name": "Bob",
            }
        elif ".addE('knows')" in query:
            assert "g.V('alice-id')" in query
            assert ".V('bob-id')" in query
            state["edge"] = {"id": "edge-id", "label": "knows"}
        return {"ok": True, "data": {"affected": 1}}

    monkeypatch.setattr(graph_write_adapter.gremlin_tools, "execute_gremlin_read", fake_read)
    monkeypatch.setattr(graph_write_adapter.gremlin_tools, "execute_gremlin_write", fake_write)

    result = WriteExecutor(
        store=store,
        registry=graph_write_adapter_registry(),
    ).confirm(plan.plan_id)

    assert result["ok"] is True
    assert result["data"]["status"] == "APPLIED"
    record = store.get_plan_record(plan.plan_id)
    assert record is not None
    assert record["operations"][0]["receipt"]["observed_state"]["id"] == "alice-id"
    assert record["operations"][1]["receipt"]["observed_state"]["id"] == "bob-id"
    assert record["operations"][2]["receipt"]["observed_state"]["id"] == "edge-id"


def test_create_reconcile_classifies_exact_missing_conflict_and_duplicates(monkeypatch):
    vertex = _import_plan().operations[0]
    responses = iter(
        [
            [{"id": "v1", "label": "person", "name": "Alice"}],
            [],
            [{"id": "v1", "label": "person", "name": "Mallory"}],
            [
                {"id": "v1", "label": "person", "name": "Alice"},
                {"id": "v2", "label": "person", "name": "Alice"},
            ],
        ]
    )
    monkeypatch.setattr(
        graph_write_adapter.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"ok": True, "data": {"data": next(responses)}},
    )

    exact = graph_write_adapter.create_vertex_reader(_import_plan(), vertex)
    missing = graph_write_adapter.create_vertex_reader(_import_plan(), vertex)
    conflict = graph_write_adapter.create_vertex_reader(_import_plan(), vertex)
    duplicate = graph_write_adapter.create_vertex_reader(_import_plan(), vertex)

    assert exact == vertex.desired_state
    assert missing == vertex.expected_state
    assert conflict["properties"] == {"name": "Mallory"}
    assert duplicate["ambiguous"] is True


def test_create_edge_reconcile_rejects_indistinguishable_duplicates(monkeypatch):
    plan = compile_graph_write_plan(
        {
            "operations": [
                {
                    "op": "create_edge",
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source_id": "alice-id",
                    "target_id": "bob-id",
                    "properties": {},
                }
            ]
        },
        plan_context=_context(),
        live_schema=_schema(),
    )
    edge = plan.operations[0]
    responses = iter(
        [
            [{"id": "e1", "label": "knows"}],
            [],
            [{"id": "e1", "label": "other"}],
            [
                {"id": "e1", "label": "knows"},
                {"id": "e2", "label": "knows"},
            ],
        ]
    )
    monkeypatch.setattr(
        graph_write_adapter.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"ok": True, "data": {"data": next(responses)}},
    )

    assert graph_write_adapter.create_edge_reader(plan, edge) == edge.desired_state
    assert graph_write_adapter.create_edge_reader(plan, edge) == edge.expected_state
    assert graph_write_adapter.create_edge_reader(plan, edge)["label"] == "other"
    assert graph_write_adapter.create_edge_reader(plan, edge)["ambiguous"] is True


def test_delete_edge_receipt_and_reader_keep_stable_backend_identity(
    monkeypatch,
):
    plan = compile_graph_write_plan(
        {
            "operations": [
                {
                    "op": "delete_edge",
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source_match": {"id": "alice-id"},
                    "target_match": {"id": "bob-id"},
                    "target_id": "edge-id",
                }
            ]
        },
        plan_context=_context(),
        live_schema=_schema(),
    )
    operation = plan.operations[0]
    assert operation.kind == DELETE_EDGE
    responses = iter([[{"id": "edge-id", "label": "knows"}], []])
    monkeypatch.setattr(
        graph_write_adapter.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"ok": True, "data": {"data": next(responses)}},
    )
    writes = []
    monkeypatch.setattr(
        graph_write_adapter.gremlin_tools,
        "execute_gremlin_write",
        lambda query, **_kwargs: writes.append(query) or {"ok": True, "data": {"affected": 1}},
    )

    receipt = graph_write_adapter.delete_edge_adapter(plan, operation, 1)

    assert receipt.status is ApplyStatus.APPLIED
    assert receipt.observed_state == {
        "exists": False,
        "element_type": "edge",
        "id": "edge-id",
        "label": "knows",
    }
    assert writes == ["g.E('edge-id').drop()"]


def test_delete_edge_reconcile_distinguishes_absent_expected_and_conflict(
    monkeypatch,
):
    plan = compile_graph_write_plan(
        {
            "operations": [
                {
                    "op": "delete_edge",
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source_match": {"id": "alice-id"},
                    "target_match": {"id": "bob-id"},
                    "target_id": "edge-id",
                }
            ]
        },
        plan_context=_context(),
        live_schema=_schema(),
    )
    operation = plan.operations[0]
    responses = iter(
        [
            [],
            [{"id": "edge-id", "label": "knows"}],
            [{"id": "edge-id", "label": "other"}],
        ]
    )
    monkeypatch.setattr(
        graph_write_adapter.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"ok": True, "data": {"data": next(responses)}},
    )

    statuses = [
        reconcile_operation_state(
            operation.kind,
            operation.expected_state,
            operation.desired_state,
            graph_write_adapter.delete_reader(plan, operation),
        )
        for _ in range(3)
    ]

    assert statuses == [
        ApplyStatus.APPLIED,
        ApplyStatus.RETRYABLE_NOT_APPLIED,
        ApplyStatus.CONFLICT,
    ]


def test_delete_edge_dry_run_plan_id_routes_through_canonical_executor(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(
        "hugegraph_mcp.tools.manage_graph_data._fetch_live_schema",
        _schema,
    )
    state = {"exists": True}

    def fake_read(query):
        if query.endswith(".count()"):
            data = [1]
        elif query.endswith(".limit(2).id()"):
            data = ["edge-id"]
        elif query == "g.E('edge-id').limit(2).elementMap()":
            data = [{"id": "edge-id", "label": "knows"}] if state["exists"] else []
        else:
            data = []
        return {"ok": True, "data": {"data": data}}

    def fake_write(query, **_kwargs):
        assert query == "g.E('edge-id').drop()"
        state["exists"] = False
        return {"ok": True, "data": {"affected": 1}}

    monkeypatch.setattr(graph_write_adapter.gremlin_tools, "execute_gremlin_read", fake_read)
    monkeypatch.setattr(graph_write_adapter.gremlin_tools, "execute_gremlin_write", fake_write)
    preview = manage_graph_data(
        mode="delete",
        change_plan={
            "operations": [
                {
                    "op": "delete_edge",
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source_match": {"name": "Alice"},
                    "target_match": {"name": "Bob"},
                }
            ]
        },
    )

    result = confirm_write(preview["data"]["plan_id"])

    assert preview["data"]["confirmable"] is True
    assert result["ok"] is True
    assert result["data"]["status"] == "APPLIED"
    assert result["data"]["operations"][0]["receipt"]["observed_state"]["id"] == "edge-id"


def graph_write_adapter_registry():
    from hugegraph_mcp.write_executor import WriteExecutorRegistry

    registry = WriteExecutorRegistry()
    registry.register(CREATE_VERTEX, graph_write_adapter.create_vertex_adapter)
    registry.register(CREATE_EDGE, graph_write_adapter.create_edge_adapter)
    return registry
