# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest

from hugegraph_llm_sdk.graph_utils import primary_key_id

PERSON = {"id": 1, "name": "person", "primary_keys": ["name", "city"]}


@pytest.mark.parametrize(
    ("vertex_label", "properties", "expected"),
    [
        (PERSON, {"name": "Alice", "city": "Beijing"}, "1:Alice!Beijing"),
        (PERSON | {"id_strategy": "primary_key"}, {"name": "Alice", "city": "Beijing"}, "1:Alice!Beijing"),
        (PERSON | {"id": "a:b"}, {"name": "p!q", "city": "r:s"}, "a`:b:p`!q!r`:s"),
        (PERSON | {"id_strategy": "CUSTOMIZE_STRING"}, {"name": "Alice", "city": "Beijing"}, None),
        (PERSON, {"name": "Alice", "city": ""}, None),
        (PERSON, {"name": "Alice"}, None),
        ({"name": "person", "primary_keys": ["name"]}, {"name": "Alice"}, None),
        (PERSON | {"primary_keys": []}, {"name": "Alice"}, None),
    ],
)
def test_primary_key_id_escapes_text_keys_like_hugegraph_splicing(vertex_label, properties, expected):
    assert primary_key_id(vertex_label, properties) == expected
