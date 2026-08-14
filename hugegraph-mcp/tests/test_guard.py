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

from hugegraph_mcp.guard import Capability, guard, require_capability

WRITE_CAPABILITIES = (
    Capability.DATA_WRITE,
    Capability.SCHEMA_WRITE,
    Capability.INDEX_WRITE,
    Capability.DEBUG_WRITE,
)


def test_guard_allows_read_in_readonly(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    assert guard(Capability.READ) is None
    assert guard(Capability.GENERATE) is None


def test_guard_blocks_write_in_readonly(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    for capability in WRITE_CAPABILITIES:
        result = guard(capability)

        assert result is not None
        assert result["ok"] is False
        assert result["error"]["type"] == "READONLY_VIOLATION"
        assert result["meta"]["capability"] == capability.value


def test_guard_allows_all_when_not_readonly(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    for capability in Capability:
        assert guard(capability) is None


def test_guard_returns_envelope(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    result = guard(Capability.DATA_WRITE)

    assert result is not None
    assert set(result) == {
        "ok",
        "data",
        "error",
        "warnings",
        "next_actions",
        "meta",
    }
    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["type"] == "READONLY_VIOLATION"
    assert result["meta"]["readonly"] is True


def test_require_capability_raises(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    with pytest.raises(PermissionError):
        require_capability(Capability.SCHEMA_WRITE)
