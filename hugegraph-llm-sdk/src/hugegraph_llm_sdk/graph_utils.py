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

"""Pure HugeGraph identity and extraction-prompt helpers."""


def generate_extract_property_graph_prompt(text, schema=None) -> str:
    return f"""---
Following the full instructions above, try to extract the following text from the given schema, output the JSON result:
# Input
## Text:
{text}
## Graph schema
{schema}

# Output"""


def primary_key_id(vertex_label, properties):
    """Return HugeGraph's escaped primary-key ID when the schema supplies one."""
    id_strategy = vertex_label.get("id_strategy")
    if id_strategy and str(id_strategy).upper() not in ("DEFAULT", "PRIMARY_KEY"):
        return None
    primary_keys = vertex_label.get("primary_keys", [])
    if not primary_keys or "id" not in vertex_label:
        return None
    values = []
    for key in primary_keys:
        value = properties.get(key)
        if value is None or value == "":
            return None
        values.append(str(value).replace("!", "`!"))
    # Match HugeGraph's concatValues(), followed by splicing().
    return ":".join(part.replace(":", "`:") for part in (str(vertex_label["id"]), "!".join(values)))
