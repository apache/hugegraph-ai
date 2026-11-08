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

"""Pure schema drafting, validation and example formatting for graph extraction."""

import json
import math
import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from hugegraph_llm_sdk.errors import ModelOutputError
from hugegraph_llm_sdk.extraction_runtime.review import Issue
from hugegraph_llm_sdk.models import require_model
from hugegraph_llm_sdk.prompts import DEFAULT_SCHEMA_PROMPT

_DATA_TYPES = frozenset({"OBJECT", "BOOLEAN", "BYTE", "INT", "LONG", "FLOAT", "DOUBLE", "TEXT", "BLOB", "DATE", "UUID"})
_CARDINALITIES = frozenset({"SINGLE", "LIST", "SET"})
_FREQUENCIES = frozenset({"DEFAULT", "SINGLE", "MULTIPLE"})
_ID_STRATEGIES = frozenset(
    {"DEFAULT", "AUTOMATIC", "PRIMARY_KEY", "CUSTOMIZE_STRING", "CUSTOMIZE_NUMBER", "CUSTOMIZE_UUID"}
)


@dataclass
class SchemaDraft:
    """A model-produced schema, including validation findings for caller review."""

    schema: dict[str, Any]
    issues: list[Issue] = field(default_factory=list)


def _json_issues(schema: dict) -> list[Issue]:
    """Check retained metadata as well as modeled fields before any model call."""
    issues: list[Issue] = []
    pending: list[tuple[object, str, frozenset[int]]] = [(schema, "schema", frozenset())]
    while pending:
        value, path, ancestors = pending.pop()
        if value is None or isinstance(value, (str, bool, int)):
            continue
        if isinstance(value, float):
            if not math.isfinite(value):
                issues.append(Issue(path, "JSON numbers must be finite"))
            continue
        if not isinstance(value, (dict, list)):
            issues.append(Issue(path, f"Expected a JSON value, got {type(value).__name__}"))
            continue
        identity = id(value)
        if identity in ancestors:
            issues.append(Issue(path, "Circular references are not valid JSON"))
            continue
        ancestors = ancestors | {identity}
        if isinstance(value, list):
            pending.extend((item, f"{path}[{index}]", ancestors) for index, item in enumerate(value))
        else:
            for key, item in value.items():
                if not isinstance(key, str):
                    issues.append(Issue(path, "JSON object keys must be strings"))
                else:
                    pending.append((item, f"{path}.{key}", ancestors))
    if not issues:
        try:
            json.dumps(schema, allow_nan=False)
        except (ValueError, TypeError, OverflowError, RecursionError):
            issues.append(Issue("schema", "Schema exceeds JSON serialization limits"))
    return issues


