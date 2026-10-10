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

import json
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GraphExtractClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: Optional[str] = None
    user: Optional[str] = None
    pwd: Optional[str] = None
    gs: Optional[str] = None


class GraphExtractRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    texts: Union[str, List[str]] = Field(..., description="Text or list of texts to extract a graph from.")
    graph_schema: Union[str, Dict[str, Any]] = Field(
        ...,
        alias="schema",
        description="Graph schema as a JSON string/object, or an existing graph name.",
    )
    example_prompt: Optional[str] = Query(None, description="Optional graph extraction prompt header.")
    extract_type: Literal["property_graph"] = Query("property_graph", description="Extraction type.")
    language: Literal["zh", "en"] = Query("zh", description="Language for chunk splitting.")
    split_type: Literal["document", "paragraph", "sentence"] = Query("document", description="Chunk split granularity.")
    include_meta: bool = Query(False, description="Include vertex/edge/text counts in the response.")
    client_config: Optional[GraphExtractClientConfig] = Field(None, description="Request-scoped HugeGraph connection.")

    @field_validator("texts")
    @classmethod
    def normalize_texts(cls, v):
        items = [v] if isinstance(v, str) else list(v)
        items = [t for t in items if t and t.strip()]
        if not items:
            raise ValueError("texts must not be empty.")
        return items

    @field_validator("graph_schema")
    @classmethod
    def normalize_schema(cls, v):
        def validate_schema_obj(schema_obj: Any) -> None:
            if not isinstance(schema_obj, dict):
                raise ValueError("schema JSON must be an object.")
            if "vertexlabels" not in schema_obj or "edgelabels" not in schema_obj:
                raise ValueError("schema must contain 'vertexlabels' and 'edgelabels'.")
            if not isinstance(schema_obj["vertexlabels"], list) or not isinstance(schema_obj["edgelabels"], list):
                raise ValueError("'vertexlabels' and 'edgelabels' must be lists.")

            for vlabel in schema_obj["vertexlabels"]:
                if not isinstance(vlabel, dict):
                    raise ValueError("Each item in 'vertexlabels' must be an object.")
                if not isinstance(vlabel.get("name"), str) or not vlabel["name"].strip():
                    raise ValueError("Each vertex label must have a non-empty string 'name'.")
                props = vlabel.get("properties")
                if not isinstance(props, list) or len(props) == 0:
                    raise ValueError("Each vertex label must have a non-empty 'properties' list.")

            for elabel in schema_obj["edgelabels"]:
                if not isinstance(elabel, dict):
                    raise ValueError("Each item in 'edgelabels' must be an object.")
                for key in ("name", "source_label", "target_label"):
                    if not isinstance(elabel.get(key), str) or not elabel[key].strip():
                        raise ValueError(f"Each edge label must have a non-empty string '{key}'.")
                if "properties" in elabel and not isinstance(elabel["properties"], list):
                    raise ValueError("'properties' in edge labels must be a list when provided.")

            if "propertykeys" in schema_obj and not isinstance(schema_obj["propertykeys"], list):
                raise ValueError("'propertykeys' must be a list when provided.")

        if isinstance(v, dict):
            validate_schema_obj(v)
            return json.dumps(v, ensure_ascii=False)
        v = v.strip()
        if not v:
            raise ValueError("schema must not be empty.")
        if v.startswith("{"):
            try:
                schema_obj = json.loads(v)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON schema: {e}") from e
            validate_schema_obj(schema_obj)
            return v
        return v

    @model_validator(mode="after")
    def validate_schema_and_client_config(self):
        schema = self.graph_schema
        is_named_schema = isinstance(schema, str) and not schema.strip().startswith("{")
        if not is_named_schema:
            if self.client_config is not None:
                raise ValueError(
                    "client_config is not allowed when 'schema' is inline JSON; graph extraction "
                    "from an inline schema does not connect to HugeGraph."
                )
            return self
        if self.client_config is None:
            raise ValueError(
                "client_config is required when 'schema' refers to an existing graph name; "
                "provide inline schema JSON instead to extract without a HugeGraph connection."
            )
        if self.client_config.graph != schema:
            raise ValueError(
                "When 'schema' is a graph name, client_config.graph must match it "
                f"(got schema='{schema}', client_config.graph='{self.client_config.graph}')."
            )
        return self
