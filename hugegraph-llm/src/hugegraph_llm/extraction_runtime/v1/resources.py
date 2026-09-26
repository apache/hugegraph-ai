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

"""Read-only access to versioned packaged runtime resources."""

from __future__ import annotations

import json
from importlib.resources import files

from hugegraph_llm.extraction_runtime.v1.json_value import JsonObject, freeze_json_object


def load_runtime_contract_resource() -> JsonObject:
    """Load and validate the packaged runtime v1 descriptor."""
    resource = files("hugegraph_llm.extraction_runtime.resources").joinpath("runtime-contract-v1.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("runtime contract resource must be a JSON object")
    if value.get("schema") != "hugegraph-ai/extraction-runtime-resource" or value.get("resource_version") != 1:
        raise ValueError("unsupported runtime contract resource")
    return freeze_json_object(value)
