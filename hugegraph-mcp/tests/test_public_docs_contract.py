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

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"
README_ZH = PROJECT_ROOT / "README.zh-CN.md"
CHECKLIST = PROJECT_ROOT / "docs" / "p0a-integration-checklist.md"
PUBLIC_DOCS = (README, README_ZH, CHECKLIST)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(content: str, heading: str, *, next_level: int) -> str:
    start = content.index(heading)
    remainder = content[start + len(heading) :]
    match = re.search(rf"^{'#' * next_level} (?!#)", remainder, flags=re.MULTILINE)
    return remainder if match is None else remainder[: match.start()]


def test_public_docs_describe_canonical_plan_lifecycle_as_id_only():
    english = _section(_text(README), "## Write Safety Contract", next_level=2)
    chinese = _section(_text(README_ZH), "## 写入安全合同", next_level=2)
    checklist = _section(_text(CHECKLIST), "## 3. Create Schema One Object Per Plan", next_level=2)

    assert "The confirmation call never accepts the original payload" in english
    assert "confirm_write_tool(plan_id)" in english
    assert "get_write_status_tool(plan_id)" in english
    assert "确认调用不接收原始 payload" in chinese
    assert "confirm_write_tool(plan_id)" in chinese
    assert "get_write_status_tool(plan_id)" in chinese
    assert '"arguments": {"plan_id": "<PLAN_ID>"}' in checklist
    assert 'Require `data.status="APPLIED"`' in checklist


def test_import_contract_is_preview_only_in_every_public_document():
    english = _text(README)
    chinese = _text(README_ZH)
    checklist = _section(_text(CHECKLIST), "## 4. Verify Import Is Preview-Only", next_level=2)

    assert re.search(
        r"`import_graph_data_tool`.*preview.*confirmation currently returns `FEATURE_DISABLED`",
        english,
    )
    assert (
        "Its preview sets `confirmable=false` and `preview_only=true`, issues no "
        "`plan_id`, and confirmation returns `FEATURE_DISABLED` without writing."
    ) in english
    assert re.search(
        r"`import_graph_data_tool`.*预览.*确认当前返回 `FEATURE_DISABLED`",
        chinese,
    )
    assert (
        "预览返回 `confirmable=false`、`preview_only=true`，不签发 `plan_id`；确认返回 `FEATURE_DISABLED` 且不写入。"
    ) in chinese

    assert "`data.confirmable=false`" in checklist
    assert "`data.preview_only=true`" in checklist
    assert "no\n`data.plan_id`" in checklist
    assert '`error.type="FEATURE_DISABLED"`' in checklist
    assert "neither vertex nor\nedge was created" in checklist
    assert "Do not call `confirm_write_tool` for an import preview" in checklist
    assert 'data.status="ISSUED"' not in checklist
    assert 'data.status="APPLIED"' not in checklist
    assert "confirm_write_tool(plan_id)" not in checklist


def test_checklist_pass_criteria_do_not_claim_import_writes():
    criteria = _section(_text(CHECKLIST), "## Pass Criteria", next_level=2)

    assert (
        "Vertex/edge import remains preview-only, issues no `plan_id`, returns "
        "`FEATURE_DISABLED` on confirmation, and creates no graph elements."
    ) in criteria
    assert "Vertex/edge import reaches `APPLIED`" not in criteria


def test_source_launch_contract_binds_both_checkout_packages():
    english = _section(_text(README), "## Developer Notes", next_level=2)
    chinese = _section(_text(README_ZH), "## 开发者说明", next_level=2)
    checklist = _section(_text(CHECKLIST), "## 1. Start an Isolated Server", next_level=2)

    for section in (english, chinese, checklist):
        assert "/hugegraph-mcp:/Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-python-client/src" in section
        assert ("/Users/uleng/Code/hugegraph-ai-pr73-mcp/.venv/bin/python -m hugegraph_mcp.server") in section
        assert "uv run --project hugegraph-mcp hugegraph-mcp" not in section

    assert "uv run --project .../hugegraph-mcp" in checklist
    assert "Do not replace it with" in checklist


def test_public_docs_fail_closed_for_other_unproved_write_boundaries():
    english = _text(README)
    chinese = _text(README_ZH)
    checklist = _text(CHECKLIST)

    assert "Property mutation is preview-only" in english
    assert "Isolated vertex deletion is preview-only" in english
    assert "属性变更仅支持预览" in chinese
    assert "孤立点删除仅支持预览" in chinese
    assert "data.preview_only=true" in checklist
    assert "Each call below must return `FEATURE_DISABLED`" in checklist


def test_public_docs_keep_legacy_locator_all_or_nothing():
    expected = ("plan_hash", "nonce", "expires_at")
    for path in PUBLIC_DOCS:
        content = _text(path)
        assert all(field in content for field in expected), path
        assert "LEGACY_CONFIRMATION_DEPRECATED" in content, path

    checklist = _text(CHECKLIST)
    assert "only when all three are supplied together" in checklist
    assert "A partial legacy locator must return `VALIDATION_ERROR`" in checklist
