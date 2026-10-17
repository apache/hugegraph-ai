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

"""Property-graph extraction and review using the configured model client."""

import json
import math
import re
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from hugegraph_llm.config import prompt
from hugegraph_llm.extraction_runtime.v1.contracts import ChunkInput, Issue, ReviewResult
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.llm_op.property_graph_extract import (
    PropertyGraphExtract,
    generate_extract_property_graph_prompt,
)

_JAVA_HEX_LETTERS = str.maketrans("ＡＢＣＤＥＦａｂｃｄｅｆ", "ABCDEFabcdef")
# The midpoint above the largest finite float32 rounds to infinity, not to FLOAT_MAX.
_FLOAT32_OVERFLOW_MIDPOINT = Decimal(2**128 - 2**103)


def _invalid_constant(value: str):
    raise ValueError(f"Invalid JSON constant: {value}")


def _parse_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite JSON number: {value}")
    return number


def _parse_json(response: str):
    text = response.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    return json.loads(text, parse_constant=_invalid_constant, parse_float=_parse_float)


def _parse_graph(response: str) -> dict:
    graph = _parse_json(response)
    if isinstance(graph, list):
        grouped = {"vertices": [], "edges": []}
        for item in graph:
            if not isinstance(item, dict) or item.get("type") not in ("vertex", "edge"):
                raise ValueError("Flat graph entries must declare type vertex or edge")
            grouped["vertices" if item["type"] == "vertex" else "edges"].append(item)
        graph = grouped
    if not isinstance(graph, dict) or any(not isinstance(graph.get(key), list) for key in ("vertices", "edges")):
        raise ValueError("Graph response must contain vertices and edges arrays")
    for key, kind in (("vertices", "vertex"), ("edges", "edge")):
        for item in graph[key]:
            if isinstance(item, dict):
                item.setdefault("type", kind)
    return graph


def _valid_id(value) -> bool:
    return (isinstance(value, str) and bool(value)) or (isinstance(value, int) and not isinstance(value, bool))


def _valid_uuid(value) -> bool:
    """Match HugeGraph StringEncoding.uuid without rewriting the supplied value."""
    if not isinstance(value, str):
        return False
    if len(value) == 36 and "-" in value:
        # Java UUID.fromString also accepts nonstandard widths and leading '+'.
        parts, bits = value.split("-"), 63
        if len(parts) != 5:
            return False
    elif len(value) == 32:
        parts, bits = [value[:16], value[16:]], 64
    else:
        return False
    for part in parts:
        # Java Character.digit(char, 16) includes BMP decimal digits and fullwidth
        # A-F. Python int also accepts underscores and non-BMP digits; exclude them.
        part = part.translate(_JAVA_HEX_LETTERS)
        if re.fullmatch(r"\+?[\da-fA-F]+", part) is None or any(ord(char) > 0xFFFF for char in part):
            return False
        if int(part, 16) >= 2**bits:
            return False
    return True


def _uuid_identity(value: str) -> int:
    """Compare accepted spellings as StringEncoding.uuid/UUID.fromString does."""
    if len(value) == 32:
        return (int(value[:16].translate(_JAVA_HEX_LETTERS), 16) << 64) | int(
            value[16:].translate(_JAVA_HEX_LETTERS), 16
        )
    parts = [int(part.translate(_JAVA_HEX_LETTERS), 16) for part in value.split("-")]
    identity = 0
    for part, bits in zip(parts, (32, 16, 16, 16, 48)):
        identity = (identity << bits) | (part & (2**bits - 1))
    return identity


def _float_identity(value) -> tuple[bool, int]:
    """Round the decimal Number.toString value directly to IEEE float32, ties to even."""
    decimal = Decimal(str(value))
    numerator, denominator = decimal.copy_abs().as_integer_ratio()
    if not numerator:
        return decimal.is_signed(), 0
    exponent = numerator.bit_length() - denominator.bit_length()
    below_power = (numerator < denominator << exponent) if exponent >= 0 else (numerator << -exponent < denominator)
    if below_power:
        exponent -= 1
    # One integer unit below is the least positive float32 subnormal, 2**-149.
    shift = max(exponent - 23, -149)
    if shift >= 0:
        denominator <<= shift
    else:
        numerator <<= -shift
    rounded, remainder = divmod(numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and rounded % 2):
        rounded += 1
    return decimal.is_signed(), rounded << (shift + 149)


