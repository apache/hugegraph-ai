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

import asyncio
import json

from hugegraph_mcp import resources
from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.schema_snapshot import bound_schema_payload


def test_bound_schema_payload_is_deterministic_and_bounded():
    raw = {
        "propertykeys": [{"name": f"p{i:03d}"} for i in range(50)],
        "vertexlabels": [{"name": "person"}, {"name": "software"}],
        "edgelabels": [{"name": "knows"}],
        "indexlabels": [],
    }
    bounded, truncated, reason = bound_schema_payload(raw, max_items=10, max_bytes=10_000)
    assert truncated is True
    assert reason == "max_items_exceeded"
    assert len(bounded["propertykeys"]) == 10
    assert bounded["propertykeys"][0]["name"] == "p000"


def test_schema_resource_applies_bounds_while_keeping_full_fingerprint(monkeypatch):
    big_raw = {
        "propertykeys": [{"name": f"prop_{i:03d}", "data_type": "TEXT"} for i in range(250)],
        "vertexlabels": [],
        "edgelabels": [],
        "indexlabels": [],
    }
    monkeypatch.setattr(
        resources,
        "inspect_schema",
        lambda **kw: envelope_ok(
            {"summary": {}, "relations": [], "index_labels": [], "filtered": {}, "raw_schema": big_raw}
        ),
    )
    rendered = json.loads(asyncio.run(resources.read_schema_resource("default", "DEFAULT", "hugegraph")))
    assert rendered["truncated"] is True
    assert rendered["truncation_reason"] == "max_items_exceeded"
    assert len(rendered["schema"]["raw_schema"]["propertykeys"]) == 200
