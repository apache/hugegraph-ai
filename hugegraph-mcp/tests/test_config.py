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

import logging
from dataclasses import FrozenInstanceError

import hugegraph_mcp.config as config_module
import pytest
from hugegraph_mcp.config import MCPConfig, config

CONFIG_ENV_VARS = (
    "HUGEGRAPH_URL",
    "HUGEGRAPH_GRAPH_PATH",
    "HUGEGRAPH_GRAPH",
    "HUGEGRAPH_GRAPHSPACE",
    "HUGEGRAPH_USER",
    "HUGEGRAPH_PASSWORD",
    "HUGEGRAPH_MCP_READONLY",
    "HUGEGRAPH_AI_URL",
    "HUGEGRAPH_AI_TOKEN",
    "HUGEGRAPH_AI_GRAPH_URL",
    "HUGEGRAPH_MCP_ALLOW_AI",
    "HUGEGRAPH_MCP_ADMIN_MODE",
    "HUGEGRAPH_MCP_TIMEOUT_SECONDS",
    "HUGEGRAPH_AI_TIMEOUT_SECONDS",
    "HUGEGRAPH_CONNECT_TIMEOUT_SECONDS",
    "HUGEGRAPH_READ_TIMEOUT_SECONDS",
    "HUGEGRAPH_WRITE_TIMEOUT_SECONDS",
    "HUGEGRAPH_MCP_MAX_RESULT_ITEMS",
    "HUGEGRAPH_MCP_MAX_RESULT_BYTES",
    "HUGEGRAPH_MCP_STATE_DIR",
    "XDG_STATE_HOME",
)


def clear_config_env(monkeypatch):
    for name in CONFIG_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_basic_config_parsing(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_URL", "http://graph.example:18080")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "space_a")
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "graph_a")
    monkeypatch.setenv("HUGEGRAPH_USER", "alice")
    monkeypatch.setenv("HUGEGRAPH_PASSWORD", "secret")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    monkeypatch.setenv("HUGEGRAPH_AI_URL", "http://ai.example:18001")
    monkeypatch.setenv("HUGEGRAPH_AI_TOKEN", "ai-token")
    monkeypatch.setenv("HUGEGRAPH_AI_GRAPH_URL", "http://graph-internal:8080")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "yes")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("HUGEGRAPH_READ_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "40")
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "25")
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "2048")

    cfg = MCPConfig.from_env()

    assert cfg.url == "http://graph.example:18080"
    assert cfg.graphspace == "space_a"
    assert cfg.graph == "graph_a"
    assert cfg.user == "alice"
    assert cfg.password == "secret"
    assert cfg.is_readonly() is True
    assert cfg.ai_url == "http://ai.example:18001"
    assert cfg.ai_token == "ai-token"
    assert cfg.ai_graph_url == "http://graph-internal:8080"
    assert cfg.allow_ai is True
    assert cfg.admin_mode is True
    assert cfg.timeout_seconds == 45
    assert cfg.connect_timeout_seconds == 1.5
    assert cfg.read_timeout_seconds == 20.0
    assert cfg.write_timeout_seconds == 40.0
    assert cfg.max_result_items == 25
    assert cfg.max_result_bytes == 2048


