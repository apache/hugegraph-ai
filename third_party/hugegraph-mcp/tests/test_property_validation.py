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

import pytest

from hugegraph_mcp.tools.property_validation import (
    property_specs,
    property_value_error,
    value_matches_type,
)


def test_property_specs_normalizes_schema_shapes_and_aliases():
    specs = property_specs(
        {
            "schema": {
                "propertyKeys": [
                    {
                        "propertyName": "count",
                        "dataType": "integer",
                        "cardinalityType": "single",
                    },
                    {
                        "property_name": "flags",
                        "data_type": "bool",
                        "cardinality": "list",
                    },
                    {"name": "title", "data_type": "string"},
                ]
            }
        }
    )

    assert specs == {
        "count": ("INT", "SINGLE"),
        "flags": ("BOOLEAN", "LIST"),
        "title": ("TEXT", "SINGLE"),
    }


@pytest.mark.parametrize(
    ("data_type", "value"),
    [
        ("TEXT", "value"),
        ("BOOLEAN", True),
        ("BYTE", -128),
        ("BYTE", 127),
        ("INT", -(2**31)),
        ("INT", 2**31 - 1),
        ("LONG", -(2**63)),
        ("LONG", 2**63 - 1),
        ("FLOAT", 1.5),
        ("DOUBLE", 2),
        ("UUID", "550e8400-e29b-41d4-a716-446655440000"),
        ("DATE", "2026-09-04T12:30:00Z"),
        ("DATE", 0),
        ("BLOB", "aGVsbG8="),
        ("BLOB", "0x00ff"),
        ("BLOB", [0, 127, 255, -1]),
        ("OBJECT", {"key": "value"}),
    ],
)
def test_value_matches_supported_types(data_type, value):
    assert value_matches_type(value, data_type) is True


@pytest.mark.parametrize(
    ("data_type", "value"),
    [
        ("TEXT", 1),
        ("BOOLEAN", 1),
        ("BYTE", 128),
        ("INT", 2**31),
        ("LONG", 2**63),
        ("FLOAT", float("inf")),
        ("DOUBLE", float("nan")),
        ("UUID", "not-a-uuid"),
        ("DATE", "not-a-date"),
        ("DATE", True),
        ("BLOB", "not base64!"),
        ("BLOB", [256]),
        ("OBJECT", []),
    ],
)
def test_value_rejects_invalid_types_and_ranges(data_type, value):
    assert value_matches_type(value, data_type) is False


@pytest.mark.parametrize("data_type", ["FLOAT", "DOUBLE"])
def test_floating_validation_is_total_for_arbitrary_precision_integers(data_type):
    assert value_matches_type(10**1000, data_type) is False
    assert value_matches_type(-(10**1000), data_type) is False


@pytest.mark.parametrize(
    ("data_type", "value", "expected"),
    [
        ("FLOAT", float.fromhex("0x1.fffffep+127"), True),
        ("FLOAT", 10**39, False),
        ("DOUBLE", float.fromhex("0x1.fffffffffffffp+1023"), True),
        ("DOUBLE", 10**309, False),
        ("FLOAT", float("inf"), False),
        ("FLOAT", float("-inf"), False),
        ("DOUBLE", float("nan"), False),
    ],
)
def test_floating_validation_rejects_overflow_and_nonfinite_values(data_type, value, expected):
    assert value_matches_type(value, data_type) is expected


def test_collection_floating_validation_handles_arbitrary_precision_element():
    assert (
        property_value_error(
            item_kind="vertex",
            item_index=0,
            property_name="weights",
            value=[1.0, 10**1000],
            spec=("DOUBLE", "LIST"),
        )
        == "vertex 0 property 'weights' element 1 expects DOUBLE, got int"
    )


def test_collection_validation_checks_container_and_each_element():
    wrong_container = property_value_error(
        item_kind="vertex",
        item_index=2,
        property_name="ages",
        value=1,
        spec=("INT", "LIST"),
    )
    wrong_element = property_value_error(
        item_kind="vertex",
        item_index=2,
        property_name="ages",
        value=[1, True],
        spec=("INT", "SET"),
    )

    assert wrong_container == "vertex 2 property 'ages' expects LIST of INT, got int"
    assert wrong_element == ("vertex 2 property 'ages' element 1 expects INT, got bool")


def test_property_validation_preserves_existing_none_contract():
    assert (
        property_value_error(
            item_kind="vertex",
            item_index=0,
            property_name="optional",
            value=None,
            spec=("TEXT", "SINGLE"),
        )
        is None
    )
    assert "element 0" in property_value_error(
        item_kind="vertex",
        item_index=0,
        property_name="optional_list",
        value=[None],
        spec=("TEXT", "LIST"),
    )
