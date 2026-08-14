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

from unittest.mock import Mock

from hugegraph_mcp.tools import mutate_graph_properties as mutate_module


def _schema():
    return {
        "schema": {
            "propertykeys": [
                {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
                {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
                {"name": "aliases", "data_type": "TEXT", "cardinality": "LIST"},
                {"name": "tags", "data_type": "TEXT", "cardinality": "SET"},
            ],
            "vertexlabels": [
                {
                    "name": "person",
                    "properties": ["name", "age", "aliases", "tags"],
                    "primary_keys": ["name"],
                }
            ],
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "properties": ["age", "aliases", "tags"],
                }
            ],
            "indexlabels": [],
        },
        "readonly": False,
    }


class FakeGraphManager:
    def __init__(self, vertex=None, changed_vertex=None):
        self.vertex = vertex or {
            "id": "1:alice",
            "label": "person",
            "type": "vertex",
            "properties": {"name": "Alice"},
        }
        self.changed_vertex = changed_vertex
        self.read_count = 0
        self.append_calls = []
        self.eliminate_calls = []

    def getVertexById(self, vertex_id):
        self.read_count += 1
        if self.changed_vertex is not None and self.read_count >= 2:
            return self.changed_vertex
        return self.vertex

    def getEdgeById(self, edge_id):
        return {
            "id": edge_id,
            "label": "knows",
            "type": "edge",
            "properties": {"age": 1},
        }

    def appendVertex(self, vertex_id, properties):
        self.append_calls.append((vertex_id, properties))
        self.vertex = {
            **self.vertex,
            "properties": {**self.vertex["properties"], **properties},
        }
        return self.vertex

    def eliminateVertex(self, vertex_id, properties):
        self.eliminate_calls.append((vertex_id, properties))
        self.vertex = {
            **self.vertex,
            "properties": {
                key: value
                for key, value in self.vertex["properties"].items()
                if key not in properties
            },
        }
        return self.vertex


class MissingTargetManager:
    def getVertexById(self, vertex_id):
        raise RuntimeError("404 Not Found: vertex does not exist")

    def getEdgeById(self, edge_id):
        raise RuntimeError("404 Not Found: edge does not exist")


class PostReadFailureManager(FakeGraphManager):
    def __init__(self):
        super().__init__()
        self.post_read_error = RuntimeError(
            "post read failed: Authorization: Bearer abc123 "
            "token=xyz http://user:pass@example.com"
        )

    def getVertexById(self, vertex_id):
        if self.append_calls:
            raise self.post_read_error
        return super().getVertexById(vertex_id)


class PostReadMissingManager(FakeGraphManager):
    def getVertexById(self, vertex_id):
        if self.append_calls:
            return None
        return super().getVertexById(vertex_id)


class PostReadMismatchManager(FakeGraphManager):
    def getVertexById(self, vertex_id):
        if self.append_calls:
            return {
                **self.vertex,
                "properties": {"name": "Alice", "age": 31},
            }
        return super().getVertexById(vertex_id)


class ExecutionFailureManager(FakeGraphManager):
    def appendVertex(self, vertex_id, properties):
        self.append_calls.append((vertex_id, properties))
        raise RuntimeError("404 Not Found: vertex does not exist")


class CollectionGraphManager(FakeGraphManager):
    def __init__(self, *, target="vertex", property_name="tags", values=None):
        super().__init__(
            vertex={
                "id": "1:alice",
                "label": "person",
                "type": "vertex",
                "properties": {property_name: list(values or [])},
            }
        )
        self.target = target
        self.property_name = property_name
        self.edge = {
            "id": "edge-1",
            "label": "knows",
            "type": "edge",
            "properties": {property_name: list(values or [])},
        }

    def getEdgeById(self, edge_id):
        return self.edge

    def appendVertex(self, vertex_id, properties):
        self.append_calls.append((vertex_id, properties))
        self.vertex = self._append(self.vertex, properties)
        return self.vertex

    def appendEdge(self, edge_id, properties):
        self.append_calls.append((edge_id, properties))
        self.edge = self._append(self.edge, properties)
        return self.edge

    def _append(self, item, properties):
        values = [
            *item["properties"][self.property_name],
            *properties[self.property_name],
        ]
        if self.property_name == "tags":
            values = list(dict.fromkeys(values))
        return {**item, "properties": {self.property_name: values}}


class ReorderedSetGraphManager(CollectionGraphManager):
    def getVertexById(self, vertex_id):
        item = super().getVertexById(vertex_id)
        if self.append_calls:
            return {
                **item,
                "properties": {
                    **item["properties"],
                    self.property_name: list(
                        reversed(item["properties"][self.property_name])
                    ),
                },
            }
        return item


