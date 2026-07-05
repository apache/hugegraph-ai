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

"""Candidate graph parser for the enhanced graph extraction strategy.

Reads a single chunk's raw LLM output (a string) and produces a
``CandidateGraph`` plus a list of ``StructuredWarning``s describing every
recoverable or unrecoverable defect encountered along the way. Downstream
stages (normalizer, assembler) rely on the parser to have already:

* stripped Markdown code fences,
* located and parsed a JSON payload,
* separated grouped ``{"vertices": [...], "edges": [...]}`` and flat-array
  ``[{"type": "vertex", ...}, ...]`` shapes into two arrays,
* dropped items that are not dicts or that carry an explicit ``type`` in
  conflict with their containing array.

The parser does NOT perform any schema validation. That is the normalizer's
responsibility. This keeps parser failure modes JSON-shaped rather than
schema-shaped and makes the warning surface easier to reason about.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.types import CandidateGraph
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.warnings import (
    StructuredWarning,
    WarningCode,
)

_FENCE_TAG_RE = re.compile(r"```[^\n]*\n?", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"```")
# Greedy match from the first '{' to the last '}' (or first '[' to last ']').
# The greedy .* in DOTALL mode lets us pick up JSON that spans newlines and is
# wrapped in prose. If the extracted substring is not valid JSON the caller
# emits JSON_DECODE_FAILED instead of hallucinating a smaller match.
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class CandidateGraphParser:
    """Turn raw LLM output into a ``CandidateGraph`` with structured warnings.

    The parser is stateless — a single instance can be reused across chunks
    and threads. Pass ``chunk_id`` on each call so emitted warnings can be
    correlated back to the chunk they came from.
    """

    def parse(
        self,
        raw_text: str,
        *,
        chunk_id: Optional[int] = None,
    ) -> Tuple[CandidateGraph, List[StructuredWarning]]:
        """Parse a single chunk's raw LLM output.

        Returns:
            A ``(CandidateGraph, warnings)`` tuple. On complete parse failure,
            the returned graph has empty vertices and edges lists.
        """
        warnings: List[StructuredWarning] = []
        text = self._strip_fences(raw_text or "")

        payload, decode_warning = self._locate_and_parse_json(text, chunk_id=chunk_id)
        if decode_warning is not None:
            warnings.append(decode_warning)
        if payload is None:
            return CandidateGraph(), warnings

        vertices_section, edges_section, section_warnings = self._extract_sections(payload, chunk_id=chunk_id)
        warnings.extend(section_warnings)

        vertices, v_warnings = self._collect_items(vertices_section, expected_type="vertex", chunk_id=chunk_id)
        edges, e_warnings = self._collect_items(edges_section, expected_type="edge", chunk_id=chunk_id)
        warnings.extend(v_warnings)
        warnings.extend(e_warnings)

        return CandidateGraph(vertices=vertices, edges=edges), warnings

    # ---------------------------------------------------------------- steps
    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove Markdown code fences (```, ```json, ```JSON) from the text."""
        stripped = _FENCE_TAG_RE.sub("", text)
        stripped = _FENCE_CLOSE_RE.sub("", stripped)
        return stripped.strip()

    @staticmethod
    def _locate_and_parse_json(
        text: str, *, chunk_id: Optional[int]
    ) -> Tuple[Optional[Any], Optional[StructuredWarning]]:
        """Best-effort JSON extraction.

        Order of attempts:

        1. ``json.loads`` of the entire (stripped) text — succeeds when the
           LLM emits well-formed JSON with no surrounding prose.
        2. Greedy ``{...}`` extraction — for grouped format wrapped in prose.
        3. Greedy ``[...]`` extraction — for flat-array format wrapped in prose.

        Returns ``(payload, None)`` on success, ``(None, warning)`` on failure.
        A failure is classified as ``JSON_DECODE_FAILED`` whenever the text
        contains an opening brace or bracket (evidence that JSON was attempted
        but is malformed), and ``JSON_NOT_FOUND`` otherwise.
        """
        if not text:
            return None, StructuredWarning(
                code=WarningCode.JSON_NOT_FOUND,
                item_type="graph",
                reason="LLM output is empty after stripping code fences",
                chunk_id=chunk_id,
            )

        try:
            return json.loads(text), None
        except json.JSONDecodeError as full_exc:
            full_error = str(full_exc)

        obj_match = _JSON_OBJECT_RE.search(text)
        arr_match = _JSON_ARRAY_RE.search(text)

        candidates: List[str] = []
        if obj_match:
            candidates.append(obj_match.group(0))
        if arr_match:
            candidates.append(arr_match.group(0))

        last_error: Optional[str] = full_error
        for candidate in candidates:
            try:
                return json.loads(candidate), None
            except json.JSONDecodeError as exc:
                last_error = str(exc)

        # Discriminate: text with an opening brace/bracket is a broken JSON
        # attempt; text without either bracket really has no JSON at all.
        contains_json_start = ("{" in text) or ("[" in text)
        if contains_json_start:
            return None, StructuredWarning(
                code=WarningCode.JSON_DECODE_FAILED,
                item_type="graph",
                reason=f"located a JSON-like substring but failed to decode: {last_error}",
                chunk_id=chunk_id,
            )
        return None, StructuredWarning(
            code=WarningCode.JSON_NOT_FOUND,
            item_type="graph",
            reason="no JSON object or array found in the LLM output",
            chunk_id=chunk_id,
        )

    @staticmethod
    def _extract_sections(
        payload: Any, *, chunk_id: Optional[int]
    ) -> Tuple[List[Any], List[Any], List[StructuredWarning]]:
        """Route a parsed JSON payload into (vertices_section, edges_section).

        Handles three top-level shapes:

        * ``list`` — flat array; items are partitioned by their ``type`` field.
          Items without ``type`` are dropped later by ``_collect_items`` via
          ``ITEM_TYPE_MISMATCH``.
        * ``dict`` with ``vertices``/``edges`` keys — grouped format.
        * Anything else — treated as empty; both sections yield warnings.
        """
        warnings: List[StructuredWarning] = []

        if isinstance(payload, list):
            vertices: List[Any] = []
            edges: List[Any] = []
            for item in payload:
                if isinstance(item, dict):
                    t = item.get("type")
                    if t == "vertex":
                        vertices.append(item)
                    elif t == "edge":
                        edges.append(item)
                    else:
                        # Route once (to vertices) with a marker; the collector
                        # surfaces ITEM_TYPE_MISMATCH for the missing type.
                        vertices.append({"__unroutable__": True, **item})
                else:
                    # Non-dict items are routed to vertices as a single site
                    # where the collector will log ITEM_NOT_OBJECT.
                    vertices.append(item)
            return vertices, edges, warnings

        if isinstance(payload, dict):
            vertices_section = payload.get("vertices")
            edges_section = payload.get("edges")
            if "vertices" not in payload:
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.GRAPH_SECTION_MISSING,
                        item_type="graph",
                        reason="'vertices' section missing from parsed payload",
                        chunk_id=chunk_id,
                    )
                )
                vertices_section = []
            if "edges" not in payload:
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.GRAPH_SECTION_MISSING,
                        item_type="graph",
                        reason="'edges' section missing from parsed payload",
                        chunk_id=chunk_id,
                    )
                )
                edges_section = []
            # Normalize non-list section values so the collector still runs.
            if not isinstance(vertices_section, list):
                vertices_section = []
            if not isinstance(edges_section, list):
                edges_section = []
            return vertices_section, edges_section, warnings

        # Payload is a scalar (str/number/bool/None) — surface both missing
        # sections; the collector will produce two empty lists.
        warnings.append(
            StructuredWarning(
                code=WarningCode.GRAPH_SECTION_MISSING,
                item_type="graph",
                reason=f"parsed payload is not an object or array: {type(payload).__name__}",
                chunk_id=chunk_id,
            )
        )
        return [], [], warnings

    @staticmethod
    def _collect_items(
        items: List[Any],
        *,
        expected_type: str,
        chunk_id: Optional[int],
    ) -> Tuple[List[Dict[str, Any]], List[StructuredWarning]]:
        """Validate each candidate item and drop obvious defects.

        Rules:

        * Non-dict → ``ITEM_NOT_OBJECT``.
        * Item bore the ``__unroutable__`` marker (from a flat-array item that
          had no ``type`` field) → ``ITEM_TYPE_MISMATCH``.
        * Item has an explicit ``type`` disagreeing with ``expected_type`` →
          ``ITEM_TYPE_MISMATCH``.
        * Otherwise the item is kept as-is with its ``type`` field
          normalized to ``expected_type`` (this frees the normalizer from
          repeating the same defensive check).
        """
        collected: List[Dict[str, Any]] = []
        warnings: List[StructuredWarning] = []
        for item in items:
            if not isinstance(item, dict):
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.ITEM_NOT_OBJECT,
                        item_type="graph",
                        reason=f"candidate {expected_type} is not an object: {type(item).__name__}",
                        chunk_id=chunk_id,
                    )
                )
                continue

            if item.get("__unroutable__") is True:
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.ITEM_TYPE_MISMATCH,
                        item_type="graph",
                        reason="flat-array item has no 'type' field to route it to vertex or edge",
                        chunk_id=chunk_id,
                        context={"label": item.get("label")},
                    )
                )
                continue

            declared_type = item.get("type")
            if declared_type is not None and declared_type != expected_type:
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.ITEM_TYPE_MISMATCH,
                        item_type="graph",
                        reason=(f"candidate has type={declared_type!r} but was placed in the {expected_type} section"),
                        label=item.get("label"),
                        chunk_id=chunk_id,
                    )
                )
                continue

            # Normalize the type for downstream consumers so they can always
            # rely on item["type"] being present.
            normalized = dict(item)
            normalized["type"] = expected_type
            collected.append(normalized)
        return collected, warnings
