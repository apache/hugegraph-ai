# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

import pytest
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.plan_store import (
    PlanStore,
    PlanStoreUnavailableError,
    SQLitePlanStore,
    plan_store_from_config,
)


def test_sqlite_plan_store_implements_runtime_protocol(tmp_path):
    store = SQLitePlanStore(tmp_path)

    assert isinstance(store, PlanStore)


def test_plan_store_factory_uses_configured_state_dir(tmp_path):
    cfg = MCPConfig(state_dir=tmp_path)

    store = plan_store_from_config(cfg)

    assert isinstance(store, SQLitePlanStore)
    assert store.state_dir == tmp_path


def test_unknown_plan_store_backend_fails_closed(tmp_path):
    cfg = MCPConfig(state_dir=tmp_path, plan_store_backend="unknown")

    with pytest.raises(PlanStoreUnavailableError):
        plan_store_from_config(cfg)


def test_multiple_write_instances_with_sqlite_are_blocked(tmp_path):
    cfg = MCPConfig(
        state_dir=tmp_path,
        readonly=False,
        plan_store_backend="sqlite",
        write_instance_count=2,
    )

    result = guard(Capability.DATA_WRITE, cfg=cfg)

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert result["error"]["details"]["plan_store_backend"] == "sqlite"
    assert result["error"]["details"]["write_instance_count"] == 2


def test_multiple_write_instances_do_not_block_reads(tmp_path):
    cfg = MCPConfig(
        state_dir=tmp_path,
        readonly=False,
        plan_store_backend="sqlite",
        write_instance_count=2,
    )

    assert guard(Capability.READ, cfg=cfg) is None