def _patch_schema(monkeypatch):
    monkeypatch.setattr(mutate_module, "current_live_schema", lambda: _schema())


def test_mutate_dry_run_returns_snapshot_bound_plan(monkeypatch):
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "planned"
    assert result["data"]["before"]["properties"] == {"name": "Alice"}
    assert result["data"]["after"]["properties"] == {"name": "Alice", "age": 30}
    assert result["data"]["plan_hash"]
    assert "|ts:" in result["data"]["plan_context"]["nonce"]


def test_mutate_readonly_preview_does_not_issue_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    _patch_schema(monkeypatch)
    monkeypatch.setattr(mutate_module, "_graph_manager", FakeGraphManager)
    issue = Mock()
    monkeypatch.setattr(mutate_module, "issue_plan", issue)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )

    assert result["ok"] is True
    assert result["data"]["confirmable"] is False
    assert result["data"]["readonly_preview_only"] is True
    issue.assert_not_called()


def test_list_append_preview_preserves_order_and_duplicates(monkeypatch):
    _patch_schema(monkeypatch)
    manager = CollectionGraphManager(property_name="aliases", values=["a"])
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"aliases": ["b", "b"]},
    )

    assert result["ok"] is True
    assert result["data"]["after"]["properties"]["aliases"] == ["a", "b", "b"]


def test_set_append_preview_is_stably_deduplicated(monkeypatch):
    _patch_schema(monkeypatch)
    manager = CollectionGraphManager(property_name="tags", values=["a"])
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"tags": ["b", "a"]},
    )

    assert result["ok"] is True
    assert result["data"]["after"]["properties"]["tags"] == ["a", "b"]


def test_single_append_preview_keeps_replacement_semantics(monkeypatch):
    _patch_schema(monkeypatch)
    manager = FakeGraphManager(
        vertex={
            "id": "1:alice",
            "label": "person",
            "type": "vertex",
            "properties": {"name": "old"},
        }
    )
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"name": "new"},
    )

    assert result["ok"] is True
    assert result["data"]["after"]["properties"]["name"] == "new"


def test_collection_append_rejects_non_json_array_before_write(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = CollectionGraphManager(property_name="tags", values=["a"])
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"tags": "b"},
        dry_run=False,
        confirm=True,
        plan_hash="unused",
        nonce="unused",
        expires_at=9999999999,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["details"]["property"] == "tags"
    assert manager.append_calls == []

    tuple_result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"tags": ("b",)},
    )
    assert tuple_result["ok"] is False
    assert tuple_result["error"]["type"] == "VALIDATION_ERROR"
    assert "JSON array" in tuple_result["error"]["suggestion"]


def test_set_append_post_read_ignores_server_order(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = ReorderedSetGraphManager(property_name="tags", values=["a"])
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"tags": ["b", "a"]},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"tags": ["b", "a"]},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is True
    assert manager.append_calls == [("1:alice", {"tags": ["b", "a"]})]


def test_edge_set_append_post_read_ignores_server_order(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = CollectionGraphManager(target="edge", property_name="tags", values=["a"])
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="edge",
        operation="append",
        id="edge-1",
        properties={"tags": ["b", "a"]},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="edge",
        operation="append",
        id="edge-1",
        properties={"tags": ["b", "a"]},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is True
    assert manager.append_calls == [("edge-1", {"tags": ["b", "a"]})]


def test_eliminate_collection_still_removes_entire_property(monkeypatch):
    _patch_schema(monkeypatch)
    manager = CollectionGraphManager(property_name="aliases", values=["a", "b"])
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="eliminate",
        id="1:alice",
        properties={"aliases": ["a"]},
    )

    assert result["ok"] is True
    assert "aliases" not in result["data"]["after"]["properties"]


def test_mutate_rejects_unknown_property(monkeypatch):
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"missing": "x"},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert result["error"]["details"]["unknown_properties"] == ["missing"]


def test_mutate_confirm_rejects_cardinality_change_since_dry_run(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    live_schema = _schema()
    monkeypatch.setattr(mutate_module, "current_live_schema", lambda: live_schema)
    manager = CollectionGraphManager(property_name="aliases", values=["a"])
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"aliases": ["b"]},
    )
    context = dry_run["data"]["plan_context"]
    live_schema["schema"]["propertykeys"][2]["cardinality"] = "SET"

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"aliases": ["b"]},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_HASH_MISMATCH"
    assert manager.append_calls == []


def test_mutate_missing_vertex_returns_not_found(monkeypatch):
    _patch_schema(monkeypatch)
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: MissingTargetManager())

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:missing",
        properties={"age": 30},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "NOT_FOUND"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["reason"] == "not_found"


