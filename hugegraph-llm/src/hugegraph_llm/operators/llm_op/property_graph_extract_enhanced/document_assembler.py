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

"""Document-level assembler for the enhanced graph extraction strategy.

Takes the list of ``NormalizedChunkGraph`` outputs from every chunk and
produces the final ``DocumentGraph`` plus the warnings that only arise once
we can see the whole document at once:

* cross-chunk vertex merge by ``(label, id)``, with first-wins property
  conflict handling and ``PROPERTY_CONFLICT`` warnings on disagreement;
* endpoint repair for edges the normalizer left pending — the assembler
  unions every chunk's alias table into a document-level alias index and
  services the ``explicit_id_alias`` repair tier;
* ambiguity detection: an LLM raw id used across chunks for different
  canonical vertices yields ``ENDPOINT_AMBIGUOUS`` on the edges that
  depended on it;
* edge deduplication by ``(label, outVLabel, outV, inVLabel, inV,
  properties_signature)``, preserving first-appearance order.

The assembler performs no schema I/O and does not modify any chunk graph in
place. Chunks flow through in their given order so the emitted graph is
deterministic given the same LLM outputs.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.schema_index import (
    GraphSchemaIndex,
)
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.types import (
    PENDING_IN_KEY,
    PENDING_OUT_KEY,
    DocumentGraph,
    NormalizedChunkGraph,
)
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.warnings import (
    StructuredWarning,
    WarningCode,
)


class DocumentGraphAssembler:
    """Assemble chunk-level normalized graphs into a document-level graph."""

    def __init__(self, schema_index: GraphSchemaIndex) -> None:
        self._schema = schema_index

    # ---------------------------------------------------------------- public
    def assemble(
        self,
        chunk_graphs: Sequence[NormalizedChunkGraph],
    ) -> Tuple[DocumentGraph, List[StructuredWarning]]:
        warnings: List[StructuredWarning] = []

        doc_aliases, ambiguous_keys = self._union_aliases(chunk_graphs)

        merged_vertices, vertex_warnings, pre_v = self._merge_vertices(chunk_graphs)
        warnings.extend(vertex_warnings)

        repaired_edges, edge_warnings, pre_e, repair_count = self._repair_endpoints(
            chunk_graphs, doc_aliases, ambiguous_keys
        )
        warnings.extend(edge_warnings)

        deduped_edges, dedup_warnings = self._dedupe_edges(repaired_edges)
        warnings.extend(dedup_warnings)

        return (
            DocumentGraph(
                vertices=merged_vertices,
                edges=deduped_edges,
                pre_merge_vertex_count=pre_v,
                pre_merge_edge_count=pre_e,
                endpoint_repair_count=repair_count,
            ),
            warnings,
        )

    # ---------------------------------------------------------------- alias
    @staticmethod
    def _union_aliases(
        chunk_graphs: Sequence[NormalizedChunkGraph],
    ) -> Tuple[Dict[Tuple[str, str], str], Set[Tuple[str, str]]]:
        """Union every chunk's alias table into a document-level index.

        When the same ``(label, key)`` maps to different canonical ids across
        chunks, the key is marked ambiguous — resolving through it yields
        ``ENDPOINT_AMBIGUOUS`` for the affected edges instead of silently
        picking one of the candidates.
        """
        doc_aliases: Dict[Tuple[str, str], str] = {}
        ambiguous: Set[Tuple[str, str]] = set()
        for cg in chunk_graphs:
            for key, value in cg.aliases.items():
                if key in doc_aliases and doc_aliases[key] != value:
                    ambiguous.add(key)
                    # Keep the first mapping in the table; ambiguity is
                    # tracked separately so callers can distinguish it from
                    # "not found at all".
                    continue
                doc_aliases[key] = value
        return doc_aliases, ambiguous

    # -------------------------------------------------------------- vertices
    @staticmethod
    def _merge_vertices(
        chunk_graphs: Sequence[NormalizedChunkGraph],
    ) -> Tuple[List[Dict[str, Any]], List[StructuredWarning], int]:
        """Merge vertices by ``(label, id)``. Returns (merged, warnings, pre_count).

        Rules per design section 6.5:

        * First-appearance wins for merge target and property values.
        * Non-conflicting properties from later occurrences are added.
        * Property conflicts emit ``PROPERTY_CONFLICT`` (soft — first value kept).
        * Every merge event emits ``DUPLICATE_VERTEX_MERGED`` so the
          quality gate can count exactly how many duplicates were folded in.
        * Vertices without an ``id`` are kept as-is (they have no way to
          merge with any other) and each occupies a distinct output slot.
        """
        merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
        order: List[Tuple[str, str]] = []
        no_id_vertices: List[Dict[str, Any]] = []
        warnings: List[StructuredWarning] = []
        pre_count = 0

        for cg in chunk_graphs:
            for vertex in cg.vertices:
                pre_count += 1
                vid = vertex.get("id")
                label = vertex.get("label")
                if vid is None or label is None:
                    # No key to merge on — keep the vertex verbatim.
                    no_id_vertices.append(dict(vertex))
                    continue
                key = (str(label), str(vid))
                if key not in merged:
                    merged[key] = _copy_vertex(vertex)
                    order.append(key)
                    continue
                # Fold this occurrence into the existing merged vertex.
                existing_props = merged[key].setdefault("properties", {})
                new_props = vertex.get("properties") or {}
                for pk, pv in new_props.items():
                    if pk not in existing_props:
                        existing_props[pk] = pv
                    elif existing_props[pk] != pv:
                        warnings.append(
                            StructuredWarning(
                                code=WarningCode.PROPERTY_CONFLICT,
                                item_type="vertex",
                                reason=(
                                    f"property {pk!r} on {label} vertex conflicts across chunks; "
                                    f"kept {existing_props[pk]!r}, discarded {pv!r}"
                                ),
                                label=str(label),
                                context={
                                    "property": pk,
                                    "kept": existing_props[pk],
                                    "discarded": pv,
                                },
                            )
                        )
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.DUPLICATE_VERTEX_MERGED,
                        item_type="vertex",
                        reason=f"duplicate vertex merged by (label, id) = ({label}, {vid})",
                        label=str(label),
                    )
                )

        ordered = [merged[k] for k in order]
        ordered.extend(no_id_vertices)
        return ordered, warnings, pre_count

    # ----------------------------------------------------------------- edges
    def _repair_endpoints(
        self,
        chunk_graphs: Sequence[NormalizedChunkGraph],
        doc_aliases: Mapping[Tuple[str, str], str],
        ambiguous: Set[Tuple[str, str]],
    ) -> Tuple[List[Dict[str, Any]], List[StructuredWarning], int, int]:
        """Attempt document-level endpoint repair for edges left pending.

        Returns ``(edges, warnings, pre_count, repair_count)``:

        * ``edges`` — edges with both endpoints resolved, ready for dedup.
        * ``pre_count`` — total edges seen across all chunks (pre-dedup).
        * ``repair_count`` — number of pending endpoints the assembler resolved.
        """
        warnings: List[StructuredWarning] = []
        edges: List[Dict[str, Any]] = []
        pre_count = 0
        repair_count = 0

        for cg in chunk_graphs:
            for edge in cg.edges:
                pre_count += 1
                cleaned = {k: v for k, v in edge.items() if k not in (PENDING_OUT_KEY, PENDING_IN_KEY)}

                out_hint = edge.get(PENDING_OUT_KEY)
                in_hint = edge.get(PENDING_IN_KEY)
                edge_label = edge.get("label")

                out_result = self._resolve_pending(out_hint, edge.get("outVLabel"), doc_aliases, ambiguous)
                in_result = self._resolve_pending(in_hint, edge.get("inVLabel"), doc_aliases, ambiguous)

                # Populate resolved endpoint ids where we succeeded.
                if out_hint is not None and out_result[0] is not None:
                    cleaned["outV"] = out_result[0]
                    repair_count += 1
                if in_hint is not None and in_result[0] is not None:
                    cleaned["inV"] = in_result[0]
                    repair_count += 1

                # Categorize a definitive failure so the reader can distinguish
                # "no candidate" from "multiple candidates".
                out_status = out_result[1] if out_hint is not None else "resolved"
                in_status = in_result[1] if in_hint is not None else "resolved"
                if "outV" not in cleaned:
                    out_status = "unresolved" if out_status == "resolved" else out_status
                if "inV" not in cleaned:
                    in_status = "unresolved" if in_status == "resolved" else in_status

                if "outV" in cleaned and "inV" in cleaned:
                    edges.append(cleaned)
                    continue

                # Drop with a categorized warning. Ambiguous beats unresolved
                # when both endpoints failed — it points to a real data issue.
                if out_status == "ambiguous" or in_status == "ambiguous":
                    warnings.append(
                        StructuredWarning(
                            code=WarningCode.ENDPOINT_AMBIGUOUS,
                            item_type="edge",
                            reason=(
                                f"edge {edge_label!r} endpoint alias resolves to multiple canonical ids "
                                f"across chunks; edge dropped"
                            ),
                            label=str(edge_label) if edge_label else None,
                        )
                    )
                else:
                    warnings.append(
                        StructuredWarning(
                            code=WarningCode.ENDPOINT_UNRESOLVED,
                            item_type="edge",
                            reason=(
                                f"edge {edge_label!r} has unresolved endpoint(s) after document-level "
                                f"repair; edge dropped"
                            ),
                            label=str(edge_label) if edge_label else None,
                        )
                    )

        return edges, warnings, pre_count, repair_count

    def _resolve_pending(
        self,
        hint: Optional[Mapping[str, Any]],
        endpoint_label: Optional[str],
        doc_aliases: Mapping[Tuple[str, str], str],
        ambiguous: Set[Tuple[str, str]],
    ) -> Tuple[Optional[str], str]:
        """Resolve a single pending-endpoint hint against the doc-level index.

        Returns ``(canonical_id_or_None, status)`` where status is
        ``"resolved"``, ``"unresolved"``, or ``"ambiguous"``.
        """
        if hint is None or endpoint_label is None:
            return None, "unresolved"

        if "original_id" in hint:
            key = (endpoint_label, str(hint["original_id"]))
            if key in ambiguous:
                return None, "ambiguous"
            resolved = doc_aliases.get(key)
            return (resolved, "resolved") if resolved is not None else (None, "unresolved")

        if "legacy" in hint:
            legacy = hint["legacy"]
            # Re-attempt schema-based canonical id computation at doc level.
            # Rarely more productive than the normalizer's earlier attempt,
            # but harmless when the schema now has more property keys or
            # the caller has supplied a richer schema.
            if isinstance(legacy, Mapping):
                canonical = self._schema.canonical_vertex_id(legacy.get("label"), legacy.get("properties") or {})
                if canonical is not None:
                    return canonical, "resolved"
            return None, "unresolved"

        return None, "unresolved"

    # ------------------------------------------------------------- dedupe
    @staticmethod
    def _dedupe_edges(
        edges: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[StructuredWarning]]:
        """Deduplicate edges by ``(label, endpoints, properties_signature)``.

        Edges with the same endpoints but different property signatures are
        preserved — the reader should not lose facts even when duplicates
        share endpoints. First-appearance order is retained.
        """
        seen: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        order: List[Tuple[Any, ...]] = []
        warnings: List[StructuredWarning] = []
        for edge in edges:
            props = edge.get("properties") or {}
            # json.dumps with sort_keys gives a stable string signature that
            # handles nested lists/dicts (e.g. LIST cardinality property values)
            # which a plain tuple() would refuse to hash.
            try:
                prop_sig = json.dumps(props, sort_keys=True, ensure_ascii=False, default=str)
            except TypeError:
                prop_sig = repr(sorted(props.items()))
            key = (
                edge.get("label"),
                edge.get("outVLabel"),
                edge.get("outV"),
                edge.get("inVLabel"),
                edge.get("inV"),
                prop_sig,
            )
            if key not in seen:
                seen[key] = edge
                order.append(key)
                continue
            warnings.append(
                StructuredWarning(
                    code=WarningCode.DUPLICATE_EDGE_MERGED,
                    item_type="edge",
                    reason=(
                        f"duplicate edge merged by (label, endpoints, properties_signature) — "
                        f"label={edge.get('label')!r}"
                    ),
                    label=edge.get("label"),
                )
            )
        return [seen[k] for k in order], warnings


def _copy_vertex(vertex: Mapping[str, Any]) -> Dict[str, Any]:
    """Shallow-copy a vertex, deep-copying the properties dict so first-wins
    conflict handling can mutate it safely."""
    out = dict(vertex)
    if "properties" in out and isinstance(out["properties"], Mapping):
        out["properties"] = dict(out["properties"])
    return out
