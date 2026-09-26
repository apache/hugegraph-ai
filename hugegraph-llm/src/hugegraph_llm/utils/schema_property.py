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

import re
from typing import Any, Dict

COLLECTION_CARDINALITIES = {"LIST", "SET"}
INTEGER_DATA_TYPES = {"BYTE", "INT", "LONG"}
FLOAT_DATA_TYPES = {"FLOAT", "DOUBLE"}
TEXT_DATA_TYPES = {"TEXT", "UUID"}


def is_schema_property_value(
    value: Any,
    prop_schema: Dict[str, Any],
    *,
    strict_data_type: bool = False,
) -> bool:
    data_type = prop_schema.get("data_type")
    cardinality = prop_schema.get("cardinality")
    if not data_type or not cardinality:
        return True
    return is_property_value_for_type(
        data_type,
        cardinality,
        value,
        strict_data_type=strict_data_type,
    )


def is_property_value_for_type(
    data_type: str,
    cardinality: str,
    value: Any,
    *,
    strict_data_type: bool = False,
) -> bool:
    cardinality = str(cardinality).upper()
    if cardinality in COLLECTION_CARDINALITIES:
        return isinstance(value, list) and all(
            is_single_property_value(data_type, item, strict_data_type=strict_data_type) for item in value
        )
    return is_single_property_value(data_type, value, strict_data_type=strict_data_type)


def is_single_property_value(data_type: str, value: Any, *, strict_data_type: bool = False) -> bool:
    data_type = str(data_type).upper()
    if data_type == "BOOLEAN":
        return isinstance(value, bool)
    if data_type in INTEGER_DATA_TYPES:
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type in FLOAT_DATA_TYPES:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if data_type in TEXT_DATA_TYPES:
        return isinstance(value, str)
    if data_type == "DATE":
        return isinstance(value, str) and bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))
    if strict_data_type:
        raise ValueError(f"Unknown/Unsupported data type: {data_type}")
    return True
