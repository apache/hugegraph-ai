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

"""Offline schema structure validation backed by hugegraph-llm-sdk."""

from __future__ import annotations

import json
from typing import Any

from hugegraph_mcp.artifacts import (
    ArtifactAccessError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    get_default_artifact_store,
)
from hugegraph_mcp.config import get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.runtime import get_current_actor
from hugegraph_mcp.stores.base import default_stdio_actor


def validate_schema_structure(
    *,
    schema: dict[str, Any] | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Validate a HugeGraph schema object or artifact using ``hugegraph_llm_sdk``."""

    if schema is not None and artifact_id is not None:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "Provide either schema or artifact_id, not both.",
            source="validate_schema_tool",
        )
    if schema is None and not artifact_id:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "Either schema or artifact_id is required.",
            source="validate_schema_tool",
        )

    target_schema: Any = schema
    if artifact_id is not None:
        cfg = get_effective_config()
        actor = get_current_actor() or default_stdio_actor()
        owner_key = actor.principal_key
        try:
            store = get_default_artifact_store(cfg)
            manifest = store.get_manifest(artifact_id, owner_key=owner_key)
            if manifest.kind not in {"schema", "schema_draft"}:
                return envelope_err(
                    ErrorType.VALIDATION_ERROR,
                    f"Artifact {artifact_id} has kind={manifest.kind!r}, expected schema or schema_draft.",
                    source="validate_schema_tool",
                )
            raw = store.read_all(artifact_id, owner_key=owner_key)
            target_schema = json.loads(raw.decode("utf-8"))
        except ArtifactAccessError as exc:
            return envelope_err(ErrorType.AUTHORIZATION_FAILED, str(exc), source="validate_schema_tool")
        except (ArtifactIntegrityError, ValueError) as exc:
            return envelope_err(ErrorType.VALIDATION_ERROR, str(exc), source="validate_schema_tool")
        except ArtifactNotFoundError as exc:
            return envelope_err(ErrorType.NOT_FOUND, str(exc), source="validate_schema_tool")

    if not isinstance(target_schema, dict):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "Schema must be a JSON object.",
            source="validate_schema_tool",
        )

    try:
        from hugegraph_llm_sdk.schema import validate_schema as sdk_validate_schema
    except ImportError:
        sdk_validate_schema = None

    warnings: list[str] = []
    try:
        if sdk_validate_schema is not None:
            issues = sdk_validate_schema(target_schema)
            serialized_issues = [{"path": item.path, "message": item.message} for item in issues]
            validation_scope = "schema_structure"
            sdk_available = True
        else:
            serialized_issues = _fallback_validate_schema(target_schema)
            validation_scope = "limited_fallback"
            sdk_available = False
            warnings.append(
                "hugegraph-llm-sdk is not installed; ran limited structural fallback validation. "
                "Install hugegraph-llm-sdk for full schema validation."
            )
    except Exception as exc:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"Schema validation failed: {exc}",
            source="validate_schema_tool",
        )
    try:
        from hugegraph_mcp.schema_snapshot import compute_schema_fingerprint

        fingerprint: str | None = compute_schema_fingerprint(target_schema)
    except (TypeError, ValueError):
        fingerprint = None
    return envelope_ok(
        {
            "valid": len(serialized_issues) == 0,
            "issues": serialized_issues,
            "schema_fingerprint": fingerprint,
            "validation_scope": validation_scope,
            "sdk_available": sdk_available,
        },
        warnings=warnings,
    )


def _fallback_validate_schema(schema: dict[str, Any]) -> list[dict[str, str]]:
    """Limited structural schema validator used when hugegraph-llm-sdk is not installed.

    Matches SDK semantics for required collections (``vertexlabels``, ``edgelabels``),
    optional ``propertykeys`` (only validated against when present in ``schema``),
    label-internal property references, and edge endpoint labels.
    """
    issues: list[dict[str, str]] = []

    def _collect_named(key: str, *, required: bool) -> dict[str, dict[str, Any]]:
        if key not in schema:
            if required:
                issues.append({"path": key, "message": "Required schema collection is missing"})
            return {}
        entries = schema[key]
        if not isinstance(entries, list):
            issues.append({"path": key, "message": "Expected an array"})
            return {}
        names: dict[str, dict[str, Any]] = {}
        for idx, entry in enumerate(entries):
            path = f"{key}[{idx}]"
            if not isinstance(entry, dict):
                issues.append({"path": path, "message": "Expected an object"})
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                issues.append({"path": f"{path}.name", "message": "Expected a non-empty name string"})
            elif name in names:
                issues.append({"path": f"{path}.name", "message": f"Duplicate name: {name}"})
            else:
                names[name] = entry
        return names

    def _collect_key_list(entry: dict[str, Any], field_name: str, path: str) -> list[str]:
        value = entry.get(field_name, [])
        if not isinstance(value, list):
            issues.append({"path": f"{path}.{field_name}", "message": "Expected an array of property names"})
            return []
        result: list[str] = []
        for idx, item in enumerate(value):
            item_path = f"{path}.{field_name}[{idx}]"
            if not isinstance(item, str) or not item.strip():
                issues.append({"path": item_path, "message": "Expected a non-empty property name string"})
            elif item in result:
                issues.append({"path": item_path, "message": f"Duplicate property reference: {item}"})
            else:
                result.append(item)
        return result

    prop_names = _collect_named("propertykeys", required=False)
    vertex_names = _collect_named("vertexlabels", required=True)
    _collect_named("edgelabels", required=True)

    has_propertykeys = "propertykeys" in schema

    for collection in ("vertexlabels", "edgelabels"):
        raw_collection = schema.get(collection)
        if not isinstance(raw_collection, list):
            continue
        key_fields = (
            ("primary_keys", "nullable_keys") if collection == "vertexlabels" else ("sort_keys", "nullable_keys")
        )
        for idx, entry in enumerate(raw_collection):
            if not isinstance(entry, dict):
                continue
            path = f"{collection}[{idx}]"
            props = _collect_key_list(entry, "properties", path)
            if has_propertykeys:
                raw_props = entry.get("properties", [])
                if isinstance(raw_props, list):
                    for pidx, prop in enumerate(raw_props):
                        if isinstance(prop, str) and prop not in prop_names:
                            issues.append(
                                {"path": f"{path}.properties[{pidx}]", "message": f"Unknown property key: {prop}"}
                            )
            for field_name in key_fields:
                for prop in _collect_key_list(entry, field_name, path):
                    if prop not in props:
                        issues.append(
                            {
                                "path": f"{path}.{field_name}",
                                "message": f"Property {prop!r} is not declared in this label's properties",
                            }
                        )
            if collection == "edgelabels":
                for end_field in ("source_label", "target_label"):
                    end_val = entry.get(end_field)
                    if not isinstance(end_val, str) or not end_val.strip():
                        issues.append(
                            {"path": f"{path}.{end_field}", "message": "Expected a non-empty vertex label name"}
                        )
                    elif end_val not in vertex_names:
                        issues.append({"path": f"{path}.{end_field}", "message": f"Unknown vertex label: {end_val}"})

    return issues
