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

from hugegraph_mcp.projection import project_element, project_items, validate_fields


def test_validate_fields_and_projection_preserves_identity():
    fields = validate_fields(["properties.name", "age"])
    assert fields == ("properties.name", "age")

    vertex = {
        "id": 123,
        "label": "person",
        "type": "vertex",
        "properties": {"name": "marko", "age": 29, "secret": "x"},
    }
    projected = project_element(vertex, fields)
    assert projected == {
        "id": 123,
        "label": "person",
        "type": "vertex",
        "properties": {"name": "marko", "age": 29},
    }
    assert isinstance(projected["id"], int)


def test_project_items_none_returns_original():
    items = [{"id": "v1", "properties": {"a": 1}}]
    assert project_items(items, None) is items