def validate_schema(schema: object) -> list[Issue]:
    """Report malformed schema and references without changing or completing it.

    HugeGraph metadata and optional fields are preserved. A missing global
    ``propertykeys`` collection is allowed for existing simplified schemas;
    when provided, every label property must reference a declared property key.
    Extraction constrains properties only when a label declares ``properties``;
    an explicit empty array permits no properties, while omission is unrestricted.
    Omitted optional defaults are never written into the caller's dictionary.
    """
    if not isinstance(schema, dict):
        return [Issue("schema", "Schema must be a JSON object")]
    issues = _json_issues(schema)
    if issues:
        return issues

    def issue(path: str, message: str) -> None:
        issues.append(Issue(path, message))

    def named_items(key: str, *, required: bool = False) -> dict[str, dict]:
        if key not in schema:
            if required:
                issue(key, "Required schema collection is missing")
            return {}
        entries = schema[key]
        if not isinstance(entries, list):
            issue(key, "Expected an array")
            return {}
        names: dict[str, dict] = {}
        ids: set[str] = set()
        for index, entry in enumerate(entries):
            path = f"{key}[{index}]"
            if not isinstance(entry, dict):
                issue(path, "Expected an object")
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                issue(f"{path}.name", "Expected a non-empty name string")
            elif name in names:
                issue(f"{path}.name", f"Duplicate name: {name}")
            else:
                names[name] = entry
            if "id" in entry:
                identifier = entry["id"]
                if type(identifier) not in (str, int) or (isinstance(identifier, str) and not identifier.strip()):
                    issue(f"{path}.id", "Expected a non-empty string or integer schema ID")
                else:
                    # Schema label IDs are rendered into primary-key vertex IDs
                    # as text, so 1 and "1" identify the same label namespace.
                    identity = str(identifier)
                    if identity in ids:
                        issue(f"{path}.id", "Duplicate schema ID")
                    ids.add(identity)
        return names

    property_keys = named_items("propertykeys")
    vertex_labels = named_items("vertexlabels", required=True)
    named_items("edgelabels", required=True)

    def entries(key: str):
        collection = schema.get(key, [])
        if isinstance(collection, list):
            for index, entry in enumerate(collection):
                if isinstance(entry, dict):
                    yield f"{key}[{index}]", entry

    def enum_value(entry: dict, key: str, accepted: frozenset[str], path: str) -> None:
        if key not in entry:
            return
        value = entry[key]
        if not isinstance(value, str) or value not in accepted:
            issue(f"{path}.{key}", f"Expected one of: {', '.join(sorted(accepted))}")

    def key_list(entry: dict, key: str, path: str) -> list[str]:
        value = entry.get(key, [])
        if not isinstance(value, list):
            issue(f"{path}.{key}", "Expected an array of property names")
            return []
        result: list[str] = []
        for index, item in enumerate(value):
            item_path = f"{path}.{key}[{index}]"
            if not isinstance(item, str) or not item.strip():
                issue(item_path, "Expected a non-empty property name string")
            elif item in result:
                issue(item_path, f"Duplicate property reference: {item}")
            else:
                result.append(item)
        return result

    for path, entry in entries("propertykeys"):
        enum_value(entry, "data_type", _DATA_TYPES, path)
        enum_value(entry, "cardinality", _CARDINALITIES, path)

    for collection in ("vertexlabels", "edgelabels"):
        for path, entry in entries(collection):
            properties = key_list(entry, "properties", path)
            if "propertykeys" in schema:
                for index, name in enumerate(
                    entry.get("properties", []) if isinstance(entry.get("properties", []), list) else []
                ):
                    if isinstance(name, str) and name not in property_keys:
                        issue(f"{path}.properties[{index}]", f"Unknown property key: {name}")
            keys = ("primary_keys", "nullable_keys") if collection == "vertexlabels" else ("sort_keys", "nullable_keys")
            references = {key: key_list(entry, key, path) for key in keys}
            for key, names in references.items():
                for name in names:
                    if name not in properties:
                        issue(f"{path}.{key}", f"Property {name!r} is not declared in this label's properties")
            if collection == "vertexlabels":
                enum_value(entry, "id_strategy", _ID_STRATEGIES, path)
                strategy = entry.get("id_strategy")
                if strategy == "PRIMARY_KEY" and not references["primary_keys"]:
                    issue(f"{path}.primary_keys", "PRIMARY_KEY requires at least one primary key")
                if strategy in (None, "DEFAULT", "PRIMARY_KEY"):
                    for name in references["primary_keys"]:
                        if name in references["nullable_keys"]:
                            issue(f"{path}.nullable_keys", f"Primary key {name!r} cannot be nullable")
            else:
                enum_value(entry, "frequency", _FREQUENCIES, path)
                frequency = entry.get("frequency")
                if frequency in ("DEFAULT", "SINGLE") and references["sort_keys"]:
                    issue(f"{path}.sort_keys", f"{frequency} frequency cannot have sort keys")
                elif frequency == "MULTIPLE" and not references["sort_keys"]:
                    issue(f"{path}.sort_keys", "MULTIPLE frequency requires at least one sort key")
                for name in references["sort_keys"]:
                    if name in references["nullable_keys"]:
                        issue(f"{path}.nullable_keys", f"Sort key {name!r} cannot be nullable")
                for key in ("source_label", "target_label"):
                    name = entry.get(key)
                    if not isinstance(name, str) or not name.strip():
                        issue(f"{path}.{key}", "Expected a non-empty vertex label name")
                    elif name not in vertex_labels:
                        issue(f"{path}.{key}", f"Unknown vertex label: {name}")
    return issues


def _load_examples(value: str, label: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}") from exc


def normalize_query_examples(examples: object = ()) -> list[dict[str, str]]:
    """Normalize question strings or description/Gremlin examples without I/O."""
    if examples is None or (isinstance(examples, str) and not examples.strip()):
        return []
    if isinstance(examples, str):
        examples = _load_examples(examples, "Query examples")
    if not isinstance(examples, (list, tuple)):
        raise ValueError("Query examples must be a JSON list.")
    result = []
    for index, item in enumerate(examples):
        if isinstance(item, str):
            if not item.strip():
                raise ValueError(f"Query examples[{index}] must be a non-empty string.")
            result.append({"description": item.strip(), "gremlin": ""})
        elif isinstance(item, dict):
            description, gremlin = item.get("description"), item.get("gremlin")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("Each query example object must contain a non-empty `description` string.")
            if not isinstance(gremlin, str):
                raise ValueError("Each query example object must contain a `gremlin` string.")
            result.append({"description": description.strip(), "gremlin": gremlin.strip()})
        else:
            raise ValueError("Query examples must contain strings or objects with `description` and `gremlin` fields.")
    return result


