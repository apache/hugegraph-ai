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

import inspect

from hugegraph_mcp.tools import graph_data_validate
from hugegraph_mcp.tools.schema_utils import (
    normalized_schema_summary,
    property_cardinalities,
    schema_payload,
)


def test_normalized_schema_summary_uses_shared_canonical_shape():
    schema = {
        "schema": {
            "propertykeys": [
                {"name": "name", "dataType": "TEXT", "id": 1},
                {"name": "rank", "data_type": "INT", "cardinality": "SINGLE"},
            ],
            "vertexlabels": [
                {
                    "name": "city",
                    "properties": [{"name": "name"}, "rank"],
                    "primaryKeys": [{"name": "name"}],
                    "nullableKeys": ["rank"],
                    "id": 2,
                }
            ],
            "edgelabels": [
                {
                    "name": "knows",
                    "sourceLabel": "person",
                    "target_label": "person",
                    "properties": [{"name": "rank"}],
                    "frequency": "SINGLE",
                }
            ],
            "indexlabels": [
                {
                    "name": "cityByName",
                    "baseType": "VERTEX_LABEL",
                    "base_label": "city",
                    "indexType": "SECONDARY",
                    "fields": [{"name": "name"}],
                    "status": "CREATED",
                }
            ],
        }
    }

    assert normalized_schema_summary(schema) == {
        "propertykeys": [
            {"name": "name", "data_type": "TEXT"},
            {"name": "rank", "data_type": "INT", "cardinality": "SINGLE"},
        ],
        "vertexlabels": [
            {
                "name": "city",
                "properties": ["name", "rank"],
                "primary_keys": ["name"],
                "nullable_keys": ["rank"],
            }
        ],
        "edgelabels": [
            {
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "properties": ["rank"],
                "frequency": "SINGLE",
            }
        ],
        "indexlabels": [
            {
                "name": "cityByName",
                "base_type": "VERTEX_LABEL",
                "base_label": "city",
                "index_type": "SECONDARY",
                "fields": ["name"],
            }
        ],
    }


def test_schema_payload_preserves_explicit_empty_schema():
    assert schema_payload({"schema": {}}) == {}


def test_property_cardinalities_supports_wrappers_and_field_aliases():
    assert property_cardinalities(
        {
            "schema": {
                "propertyKeys": [
                    {"name": "name"},
                    {"propertyName": "aliases", "cardinalityType": "list"},
                    {"property_name": "tags", "cardinality_type": "set"},
                ]
            }
        }
    ) == {"name": "SINGLE", "aliases": "LIST", "tags": "SET"}

    assert property_cardinalities(
        {"propertykeys": [{"name": "values", "cardinality": "LIST"}]}
    ) == {"values": "LIST"}


def test_normalized_schema_summary_binds_property_key_cardinality_aliases():
    assert normalized_schema_summary(
        {
            "schema": {
                "propertyKeys": [
                    {
                        "propertyName": "aliases",
                        "dataType": "TEXT",
                        "cardinalityType": "LIST",
                    }
                ]
            }
        }
    )["propertykeys"] == [
        {"name": "aliases", "data_type": "TEXT", "cardinality": "LIST"}
    ]


def test_normalized_schema_summary_binds_supported_schema_fields():
    summary = normalized_schema_summary(
        {
            "schema": {
                "propertykeys": [
                    {
                        "name": "score",
                        "data_type": "INT",
                        "cardinality": "SINGLE",
                        "aggregate_type": "SUM",
                    }
                ],
                "vertexlabels": [
                    {
                        "name": "person",
                        "properties": ["name"],
                        "primary_keys": ["name"],
                        "index_labels": ["person_by_name"],
                        "enable_label_index": False,
                    }
                ],
                "edgelabels": [
                    {
                        "name": "knows",
                        "source_label": "person",
                        "target_label": "person",
                        "sort_keys": ["score"],
                        "enableLabelIndex": True,
                    }
                ],
            }
        }
    )

    assert summary["propertykeys"] == [
        {
            "name": "score",
            "data_type": "INT",
            "cardinality": "SINGLE",
            "aggregate_type": "SUM",
        }
    ]
    assert summary["vertexlabels"] == [
        {
            "name": "person",
            "properties": ["name"],
            "primary_keys": ["name"],
            "index_labels": ["person_by_name"],
            "enable_label_index": False,
        }
    ]
    assert summary["edgelabels"] == [
        {
            "name": "knows",
            "source_label": "person",
            "target_label": "person",
            "sort_keys": ["score"],
            "enable_label_index": True,
        }
    ]


def test_normalized_schema_summary_includes_supported_user_data_fields():
    summary = normalized_schema_summary(
        {
            "schema": {
                "propertykeys": [
                    {
                        "name": "score",
                        "data_type": "INT",
                        "user_data": {"u": 1, "~create_time": "server-value"},
                    }
                ],
                "vertexlabels": [{"name": "person", "user_data": {"owner": "mcp"}}],
                "edgelabels": [{"name": "knows", "user_data": {"owner": "mcp"}}],
            }
        },
        include_user_data=True,
    )

    assert summary["propertykeys"][0]["user_data"] == {"u": 1}
    assert summary["vertexlabels"][0]["user_data"] == {"owner": "mcp"}
    assert summary["edgelabels"][0]["user_data"] == {"owner": "mcp"}


def test_graph_data_validate_does_not_reverse_import_ingest_module():
    source = inspect.getsource(graph_data_validate)

    assert "import ingest_graph_data" not in source
    assert "tools.ingest_graph_data" not in source