def test_explicit_ai_timeout_takes_priority_over_legacy_name(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("HUGEGRAPH_AI_TIMEOUT_SECONDS", "12")

    assert MCPConfig.from_env().timeout_seconds == 12


def test_invalid_graph_timeouts_fall_back_to_safe_defaults(monkeypatch, caplog):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "zero")
    monkeypatch.setenv("HUGEGRAPH_READ_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "-1")

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        cfg = MCPConfig.from_env()

    assert cfg.connect_timeout_seconds == 0.5
    assert cfg.read_timeout_seconds == 15.0
    assert cfg.write_timeout_seconds == 15.0
    assert len(caplog.messages) == 3


def test_non_finite_graph_timeouts_fall_back_to_safe_defaults(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_READ_TIMEOUT_SECONDS", "nan")
    monkeypatch.setenv("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "inf")

    cfg = MCPConfig.from_env()

    assert cfg.read_timeout_seconds == 15.0
    assert cfg.write_timeout_seconds == 15.0


@pytest.mark.parametrize(
    ("env_name", "invalid_value", "field_name", "default"),
    [
        ("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "", "connect_timeout_seconds", 0.5),
        ("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "-0.1", "connect_timeout_seconds", 0.5),
        ("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "nan", "connect_timeout_seconds", 0.5),
        ("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "inf", "connect_timeout_seconds", 0.5),
        ("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "86401", "connect_timeout_seconds", 0.5),
        ("HUGEGRAPH_READ_TIMEOUT_SECONDS", "-1", "read_timeout_seconds", 15.0),
        ("HUGEGRAPH_READ_TIMEOUT_SECONDS", "-inf", "read_timeout_seconds", 15.0),
        ("HUGEGRAPH_READ_TIMEOUT_SECONDS", "86401", "read_timeout_seconds", 15.0),
        ("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "-1", "write_timeout_seconds", 15.0),
        ("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "nan", "write_timeout_seconds", 15.0),
        ("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "86401", "write_timeout_seconds", 15.0),
        ("HUGEGRAPH_AI_TIMEOUT_SECONDS", "-1", "timeout_seconds", 30),
        ("HUGEGRAPH_AI_TIMEOUT_SECONDS", "nan", "timeout_seconds", 30),
        ("HUGEGRAPH_AI_TIMEOUT_SECONDS", "inf", "timeout_seconds", 30),
        ("HUGEGRAPH_AI_TIMEOUT_SECONDS", "86401", "timeout_seconds", 30),
        ("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "-1", "max_result_items", 100),
        ("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "nan", "max_result_items", 100),
        ("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "1000001", "max_result_items", 100),
        ("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "-1", "max_result_bytes", 1_048_576),
        ("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "inf", "max_result_bytes", 1_048_576),
        ("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "1073741825", "max_result_bytes", 1_048_576),
    ],
)
def test_numeric_config_rejects_values_outside_field_bounds(
    monkeypatch,
    env_name,
    invalid_value,
    field_name,
    default,
):
    clear_config_env(monkeypatch)
    monkeypatch.setenv(env_name, invalid_value)

    cfg = MCPConfig.from_env()

    assert getattr(cfg, field_name) == default


@pytest.mark.parametrize(
    ("env_name", "field_name", "default"),
    [
        ("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "connect_timeout_seconds", 0.5),
        ("HUGEGRAPH_READ_TIMEOUT_SECONDS", "read_timeout_seconds", 15.0),
        ("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "write_timeout_seconds", 15.0),
        ("HUGEGRAPH_AI_TIMEOUT_SECONDS", "timeout_seconds", 30),
        ("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "max_result_items", 100),
        ("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "max_result_bytes", 1_048_576),
    ],
)
def test_arbitrarily_large_numeric_config_never_raises(
    monkeypatch,
    env_name,
    field_name,
    default,
):
    clear_config_env(monkeypatch)
    monkeypatch.setenv(env_name, "1" + ("0" * 1000))

    cfg = MCPConfig.from_env()

    assert getattr(cfg, field_name) == default


def test_numeric_config_accepts_declared_upper_bounds(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "86400")
    monkeypatch.setenv("HUGEGRAPH_READ_TIMEOUT_SECONDS", "86400")
    monkeypatch.setenv("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "86400")
    monkeypatch.setenv("HUGEGRAPH_AI_TIMEOUT_SECONDS", "86400")
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "1000000")
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "1073741824")

    cfg = MCPConfig.from_env()

    assert cfg.connect_timeout_seconds == 86400.0
    assert cfg.read_timeout_seconds == 86400.0
    assert cfg.write_timeout_seconds == 86400.0
    assert cfg.timeout_seconds == 86400
    assert cfg.max_result_items == 1_000_000
    assert cfg.max_result_bytes == 1_073_741_824


def test_numeric_config_accepts_declared_lower_bounds(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setenv("HUGEGRAPH_READ_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setenv("HUGEGRAPH_WRITE_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setenv("HUGEGRAPH_AI_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "1")
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "1")

    cfg = MCPConfig.from_env()

    assert cfg.connect_timeout_seconds == 0.001
    assert cfg.read_timeout_seconds == 0.001
    assert cfg.write_timeout_seconds == 0.001
    assert cfg.timeout_seconds == 1
    assert cfg.max_result_items == 1
    assert cfg.max_result_bytes == 1


def test_graph_path_parsing(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "myspace/mygraph")

    cfg = MCPConfig.from_env()

    assert cfg.graphspace == "myspace"
    assert cfg.graph == "mygraph"


def test_split_graph_variables_take_priority(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "path_space/path_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "split_space")
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "split_graph")

    cfg = MCPConfig.from_env()

    assert cfg.graphspace == "split_space"
    assert cfg.graph == "split_graph"
    assert cfg.warnings == ("HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH",)


def test_warnings_are_logged(monkeypatch, caplog):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "path_space/path_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "split_space")

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        cfg = MCPConfig.from_env()

    assert cfg.warnings == ("HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH",)
    assert "HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH" in caplog.messages


def test_duplicate_config_warnings_are_not_logged_for_unchanged_env(monkeypatch, caplog):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "cache_space/cache_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "cache_override")

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        first = MCPConfig.from_env()
        second = MCPConfig.from_env()

    assert first is second
    assert caplog.messages.count("HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH") == 1


def test_invalid_integer_config_falls_back_to_default(monkeypatch, caplog):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_TIMEOUT_SECONDS", "not-a-number")

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        cfg = MCPConfig.from_env()

    assert cfg.timeout_seconds == 30
    assert cfg.connect_timeout_seconds == 0.5
    assert cfg.read_timeout_seconds == 15.0
    assert cfg.write_timeout_seconds == 15.0
    assert cfg.max_result_items == 100
    assert cfg.max_result_bytes == 1_048_576
    assert "Invalid integer config value 'not-a-number'; using default 30" in caplog.messages


def test_non_positive_integer_config_falls_back_to_default(monkeypatch, caplog):
    for value in ("0", "-1"):
        clear_config_env(monkeypatch)
        monkeypatch.setenv("HUGEGRAPH_MCP_TIMEOUT_SECONDS", value)
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
            cfg = MCPConfig.from_env()

        assert cfg.timeout_seconds == 30
        assert f"Invalid integer config value '{value}'; using default 30" in caplog.messages


def test_readonly_and_allow_ai_are_controlled_independently(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "true")

    cfg = MCPConfig.from_env()

    assert cfg.is_readonly() is True
    assert cfg.allow_ai is True


def test_admin_mode_reads_current_env(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")
    assert MCPConfig.from_env().admin_mode is False

    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    assert MCPConfig.from_env().admin_mode is True


def test_strict_boolean_parsing(monkeypatch):
    true_values = ("true", "1", "yes", "on", "TRUE", " On ")
    false_values = ("false", "0", "no", "off", "FALSE", " Off ")

    for value in true_values:
        clear_config_env(monkeypatch)
        monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", value)
        assert MCPConfig.from_env().is_readonly() is True

    for value in false_values:
        clear_config_env(monkeypatch)
        monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", value)
        assert MCPConfig.from_env().is_readonly() is False


def test_invalid_boolean_values_fail_closed_without_leaking_value(monkeypatch, caplog):
    clear_config_env(monkeypatch)
    secret_like_value = "treu-secret-token"
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", secret_like_value)
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "junk")

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        cfg = MCPConfig.from_env()

    assert cfg.readonly is True
    assert cfg.allow_ai is False
    assert cfg.admin_mode is False
    assert secret_like_value not in caplog.text
    assert "HUGEGRAPH_MCP_READONLY" in caplog.text
    assert "HUGEGRAPH_MCP_ALLOW_AI" in caplog.text
    assert "HUGEGRAPH_MCP_ADMIN_MODE" in caplog.text


def test_unset_boolean_values_use_defaults_without_warning(monkeypatch, caplog):
    clear_config_env(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        cfg = MCPConfig.from_env()

    assert cfg.readonly is True
    assert cfg.allow_ai is False
    assert cfg.admin_mode is False
    assert "HUGEGRAPH_MCP_READONLY" not in caplog.text
    assert "HUGEGRAPH_MCP_ALLOW_AI" not in caplog.text
    assert "HUGEGRAPH_MCP_ADMIN_MODE" not in caplog.text


def test_state_dir_priority_and_defaults(monkeypatch, tmp_path):
    clear_config_env(monkeypatch)
    explicit = tmp_path / "explicit-state"
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(explicit))
    assert MCPConfig.from_env().state_dir == explicit

    monkeypatch.delenv("HUGEGRAPH_MCP_STATE_DIR")
    xdg = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg))
    assert MCPConfig.from_env().state_dir == xdg / "hugegraph-mcp"


def test_default_password_is_empty_but_explicit_xxx_is_accepted(monkeypatch):
    clear_config_env(monkeypatch)
    assert MCPConfig.from_env().password == ""

    monkeypatch.setenv("HUGEGRAPH_PASSWORD", "xxx")
    assert MCPConfig.from_env().password == "xxx"


def test_default_values(monkeypatch):
    clear_config_env(monkeypatch)

    cfg = MCPConfig.from_env()

    assert cfg.url == "http://127.0.0.1:8080"
    assert cfg.graphspace == "DEFAULT"
    assert cfg.graph == "hugegraph"
    assert cfg.user == "admin"
    assert cfg.password == ""
    assert cfg.is_readonly() is True
    assert cfg.ai_url == "http://127.0.0.1:8001"
    assert cfg.ai_token is None
    assert cfg.ai_graph_url is None
    assert cfg.allow_ai is False
    assert cfg.admin_mode is False
    assert cfg.timeout_seconds == 30
    assert cfg.warnings == ()


def test_config_proxy_reads_current_env(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "first_graph")
    assert config.graph == "first_graph"

    monkeypatch.setenv("HUGEGRAPH_GRAPH", "second_graph")
    assert config.graph == "second_graph"


def test_cached_config_is_immutable(monkeypatch):
    clear_config_env(monkeypatch)
    cached = MCPConfig.from_env()

    with pytest.raises(FrozenInstanceError):
        cached.graph = "mutated"

    assert MCPConfig.from_env().graph == "hugegraph"


def test_cached_config_uses_same_environment_snapshot_for_key_and_value(monkeypatch):
    class ChangingEnvironment(dict):
        readonly_reads = 0

        def get(self, key, default=None):
            if key == "HUGEGRAPH_MCP_READONLY":
                self.readonly_reads += 1
                return "false" if self.readonly_reads == 1 else "true"
            return super().get(key, default)

    environment = ChangingEnvironment(HUGEGRAPH_URL="http://snapshot.example:8080")
    monkeypatch.setattr(config_module.os, "environ", environment)

    cfg = MCPConfig.from_env()

    assert environment.readonly_reads == 1
    assert cfg.readonly is False