def test_mutate_missing_edge_returns_not_found(monkeypatch):
    _patch_schema(monkeypatch)
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: MissingTargetManager())

    result = mutate_module.mutate_graph_properties(
        target="edge",
        operation="append",
        id="S1:alice>11>knows>S2:bob",
        properties={"age": 1},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "NOT_FOUND"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["reason"] == "not_found"


def test_mutate_confirm_applies_after_valid_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "applied"
    assert manager.append_calls == [("1:alice", {"age": 30})]


def test_mutate_replayed_confirmation_does_not_execute_twice(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)
    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        nonce="mutation-replay",
    )
    context = dry_run["data"]["plan_context"]
    arguments = {
        "target": "vertex",
        "operation": "append",
        "id": "1:alice",
        "properties": {"age": 30},
        "dry_run": False,
        "confirm": True,
        "plan_hash": dry_run["data"]["plan_hash"],
        "nonce": context["nonce"],
        "expires_at": context["expires_at"],
    }

    first = mutate_module.mutate_graph_properties(**arguments)
    second = mutate_module.mutate_graph_properties(**arguments)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error"]["type"] == "PLAN_ALREADY_USED"
    assert manager.vertex["properties"]["age"] == 30
    assert manager.append_calls == [("1:alice", {"age": 30})]


def test_mutate_confirm_maps_execution_errors_with_hugegraph_classifier(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = ExecutionFailureManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    arguments = {
        "target": "vertex",
        "operation": "append",
        "id": "1:alice",
        "properties": {"age": 30},
        "dry_run": False,
        "confirm": True,
        "plan_hash": dry_run["data"]["plan_hash"],
        "nonce": context["nonce"],
        "expires_at": context["expires_at"],
    }
    result = mutate_module.mutate_graph_properties(**arguments)

    assert result["ok"] is False
    assert result["error"]["type"] == "NOT_FOUND"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["stage"] == "mutation_execute"
    assert result["error"]["details"]["reason"] == "not_found"

    replay = mutate_module.mutate_graph_properties(**arguments)
    assert replay["ok"] is False
    assert replay["error"]["type"] == "PLAN_ALREADY_USED"
    assert manager.append_calls == [("1:alice", {"age": 30})]


def test_mutate_confirm_sanitizes_post_read_error(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = PostReadFailureManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PARTIAL_APPLY"
    assert result["error"]["details"]["stage"] == "post_write_verification"
    assert result["error"]["details"]["status"] == "unknown"
    response_text = str(result)
    assert "abc123" not in response_text
    assert "token=xyz" not in response_text
    assert "user:pass" not in response_text
    assert result["warnings"] == [
        "Mutation returned from HugeGraph, but post-read verification failed."
    ]
    assert result["next_actions"] == [
        "Call query_graph_data_tool to verify the target state."
    ]


def test_mutate_confirm_returns_error_when_post_read_is_missing(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = PostReadMissingManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PARTIAL_APPLY"
    assert result["error"]["details"]["stage"] == "post_write_verification"
    assert result["error"]["details"]["post_read"] is None
    assert result["warnings"] == [
        "Mutation returned from HugeGraph, but the target was not found on post-read."
    ]
    assert result["next_actions"] == [
        "Call query_graph_data_tool to verify whether the target still exists."
    ]


def test_mutate_confirm_returns_error_when_post_read_mismatches_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = PostReadMismatchManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PARTIAL_APPLY"
    assert result["error"]["details"]["stage"] == "post_write_verification"
    assert result["error"]["details"]["planned_after"]["properties"]["age"] == 30
    assert result["error"]["details"]["post_read"]["properties"]["age"] == 31
    assert result["warnings"] == ["Post-read state did not match the planned preview."]


def test_mutate_confirm_detects_target_changed(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = FakeGraphManager(
        changed_vertex={
            "id": "1:alice",
            "label": "person",
            "type": "vertex",
            "properties": {"name": "Alice", "age": 99},
        }
    )
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "TARGET_CHANGED"
    assert manager.append_calls == []

    from hugegraph_mcp.confirmation_store import ConfirmationStore

    assert ConfirmationStore.from_config().has_consumed(context["nonce"]) is False
    manager.changed_vertex = None
    retry_after_restore = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )
    assert retry_after_restore["ok"] is True
    assert manager.append_calls == [("1:alice", {"age": 30})]


def test_mutate_confirm_requires_non_readonly(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash="bad",
        nonce="nonce",
        expires_at=9999999999,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"
    assert manager.append_calls == []