def _valid_scalar(value, data_type: str) -> bool:
    if data_type == "TEXT":
        return isinstance(value, str)
    if data_type == "UUID":
        return _valid_uuid(value)
    if data_type == "BOOLEAN":
        return isinstance(value, bool)
    if data_type in ("BYTE", "INT", "LONG"):
        bits = {"BYTE": 8, "INT": 32, "LONG": 64}[data_type]
        return isinstance(value, int) and not isinstance(value, bool) and -(2 ** (bits - 1)) <= value < 2 ** (bits - 1)
    if data_type in ("FLOAT", "DOUBLE"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            if not math.isfinite(value):
                return False
        except OverflowError:
            return False
        # HugeGraph uses Float.valueOf(Number.toString()). Compare decimal values
        # to avoid binary64 double rounding; preserve normal rounding and underflow.
        return data_type == "DOUBLE" or Decimal(str(value)).copy_abs() < _FLOAT32_OVERFLOW_MIDPOINT
    if data_type == "DATE":
        if isinstance(value, int):
            # HugeGraph accepts Integer/Long epoch milliseconds, but not floats or booleans.
            return _valid_scalar(value, "LONG")
        if not isinstance(value, str):
            return False
        match = re.fullmatch(r"(\d{4}-\d{1,2}-\d{1,2})(?:\s(\d{2}:\d{2}:\d{2})(\.\d{1,3})?)?", value, re.ASCII)
        if match is None:
            return False
        # Match HugeGraph DateUtil's date, second and millisecond formats without normalizing the value.
        date_format = "%Y-%m-%d" + (" %H:%M:%S" if match[2] else "") + (".%f" if match[3] else "")
        try:
            datetime.strptime(value, date_format)
            return True
        except ValueError:
            return False
    # Leave unmodeled types (including OBJECT/BLOB) to HugeGraph instead of inventing restrictions.
    return value is not None


class PropertyGraphBundle:
    """Keep invalid graph entries available for repair instead of filtering them."""

    def __init__(self, *, llm: BaseLLM, schema: dict, example_prompt: str | None = None):
        self.llm = llm
        self.schema = deepcopy(schema)
        self.example_prompt = prompt.extract_graph_prompt if example_prompt is None else example_prompt
        self.vertex_labels = {item["name"]: item for item in self.schema["vertexlabels"]}
        self.edge_labels = {item["name"]: item for item in self.schema["edgelabels"]}
        self.property_keys = {item["name"]: item for item in self.schema.get("propertykeys", [])}

    def extract(self, chunk: ChunkInput) -> dict:
        request = self.example_prompt + generate_extract_property_graph_prompt(chunk.text, self.schema)
        return _parse_graph(self.llm.generate(prompt=request))

    def review(self, graph: dict, chunk: ChunkInput) -> ReviewResult:
        response = _parse_json(self.llm.generate(prompt=self._context(prompt.review_graph_prompt, graph, chunk)))
        if not isinstance(response, dict) or response.get("decision") not in ("pass", "fix", "block"):
            raise ValueError("Review decision must be pass, fix, or block")
        if not isinstance(response.get("issues"), list):
            raise ValueError("Review issues must be an array")
        issues = []
        for item in response["issues"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"].strip()
                or not isinstance(item.get("message"), str)
                or not item["message"].strip()
                or (item.get("evidence") is not None and not isinstance(item["evidence"], str))
            ):
                raise ValueError("Review issues require path/message strings and optional evidence text")
            issues.append(Issue(path=item["path"], message=item["message"], evidence=item.get("evidence")))
        if (response["decision"] == "pass") != (not issues):
            raise ValueError("A pass review must have no issues; fix/block must explain at least one issue")
        return ReviewResult(decision=response["decision"], issues=issues)

    def repair(self, graph: dict, chunk: ChunkInput, issues: list[Issue]) -> dict:
        request = self._context(prompt.repair_graph_prompt, graph, chunk, issues=[asdict(issue) for issue in issues])
        return _parse_graph(self.llm.generate(prompt=request))

    def _context(self, instructions: str, graph: dict, chunk: ChunkInput, **extra) -> str:
        context = {"text": chunk.text, "schema": self.schema, "graph": graph, **extra}
        return instructions + "\n## Input\n" + json.dumps(context, ensure_ascii=False, allow_nan=False)

    def _primary_identity(self, key: str, value) -> tuple:
        data_type = self.property_keys.get(key, {}).get("data_type")
        if data_type and _valid_scalar(value, data_type):
            if data_type == "UUID":
                return data_type, _uuid_identity(value)
            if data_type == "FLOAT":
                return data_type, _float_identity(value)
            if data_type == "DOUBLE":
                return data_type, float(value).hex()
            if data_type == "DATE" and isinstance(value, str):
                # DateUtil uses Joda's fraction-of-second SSS, so .1 means 100ms.
                date_format = "%Y-%m-%d" + (" %H:%M:%S" if re.search(r"\s", value) else "")
                date_format += ".%f" if "." in value else ""
                parsed = datetime.strptime(value, date_format)
                # SafeDateFormat uses the server's default zone, which this schema
                # does not expose. Compare wall times; never guess an epoch/text offset.
                return data_type, "wall", parsed
        return data_type, json.dumps(value, sort_keys=True)

    def validate(self, graph: dict, chunk: ChunkInput) -> list[Issue]:
        """Normalize this chunk's private graph in place and report all remaining problems."""
        del chunk
        issues = self._normalize(graph)
        vertices_by_id = {}
        uuid_ids_seen = set()
        primary_keys_seen = set()
        for key, kind, labels in (
            ("vertices", "vertex", self.vertex_labels),
            ("edges", "edge", self.edge_labels),
        ):
            for index, item in enumerate(graph[key]):
                path = f"{key}[{index}]"
                if not isinstance(item, dict):
                    issues.append(Issue(path, "Entry must be an object"))
                    continue
                if item.get("type", kind) != kind:
                    issues.append(Issue(path + ".type", f"Expected {kind}"))
                label = item.get("label")
                definition = labels.get(label) if isinstance(label, str) else None
                if definition is None:
                    issues.append(Issue(path + ".label", f"Unknown {kind} label: {label!r}"))
                properties = item.get("properties")
                if not isinstance(properties, dict):
                    issues.append(Issue(path + ".properties", "Properties must be an object"))
                elif definition is not None:
                    issues.extend(self._validate_properties(properties, definition, path))
                    keys = definition.get("primary_keys", []) if kind == "vertex" else []
                    if keys and all(key in properties and properties[key] not in (None, "") for key in keys):
                        identity = (label, tuple(self._primary_identity(key, properties[key]) for key in keys))
                        if identity in primary_keys_seen:
                            issues.append(Issue(path + ".properties", "Duplicate vertex primary key"))
                        primary_keys_seen.add(identity)
                if kind == "vertex":
                    vertex_id = item.get("id")
                    strategy = definition.get("id_strategy") if definition is not None else None
                    uuid_identity = (
                        _uuid_identity(vertex_id) if strategy == "CUSTOMIZE_UUID" and _valid_uuid(vertex_id) else None
                    )
                    if not _valid_id(vertex_id):
                        issues.append(Issue(path + ".id", "Vertex id must be a non-empty string or integer"))
                    elif vertex_id in vertices_by_id:
                        issues.append(Issue(path + ".id", f"Duplicate vertex id: {vertex_id!r}"))
                    else:
                        vertices_by_id[vertex_id] = item
                        if uuid_identity is not None and uuid_identity in uuid_ids_seen:
                            issues.append(Issue(path + ".id", f"Duplicate vertex id: {vertex_id!r}"))
                    if uuid_identity is not None:
                        uuid_ids_seen.add(uuid_identity)
                    if strategy == "CUSTOMIZE_STRING" and not isinstance(vertex_id, str):
                        issues.append(Issue(path + ".id", "CUSTOMIZE_STRING requires a string vertex id"))
                    if strategy == "CUSTOMIZE_NUMBER" and not _valid_scalar(vertex_id, "LONG"):
                        issues.append(
                            Issue(path + ".id", "CUSTOMIZE_NUMBER requires a signed 64-bit integer vertex id")
                        )
                    if strategy == "CUSTOMIZE_UUID" and not _valid_uuid(vertex_id):
                        issues.append(Issue(path + ".id", "CUSTOMIZE_UUID requires a valid UUID string vertex id"))
                else:
                    issues.extend(self._validate_endpoints(item, definition, vertices_by_id, path))
        return issues

    def _validate_properties(self, properties: dict, definition: dict, path: str) -> list[Issue]:
        issues = []
        allowed = definition.get("properties")
        required = set(definition.get("primary_keys", []))
        if allowed is not None and "nullable_keys" in definition:
            required.update(set(allowed) - set(definition["nullable_keys"]))
        for key in sorted(required):
            if key not in properties or properties[key] in (None, ""):
                issues.append(Issue(f"{path}.properties.{key}", "Required property is missing or empty"))
        for key, value in properties.items():
            property_path = f"{path}.properties.{key}"
            if allowed is not None and key not in allowed:
                issues.append(Issue(property_path, "Property is not declared for this label"))
            if value is None:
                if key not in required:
                    issues.append(Issue(property_path, "Omit absent properties instead of returning null"))
                continue
            property_key = self.property_keys.get(key, {})
            data_type = property_key.get("data_type")
            cardinality = property_key.get("cardinality")
            if cardinality in ("LIST", "SET"):
                if not isinstance(value, list):
                    issues.append(Issue(property_path, f"Expected an array for {cardinality} cardinality"))
                    continue
                if cardinality == "SET" and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
                    issues.append(Issue(property_path, "SET property contains duplicates"))
                values = value
            else:
                values = value if cardinality is None and isinstance(value, list) else [value]
                # Known types check their own shape; OBJECT and BLOB may contain JSON containers.
                if cardinality == "SINGLE" and not data_type and isinstance(value, (dict, list)):
                    issues.append(Issue(property_path, "Expected a scalar for SINGLE cardinality"))
            if data_type and any(not _valid_scalar(item, data_type) for item in values):
                issues.append(Issue(property_path, f"Value does not match property data type {data_type}"))
        return issues

    @staticmethod
    def _validate_endpoints(edge: dict, definition: dict | None, vertices: dict, path: str) -> list[Issue]:
        issues = []
        for endpoint, label_key, schema_key in (
            ("outV", "outVLabel", "source_label"),
            ("inV", "inVLabel", "target_label"),
        ):
            vertex_id = edge.get(endpoint)
            vertex = vertices.get(vertex_id) if _valid_id(vertex_id) else None
            if vertex is None:
                issues.append(Issue(f"{path}.{endpoint}", "Endpoint must reference a vertex in this graph"))
            if not isinstance(edge.get(label_key), str) or (
                vertex is not None and edge[label_key] != vertex.get("label")
            ):
                issues.append(Issue(f"{path}.{label_key}", "Endpoint label must match the referenced vertex"))
            if definition is not None and schema_key in definition and edge.get(label_key) != definition[schema_key]:
                issues.append(Issue(f"{path}.{label_key}", f"Endpoint label must match schema {schema_key}"))
        return issues

    def _normalize(self, graph: dict) -> list[Issue]:
        aliases: dict[tuple, set] = {}
        updates = []
        for item in graph["vertices"]:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                continue
            definition = self.vertex_labels.get(item["label"])
            if definition is None or not isinstance(item.get("properties"), dict):
                continue
            canonical = PropertyGraphExtract._primary_key_id(definition, item["properties"])
            target = canonical if canonical is not None else item.get("id")
            if not _valid_id(target):
                continue
            updates.append((item, target))
            for alias in (target, item.get("id")):
                if _valid_id(alias):
                    aliases.setdefault((item["label"], alias), set()).add(target)
        ambiguous = [key for key, targets in aliases.items() if len(targets) > 1]
        if ambiguous:
            # Keep the original graph so repeated validation cannot erase the ambiguity.
            return [Issue("vertices", f"Ambiguous vertex id alias: {key!r}") for key in ambiguous]
        for item, target in updates:
            item["id"] = target
        for edge in graph["edges"]:
            if not isinstance(edge, dict):
                continue
            for endpoint, label_key, legacy_key in (("outV", "outVLabel", "source"), ("inV", "inVLabel", "target")):
                vertex_id, label = edge.get(endpoint), edge.get(label_key)
                if vertex_id is None and isinstance(edge.get(legacy_key), dict):
                    legacy = edge[legacy_key]
                    label = legacy.get("label")
                    definition = self.vertex_labels.get(label) if isinstance(label, str) else None
                    if definition is not None and isinstance(legacy.get("properties"), dict):
                        vertex_id = PropertyGraphExtract._primary_key_id(definition, legacy["properties"])
                if isinstance(label, str) and _valid_id(vertex_id):
                    matches = aliases.get((label, vertex_id))
                    if matches:
                        edge[endpoint] = next(iter(matches))
                        edge[label_key] = label
        return []