def normalize_few_shot_schema(examples: object = None) -> dict:
    """Check the example's object shape; semantic findings belong to validate_schema."""
    if examples is None or (isinstance(examples, str) and not examples.strip()):
        return {}
    if isinstance(examples, str):
        examples = _load_examples(examples, "Few-shot schema examples")
    if not isinstance(examples, dict):
        raise ValueError("Few-shot schema examples must be a JSON object.")
    return deepcopy(examples)


def normalize_query_examples_json(examples: object = None) -> str:
    """JSON text counterpart retaining the UI's blank-input fallback convention."""
    if examples is None or (isinstance(examples, str) and not examples.strip()):
        return ""
    return json.dumps(normalize_query_examples(examples), indent=2, ensure_ascii=False)


def normalize_few_shot_schema_json(examples: object = None) -> str:
    """Validate and format an example object, keeping blank input blank."""
    if examples is None or (isinstance(examples, str) and not examples.strip()):
        return ""
    return json.dumps(normalize_few_shot_schema(examples), indent=2, ensure_ascii=False)


def choose_schema_examples(
    query_examples: object,
    few_shot_schema: object,
    *,
    default_questions: object = (),
    default_schema: object = None,
) -> tuple[str, str]:
    """Choose explicit examples or supplied defaults without reading configuration."""
    questions = normalize_query_examples_json(query_examples)
    schema = normalize_few_shot_schema_json(few_shot_schema)
    return (
        questions or normalize_query_examples_json(default_questions),
        schema or normalize_few_shot_schema_json(default_schema),
    )


def build_schema_prompt(
    texts: str | Iterable[str],
    questions: object = (),
    example_schema: object = None,
    prompt: str | None = None,
) -> str:
    """Render the shared three-input schema prompt with caller-supplied data."""
    if isinstance(texts, str):
        texts = [texts]
    else:
        try:
            texts = list(texts)
        except TypeError as exc:
            raise ValueError("texts must be a string or an iterable of strings") from exc
    if any(not isinstance(text, str) for text in texts):
        raise ValueError("texts must contain only strings")
    normalized_questions = normalize_query_examples(questions)
    normalized_schema = normalize_few_shot_schema(example_schema)
    if prompt is not None and not isinstance(prompt, str):
        raise ValueError("prompt must be a string or None")
    return (DEFAULT_SCHEMA_PROMPT if prompt is None else prompt).format(
        raw_texts="\n".join(f"- {text}" for text in texts),
        query_examples="\n".join(f"- {example}" for example in normalized_questions) or "None",
        few_shot_schema=json.dumps(normalized_schema, indent=2, ensure_ascii=False) if normalized_schema else "None",
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def parse_schema_response(response: object) -> dict:
    """Parse a schema JSON object, accepting the legacy Markdown code fence."""
    if not isinstance(response, str) or not response.strip():
        raise ModelOutputError("LLM returned an empty or non-text schema response")
    text = response.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    try:
        schema = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant, parse_float=_finite_float
        )
    except ValueError as exc:
        raise ModelOutputError("Invalid JSON response from LLM") from exc
    if not isinstance(schema, dict):
        raise ModelOutputError("LLM schema response must be a JSON object")
    return schema


def _design_texts(texts: str | Iterable[str]) -> list[str]:
    """Validate public drafting samples without narrowing legacy prompt helpers."""
    if isinstance(texts, str):
        result = [texts]
    else:
        try:
            result = list(texts)
        except TypeError as exc:
            raise ValueError("texts must be a string or an iterable of strings") from exc
    if not result or any(not isinstance(text, str) or not text.strip() for text in result):
        raise ValueError("Schema design requires at least one non-empty text; every text must be a non-empty string")
    return result


def design_schema(
    texts: str | Iterable[str],
    *,
    model,
    questions: object = (),
    example_schema: object = None,
    prompt: str | None = None,
) -> SchemaDraft:
    """Draft a schema with an explicit model; retain invalid drafts and findings."""
    require_model(model)
    request = build_schema_prompt(_design_texts(texts), questions, example_schema, prompt)
    schema = parse_schema_response(model.generate(prompt=request))
    return SchemaDraft(schema=schema, issues=validate_schema(schema))


async def adesign_schema(
    texts: str | Iterable[str],
    *,
    model,
    questions: object = (),
    example_schema: object = None,
    prompt: str | None = None,
) -> SchemaDraft:
    """Draft with an async model; sync models require an explicit ThreadedModel."""
    require_model(model, asynchronous=True)
    request = build_schema_prompt(_design_texts(texts), questions, example_schema, prompt)
    response = await model.agenerate(prompt=request)
    schema = parse_schema_response(response)
    return SchemaDraft(schema=schema, issues=validate_schema(schema))
