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

"""Gremlin query generation for graph data change operations.

Uses conservative literal escaping for injection prevention.
"""

import json
from typing import Any

# ---- Gremlin query generation — single-quoted strings prevent Groovy GString interpolation. ----


def _g(value: Any) -> str:
    if isinstance(value, str):
        escaped = _escape_groovy_single_quoted(value)
        return f"'{escaped}'"
    if isinstance(value, dict):
        # Groovy/Gremlin map literal uses [...] not {...}
        items = ", ".join(f"{_g(k)}: {_g(v)}" for k, v in sorted(value.items()))
        return f"[{items}]"
    if isinstance(value, (list, tuple)):
        items = ", ".join(_g(v) for v in value)
        return f"[{items}]"
    return json.dumps(value)


def _escape_groovy_single_quoted(value: str) -> str:
    chars: list[str] = []
    for char in value:
        if char == "\\":
            chars.append("\\\\")
        elif char == "'":
            chars.append("\\'")
        elif char == "\n":
            chars.append("\\n")
        elif char == "\r":
            chars.append("\\r")
        elif char == "\t":
            chars.append("\\t")
        elif char == "\b":
            chars.append("\\b")
        elif char == "\f":
            chars.append("\\f")
        elif ord(char) < 0x20:
            chars.append(f"\\u{ord(char):04x}")
        else:
            chars.append(char)
    return "".join(chars)


def _has_steps(match: dict[str, Any]) -> str:
    steps: list[str] = []
    for key, value in match.items():
        if key == "id":
            steps.append(f".hasId({_g(value)})")
        else:
            steps.append(f".has({_g(key)},{_g(value)})")
    return "".join(steps)


def _vertex_match_query(operation: dict[str, Any]) -> str:
    return f"g.V().hasLabel({_g(operation['label'])}){_has_steps(operation['match'])}"


def _edge_match_query(operation: dict[str, Any]) -> str:
    source_label = operation.get("source_label") or operation.get("outVLabel")
    target_label = operation.get("target_label") or operation.get("inVLabel")
    return (
        f"g.V().hasLabel({_g(source_label)}){_has_steps(operation['source_match'])}"
        f".outE({_g(operation['label'])})"
        f".where(inV().hasLabel({_g(target_label)}){_has_steps(operation['target_match'])})"
    )


def _source_vertex_match_query(operation: dict[str, Any]) -> str:
    source_label = operation.get("source_label") or operation.get("outVLabel")
    return f"g.V().hasLabel({_g(source_label)}){_has_steps(operation['source_match'])}"


def _target_vertex_match_query(operation: dict[str, Any]) -> str:
    target_label = operation.get("target_label") or operation.get("inVLabel")
    return f"g.V().hasLabel({_g(target_label)}){_has_steps(operation['target_match'])}"


# ---- Gremlin write-statement generation — labels and values are schema-constrained and JSON-escaped. ----


def _create_vertex_query(operation: dict[str, Any]) -> str:
    query = f"g.addV({_g(operation['label'])})"
    if operation.get("id") not in (None, ""):
        query += f".property(T.id,{_g(operation['id'])})"
    for prop, value in (operation.get("properties") or {}).items():
        query += f".property({_g(prop)},{_g(value)})"
    return query


def _create_edge_query(operation: dict[str, Any]) -> str:
    query = (
        f"g.V({_g(operation['source_id'])}).as('s')"
        f".V({_g(operation['target_id'])})"
        f".addE({_g(operation['label'])}).from('s')"
    )
    for prop, value in (operation.get("properties") or {}).items():
        query += f".property({_g(prop)},{_g(value)})"
    return query


def _delete_vertex_query(operation: dict[str, Any]) -> str:
    query = _delete_target_query(operation)
    if operation.get("cascade", False) is False:
        # The no-incident-edge precondition and drop execute in one Gremlin
        # request instead of a client-side check-then-act sequence.
        query += ".not(bothE())"
    return f"{query}.drop()"


def _delete_edge_query(operation: dict[str, Any]) -> str:
    return f"{_delete_target_query(operation)}.drop()"


def _delete_target_query(operation: dict[str, Any]) -> str:
    op = str(operation.get("op") or operation.get("type"))
    target_id = operation["target_id"]
    if op == "delete_vertex":
        return f"g.V({_g(target_id)})"
    if op == "delete_edge":
        return f"g.E({_g(target_id)})"
    raise ValueError(f"Unsupported delete op: {op}")


def _write_query(operation: dict[str, Any]) -> str:
    op = str(operation.get("op") or operation.get("type"))
    if op == "create_vertex":
        return _create_vertex_query(operation)
    if op == "create_edge":
        return _create_edge_query(operation)
    if op == "delete_vertex":
        return _delete_vertex_query(operation)
    if op == "delete_edge":
        return _delete_edge_query(operation)
    raise ValueError(f"Unsupported op: {op}")
