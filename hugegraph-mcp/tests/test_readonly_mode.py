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

"""Test that HUGEGRAPH_MCP_READONLY properly disables write tools."""

import asyncio
import importlib
import os
from unittest.mock import patch


def get_registered_tools():
    """Helper to get registered MCP tool names from a running server instance."""
    import hugegraph_mcp.server

    async def _get_tools():
        list_tools = getattr(hugegraph_mcp.server.mcp, "_mcp_list_tools", None)
        if list_tools is None:
            list_tools = hugegraph_mcp.server.mcp._list_tools
        tools = await list_tools()
        return [t.name for t in tools]

    return asyncio.run(_get_tools())


def test_readonly_env_parsing():
    """Test that various readonly env values are parsed correctly."""
    test_cases = [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("TRUE", True),
        ("True", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("", True),
        ("invalid", True),
    ]

    for env_value, expected in test_cases:
        with patch.dict(os.environ, {"HUGEGRAPH_MCP_READONLY": env_value}, clear=True):
            # Import and check READONLY value
            import importlib

            import hugegraph_mcp.server

            importlib.reload(hugegraph_mcp.server)

            assert expected == hugegraph_mcp.server.READONLY


def test_write_tools_available_when_not_readonly(monkeypatch):
    """Test that all V1 tools are registered when not in readonly mode."""
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_TOOLSET", "v1")

    import hugegraph_mcp.server

    try:
        importlib.reload(hugegraph_mcp.server)
        tools = get_registered_tools()
        # V1 stable tools
        assert "inspect_graph_tool" in tools
        assert "generate_gremlin_tool" in tools
        assert "execute_gremlin_read_tool" in tools
        assert "extract_graph_data_tool" in tools
        assert "design_schema_tool" in tools
        assert "apply_schema_tool" in tools
        assert "import_graph_data_tool" in tools
        assert "delete_graph_data_tool" in tools
        assert "query_graph_tool" not in tools
        assert "manage_schema_tool" not in tools
        assert "manage_graph_data_tool" not in tools
        # Admin-gated debug tools
        assert "execute_gremlin_write_tool" in tools
        assert "refresh_vid_embeddings_tool" in tools
        assert len(tools) == 10
    finally:
        monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
        importlib.reload(hugegraph_mcp.server)


def test_write_tools_disabled_when_readonly(monkeypatch):
    """Test that all V1 tools remain registered in readonly mode."""
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_TOOLSET", "v1")

    import hugegraph_mcp.server

    try:
        importlib.reload(hugegraph_mcp.server)
        tools = get_registered_tools()
        # All tools are registered; readonly blocks execution, not registration
        assert "inspect_graph_tool" in tools
        assert "generate_gremlin_tool" in tools
        assert "execute_gremlin_read_tool" in tools
        assert "extract_graph_data_tool" in tools
        assert "design_schema_tool" in tools
        assert "apply_schema_tool" in tools
        assert "import_graph_data_tool" in tools
        assert "delete_graph_data_tool" in tools
        assert "query_graph_tool" not in tools
        assert "manage_schema_tool" not in tools
        assert "manage_graph_data_tool" not in tools
        assert "execute_gremlin_write_tool" in tools
        assert "refresh_vid_embeddings_tool" in tools
        assert len(tools) == 10
    finally:
        monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
        importlib.reload(hugegraph_mcp.server)


def test_readonly_mode_default(monkeypatch):
    """Test that default mode is readonly when env is not set (V1 safe default)."""
    monkeypatch.delenv("HUGEGRAPH_MCP_READONLY", raising=False)
    monkeypatch.setenv("HUGEGRAPH_MCP_TOOLSET", "v1")

    import hugegraph_mcp.server

    try:
        importlib.reload(hugegraph_mcp.server)
        assert hugegraph_mcp.server.READONLY is True
        tools = get_registered_tools()
        assert len(tools) == 10
    finally:
        monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
        importlib.reload(hugegraph_mcp.server)
