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

from typing import Any, get_type_hints

from hugegraph_llm.indices.vector_index.base import VectorStoreBase


def test_contract_docstrings_are_complete():
    """Every VectorStoreBase entry point must document its contract (no placeholder TODOs)."""
    for name in (
        "get_all_properties",
        "save_index_by_name",
        "get_vector_index_info",
        "from_name",
        "exist",
        "clean",
    ):
        doc = getattr(VectorStoreBase, name).__doc__ or ""
        assert "TODO" not in doc, name
        assert len(doc.strip()) > 10, name


def test_get_all_properties_returns_stored_property_values():
    """Properties are caller-supplied values (see add()); the base said list[str]."""
    assert get_type_hints(VectorStoreBase.get_all_properties)["return"] == list[Any]


def test_clean_returns_none():
    """Every backend's clean() deletes and returns nothing; the base said bool."""
    assert get_type_hints(VectorStoreBase.clean)["return"] in (None, type(None))
