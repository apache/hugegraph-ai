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

import pytest

from hugegraph_mcp import resources
from hugegraph_mcp.artifacts import ArtifactAccessError, get_default_artifact_store
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.resource_uri import InvalidResourceURIError, build_artifact_resource_uri, parse_resource_uri
from hugegraph_mcp.stores.base import Actor


def test_artifact_uri_parsing_and_rejection():
    uri = build_artifact_resource_uri("art-123")
    assert uri == "artifact://art-123"
    assert parse_resource_uri(uri).artifact_id == "art-123"

    part_uri = build_artifact_resource_uri("art-123", part_id=2)
    assert part_uri == "artifact://art-123/parts/2"
    parsed_part = parse_resource_uri(part_uri)
    assert parsed_part.part_id == 2

    for bad in ("artifact://art-123?x=1", "artifact://%252e%252e", "artifact://art-123/parts/abc"):
        with pytest.raises(InvalidResourceURIError):
            parse_resource_uri(bad)


def test_artifact_manifest_and_part_resources_enforce_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(tmp_path))
    cfg = MCPConfig.from_env()
    owner = Actor(tenant="t1", subject="u1", issuer="test-idp")
    other = Actor(tenant="t2", subject="u2", issuer="test-idp")
    manifest = get_default_artifact_store(cfg).put(
        "hello artifact",
        owner_key=owner.principal_key,
        tenant=owner.tenant,
        target_graph={"graph": "hugegraph"},
        kind="extraction_result",
    )

    manifest_json = json.loads(
        asyncio.run(resources.read_artifact_manifest_resource(manifest.artifact_id, actor=owner))
    )
    assert manifest_json["manifest"]["artifact_id"] == manifest.artifact_id

    part_json = json.loads(asyncio.run(resources.read_artifact_part_resource(manifest.artifact_id, 0, actor=owner)))
    assert part_json["content"] == "hello artifact"

    with pytest.raises(ArtifactAccessError):
        asyncio.run(resources.read_artifact_manifest_resource(manifest.artifact_id, actor=other))
