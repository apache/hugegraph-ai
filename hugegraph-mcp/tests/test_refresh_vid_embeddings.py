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

from unittest.mock import Mock

from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.tools import refresh_vid_embeddings as refresh_vid_embeddings_module


def test_refresh_vid_embeddings_success(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(
        return_value=envelope_ok(
            {"ok": True, "data": {"added": 3, "removed": 1, "summary": "done"}}
        )
    )
    monkeypatch.setattr(refresh_vid_embeddings_module, "post", post)

    result = refresh_vid_embeddings_module.refresh_vid_embeddings(confirm=True)

    assert result["ok"] is True
    assert result["data"] == {"added": 3, "removed": 1, "summary": "done"}
    post.assert_called_once_with("/vid-embeddings/refresh", json={})


def test_refresh_vid_embeddings_parses_remove_variants(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok("Remove 2 vectors, add 3 vectors."))
    monkeypatch.setattr(refresh_vid_embeddings_module, "post", post)

    result = refresh_vid_embeddings_module.refresh_vid_embeddings(confirm=True)

    assert result["ok"] is True
    assert result["data"]["added"] == 3
    assert result["data"]["removed"] == 2


def test_refresh_vid_embeddings_readonly(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    post = Mock()
    monkeypatch.setattr(refresh_vid_embeddings_module, "post", post)

    result = refresh_vid_embeddings_module.refresh_vid_embeddings(confirm=True)

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"
    post.assert_not_called()


def test_refresh_vid_embeddings_missing_confirm(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock()
    monkeypatch.setattr(refresh_vid_embeddings_module, "post", post)

    result = refresh_vid_embeddings_module.refresh_vid_embeddings(confirm=False)

    assert result["ok"] is False
    assert result["error"]["type"] == "CONFIRM_REQUIRED"
    post.assert_not_called()
