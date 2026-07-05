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

"""Schema-aware chunk-level normalizer for the enhanced extraction strategy.

Takes a ``CandidateGraph`` (already parsed from raw LLM output) and a compiled
``GraphSchemaIndex``, then produces a ``NormalizedChunkGraph`` in which:

* every vertex has a schema-valid label and only schema-declared properties;
* property values have been safely coerced to the schema's declared types;
* every vertex whose primary keys resolve gets a canonical id
  (``{vertex_label.id}:{pk1}!{pk2}``); vertices whose canonical rule doesn't
  apply keep the LLM-provided id as a fallback (mirrors baseline);
* an alias table maps ``(label, llm_original_id) → canonical_id`` so the
  document-level assembler can resolve cross-chunk endpoint references;
* every edge has a schema-valid label, only schema-declared properties, and
  either both endpoints resolved to canonical ids (ready to emit) or explicit
  ``_pending_out`` / ``_pending_in`` hints for the assembler.

Vertex/edge processing order is: label → property filter → coerce → primary
key check → canonical id. Design section 6.4 pins this order so that a
schema-invalid property never causes a false primary-key miss.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.schema_index import (
    GraphSchemaIndex,
)
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.types import (
    PENDING_IN_KEY,
    PENDING_OUT_KEY,
    CandidateGraph,
    NormalizedChunkGraph,
)
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.warnings import (
    StructuredWarning,
    WarningCode,
)


class SchemaAwareNormalizer:
    """Normalize a chunk-level ``CandidateGraph`` against a ``GraphSchemaIndex``.

    Stateless — one instance can be shared across chunks and threads. The
    schema index passed to the constructor is not modified.
    """

    def __init__(self, schema_index: GraphSchemaIndex) -> None:
        self._schema = schema_index

    # ---------------------------------------------------------------- public
    def normalize(
        self,
        candidate: CandidateGraph,
        *,
        chunk_id: Optional[int] = None,
    ) -> Tuple[NormalizedChunkGraph, List[StructuredWarning]]:
        """Normalize a chunk's candidate graph. Returns (graph, warnings)."""
        warnings: List[StructuredWarning] = []
        aliases: Dict[Tuple[str, str], str] = {}

        vertices: List[Dict[str, Any]] = []
        for item in candidate.vertices:
            normalized, item_warnings, alias = self._normalize_vertex(item, chunk_id)
            warnings.extend(item_warnings)
            if normalized is not None:
                vertices.append(normalized)
                # Seed identity aliases so edges can resolve endpoints regardless of
                # whether the LLM referenced the vertex by its raw id or its canonical id.
                vid = normalized.get("id")
                if vid is not None:
                    aliases[(normalized["label"], str(vid))] = str(vid)
            if alias is not None:
                aliases[(alias[0], alias[1])] = alias[2]

        edges: List[Dict[str, Any]] = []
        for item in candidate.edges:
            normalized, item_warnings = self._normalize_edge(item, aliases, chunk_id)
            warnings.extend(item_warnings)
            if normalized is not None:
                edges.append(normalized)

        return (
            NormalizedChunkGraph(vertices=vertices, edges=edges, aliases=aliases),
            warnings,
        )

    # ---------------------------------------------------------------- vertex
    def _normalize_vertex(
        self, item: Mapping[str, Any], chunk_id: Optional[int]
    ) -> Tuple[Optional[Dict[str, Any]], List[StructuredWarning], Optional[Tuple[str, str, str]]]:
        """Normalize a single candidate vertex.

        Returns a triple ``(vertex_or_None, warnings, alias_or_None)``:

        * ``vertex_or_None`` is the normalized vertex dict (with keys
          ``type``, ``label``, ``properties``, and optionally ``id``), or
          ``None`` when the vertex was dropped.
        * ``alias_or_None`` is ``(label, llm_original_id, canonical_id)`` when
          the LLM-provided id differs from the canonical one; the caller adds
          it to the alias table.
        """
        warnings: List[StructuredWarning] = []
        label = item.get("label")

        if not isinstance(label, str) or not self._schema.is_vertex_label(label):
            warnings.append(
                StructuredWarning(
                    code=WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA,
                    item_type="vertex",
                    reason=f"vertex label {label!r} is not in the schema",
                    label=label if isinstance(label, str) else None,
                    chunk_id=chunk_id,
                )
            )
            return None, warnings, None

        # Property filter + coerce (order pinned by design §6.4).
        raw_properties = item.get("properties") or {}
        if not isinstance(raw_properties, Mapping):
            raw_properties = {}
        filtered, prop_warnings, primary_key_fatal = self._filter_and_coerce_properties(
            raw_properties=raw_properties,
            item_type="vertex",
            label=label,
            primary_keys=set(self._schema.primary_keys(label)),
            chunk_id=chunk_id,
        )
        warnings.extend(prop_warnings)
        if primary_key_fatal:
            return None, warnings, None

        # Primary key completeness check.
        pk_names = self._schema.primary_keys(label)
        missing_pks = [k for k in pk_names if k not in filtered or filtered[k] in (None, "")]
        if pk_names and missing_pks:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.VERTEX_PRIMARY_KEY_MISSING,
                    item_type="vertex",
                    reason=f"primary key(s) {missing_pks} missing or empty on {label} vertex",
                    label=label,
                    chunk_id=chunk_id,
                    context={"missing_primary_keys": missing_pks},
                )
            )
            return None, warnings, None

        canonical_id = self._schema.canonical_vertex_id(label, filtered)
        original_id = item.get("id") if isinstance(item.get("id"), (str, int)) else None
        if isinstance(original_id, int):
            original_id = str(original_id)

        normalized: Dict[str, Any] = {
            "type": "vertex",
            "label": label,
            "properties": filtered,
        }
        # Prefer canonical id; fall back to the LLM's original id for schemas
        # that lack vertex_label.id (baseline-compatible degrade path).
        resolved_id = canonical_id if canonical_id is not None else original_id
        if resolved_id is not None:
            normalized["id"] = resolved_id

        alias: Optional[Tuple[str, str, str]] = None
        if canonical_id is not None and original_id is not None and original_id != canonical_id:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.VERTEX_ALIAS_RECORDED,
                    item_type="vertex",
                    reason=f"LLM original id {original_id!r} mapped to canonical id {canonical_id!r}",
                    label=label,
                    chunk_id=chunk_id,
                    context={"original_id": original_id, "canonical_id": canonical_id},
                )
            )
            alias = (label, original_id, canonical_id)

        return normalized, warnings, alias

    # ---------------------------------------------------------------- edge
    def _normalize_edge(
        self,
        item: Mapping[str, Any],
        aliases: Mapping[Tuple[str, str], str],
        chunk_id: Optional[int],
    ) -> Tuple[Optional[Dict[str, Any]], List[StructuredWarning]]:
        """Normalize a single candidate edge."""
        warnings: List[StructuredWarning] = []
        label = item.get("label")

        if not isinstance(label, str) or not self._schema.is_edge_label(label):
            warnings.append(
                StructuredWarning(
                    code=WarningCode.EDGE_LABEL_NOT_IN_SCHEMA,
                    item_type="edge",
                    reason=f"edge label {label!r} is not in the schema",
                    label=label if isinstance(label, str) else None,
                    chunk_id=chunk_id,
                )
            )
            return None, warnings

        # Property filter + coerce (edges have no primary key concept).
        raw_properties = item.get("properties") or {}
        if not isinstance(raw_properties, Mapping):
            raw_properties = {}
        filtered, prop_warnings, _fatal = self._filter_and_coerce_properties(
            raw_properties=raw_properties,
            item_type="edge",
            label=label,
            primary_keys=set(),
            chunk_id=chunk_id,
        )
        warnings.extend(prop_warnings)

        # Endpoint label discovery: prefer explicit outVLabel/inVLabel, then
        # fall back to legacy source/target dicts. Missing labels we can still
        # infer from the schema's edge spec (there is exactly one legal pair).
        endpoint_spec = self._schema.edge_endpoint_spec(label)
        assert endpoint_spec is not None  # is_edge_label already verified
        schema_out_label, schema_in_label = endpoint_spec

        legacy_source = item.get("source") if isinstance(item.get("source"), Mapping) else None
        legacy_target = item.get("target") if isinstance(item.get("target"), Mapping) else None
        out_label = item.get("outVLabel") or (legacy_source.get("label") if legacy_source else None)
        in_label = item.get("inVLabel") or (legacy_target.get("label") if legacy_target else None)

        # If labels are absent, fall back to the schema-required labels rather
        # than dropping — the LLM may have skipped these fields when they are
        # redundant with the edge label.
        if out_label is None:
            out_label = schema_out_label
        if in_label is None:
            in_label = schema_in_label

        if not self._schema.is_endpoint_compatible(label, out_label, in_label):
            warnings.append(
                StructuredWarning(
                    code=WarningCode.EDGE_ENDPOINT_MISMATCH,
                    item_type="edge",
                    reason=(
                        f"edge {label!r} endpoints ({out_label!r} → {in_label!r}) do not match "
                        f"the schema spec ({schema_out_label!r} → {schema_in_label!r})"
                    ),
                    label=label,
                    chunk_id=chunk_id,
                    context={"out_label": out_label, "in_label": in_label},
                )
            )
            return None, warnings

        # Endpoint id resolution: try legacy source/target dicts first (they
        # carry the primary key values needed for a schema-only canonical id),
        # then the chunk's own alias table (LLM raw id → canonical id), then
        # leave a pending marker for the document-level assembler.
        out_v, out_pending = self._resolve_endpoint(
            explicit_id=item.get("outV"),
            legacy=legacy_source,
            endpoint_label=out_label,
            aliases=aliases,
        )
        in_v, in_pending = self._resolve_endpoint(
            explicit_id=item.get("inV"),
            legacy=legacy_target,
            endpoint_label=in_label,
            aliases=aliases,
        )

        normalized: Dict[str, Any] = {
            "type": "edge",
            "label": label,
            "outVLabel": out_label,
            "inVLabel": in_label,
            "properties": filtered,
        }
        if out_v is not None:
            normalized["outV"] = out_v
        if in_v is not None:
            normalized["inV"] = in_v

        if out_pending is not None:
            normalized[PENDING_OUT_KEY] = out_pending
        if in_pending is not None:
            normalized[PENDING_IN_KEY] = in_pending

        if out_v is None or in_v is None:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.ENDPOINT_PENDING_REPAIR,
                    item_type="edge",
                    reason=(
                        f"edge {label!r} has {'out' if out_v is None else 'in'}-endpoint pending document-level repair"
                    ),
                    label=label,
                    chunk_id=chunk_id,
                )
            )

        return normalized, warnings

    def _resolve_endpoint(
        self,
        *,
        explicit_id: Any,
        legacy: Optional[Mapping[str, Any]],
        endpoint_label: str,
        aliases: Mapping[Tuple[str, str], str],
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Try three sources for a resolved canonical id, in order.

        Returns ``(canonical_id_or_None, pending_hint_or_None)``. When both
        components are None, no endpoint info was provided at all — the caller
        emits ENDPOINT_PENDING_REPAIR anyway (an endpoint that we can neither
        resolve nor hint at will be dropped by the assembler as UNRESOLVED).
        """
        # Tier 1 & 2 combined: legacy source/target dict has enough for the
        # schema-only canonical id, which is stateless w.r.t. the chunk.
        if isinstance(legacy, Mapping):
            legacy_label = legacy.get("label")
            legacy_props = legacy.get("properties")
            if isinstance(legacy_label, str) and isinstance(legacy_props, Mapping):
                canonical = self._schema.canonical_vertex_id(legacy_label, legacy_props)
                if canonical is not None:
                    return canonical, None
                # No canonical possible — keep the legacy dict as a hint so
                # the assembler can decide.
                return None, {"legacy": {"label": legacy_label, "properties": dict(legacy_props)}}

        # Tier 3: explicit outV / inV as an LLM raw id, resolved via aliases.
        if isinstance(explicit_id, (str, int)):
            key = str(explicit_id)
            resolved = aliases.get((endpoint_label, key))
            if resolved is not None:
                return resolved, None
            return None, {"original_id": key}

        # Nothing to work with.
        return None, None

    # ------------------------------------------------------------- helpers
    def _filter_and_coerce_properties(
        self,
        *,
        raw_properties: Mapping[str, Any],
        item_type: str,
        label: str,
        primary_keys: set,
        chunk_id: Optional[int],
    ) -> Tuple[Dict[str, Any], List[StructuredWarning], bool]:
        """Filter properties against the schema and coerce their values.

        Returns ``(filtered, warnings, primary_key_fatal)``. The fatal flag is
        set when a primary-key property failed coercion — vertex callers use
        it to drop the whole vertex; edges ignore it (edges have no PKs).
        """
        allowed = self._schema.allowed_properties(item_type, label)
        warnings: List[StructuredWarning] = []
        filtered: Dict[str, Any] = {}
        pk_fatal = False

        for key, value in raw_properties.items():
            if key not in allowed:
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.PROPERTY_NOT_IN_SCHEMA,
                        item_type=item_type,
                        reason=f"property {key!r} is not allowed on {label} {item_type}",
                        label=label,
                        chunk_id=chunk_id,
                        context={"property": key},
                    )
                )
                continue
            coerced, reason = self._schema.coerce_property_value(key, value)
            if reason is not None:
                if key in primary_keys:
                    warnings.append(
                        StructuredWarning(
                            code=WarningCode.VERTEX_PRIMARY_KEY_INVALID,
                            item_type=item_type,
                            reason=reason,
                            label=label,
                            chunk_id=chunk_id,
                            context={"property": key},
                        )
                    )
                    pk_fatal = True
                    # Return early so the caller drops the whole vertex.
                    return {}, warnings, True
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.PROPERTY_COERCION_FAILED,
                        item_type=item_type,
                        reason=reason,
                        label=label,
                        chunk_id=chunk_id,
                        context={"property": key},
                    )
                )
                continue
            # Successful coerce — emit soft PROPERTY_COERCED only when the
            # value type actually changed. Same-type coerce (e.g. "Tom" → "Tom"
            # for TEXT) is silent to avoid drowning downstream consumers.
            if type(coerced) is not type(value):
                warnings.append(
                    StructuredWarning(
                        code=WarningCode.PROPERTY_COERCED,
                        item_type=item_type,
                        reason=(
                            f"property {key!r} coerced from {type(value).__name__} to "
                            f"{self._schema.property_data_type(key)}"
                        ),
                        label=label,
                        chunk_id=chunk_id,
                        context={"property": key},
                    )
                )
            filtered[key] = coerced
        return filtered, warnings, pk_fatal
