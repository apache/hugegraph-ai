# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# ruff: noqa: E402

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from run_llm_pipeline import get_stage_extra_args


def test_unknown_extra_args_only_apply_to_first_selected_stage():
    stages = ["migrate", "merge", "dpo"]
    extra = ["--input", "pairs.json"]

    assert get_stage_extra_args("migrate", stages, extra) == extra
    assert get_stage_extra_args("merge", stages, extra) == []
    assert get_stage_extra_args("dpo", stages, extra) == []


def test_migration_args_are_routed_to_migrate_stage():
    stages = ["translate", "migrate", "merge", "dpo"]
    extra = ["--migration-mode", "same_operation", "--same-operation-sample-count=3"]

    assert get_stage_extra_args("translate", stages, extra) == []
    assert get_stage_extra_args("migrate", stages, extra) == extra
    assert get_stage_extra_args("merge", stages, extra) == []
    assert get_stage_extra_args("dpo", stages, extra) == []


def test_translated_arg_routes_to_first_selected_consumer():
    extra = ["--translated", "output/llm_translated.json"]

    stages_with_migrate = ["translate", "migrate", "merge", "dpo"]
    assert get_stage_extra_args("translate", stages_with_migrate, extra) == []
    assert get_stage_extra_args("migrate", stages_with_migrate, extra) == extra
    assert get_stage_extra_args("merge", stages_with_migrate, extra) == []
    assert get_stage_extra_args("dpo", stages_with_migrate, extra) == []

    stages_from_merge = ["merge", "dpo"]
    assert get_stage_extra_args("merge", stages_from_merge, extra) == extra
    assert get_stage_extra_args("dpo", stages_from_merge, extra) == []


def test_migrated_arg_routes_to_first_selected_consumer():
    extra = ["--migrated", "output/migrated.json"]

    stages_with_merge = ["translate", "migrate", "merge", "dpo"]
    assert get_stage_extra_args("translate", stages_with_merge, extra) == []
    assert get_stage_extra_args("migrate", stages_with_merge, extra) == []
    assert get_stage_extra_args("merge", stages_with_merge, extra) == extra
    assert get_stage_extra_args("dpo", stages_with_merge, extra) == []

    stages_from_dpo = ["dpo"]
    assert get_stage_extra_args("dpo", stages_from_dpo, extra) == extra


def test_inline_file_args_route_to_first_selected_consumer():
    stages = ["translate", "migrate", "merge", "dpo"]
    translated = ["--translated=output/llm_translated.json"]
    migrated = ["--migrated=output/migrated.json"]

    assert get_stage_extra_args("translate", stages, translated) == []
    assert get_stage_extra_args("migrate", stages, translated) == translated
    assert get_stage_extra_args("merge", stages, translated) == []
    assert get_stage_extra_args("dpo", stages, translated) == []

    assert get_stage_extra_args("translate", stages, migrated) == []
    assert get_stage_extra_args("migrate", stages, migrated) == []
    assert get_stage_extra_args("merge", stages, migrated) == migrated
    assert get_stage_extra_args("dpo", stages, migrated) == []


def test_dpo_only_args_route_to_dpo_stage():
    stages = ["translate", "migrate", "merge", "dpo"]
    extra = [
        "--num-a",
        "1",
        "--num-b=2",
        "--num-c",
        "3",
        "--migrated-num-a",
        "4",
        "--migrated-num-b=5",
        "--migrated-num-c",
        "6",
        "--skip-movie",
        "--skip-migrated",
    ]

    assert get_stage_extra_args("translate", stages, extra) == []
    assert get_stage_extra_args("migrate", stages, extra) == []
    assert get_stage_extra_args("merge", stages, extra) == []
    assert get_stage_extra_args("dpo", stages, extra) == extra


def test_dpo_skip_flags_do_not_consume_following_unknown_value():
    stages = ["translate", "migrate", "merge", "dpo"]
    extra = ["--skip-movie", "orphan", "--num-a", "1"]

    assert get_stage_extra_args("translate", stages, extra) == ["orphan"]
    assert get_stage_extra_args("migrate", stages, extra) == []
    assert get_stage_extra_args("merge", stages, extra) == []
    assert get_stage_extra_args("dpo", stages, extra) == ["--skip-movie", "--num-a", "1"]


def test_dpo_skip_flags_do_not_consume_following_option():
    stages = ["translate", "migrate", "merge", "dpo"]
    extra = ["--skip-migrated", "--num-b", "2"]

    assert get_stage_extra_args("translate", stages, extra) == []
    assert get_stage_extra_args("migrate", stages, extra) == []
    assert get_stage_extra_args("merge", stages, extra) == []
    assert get_stage_extra_args("dpo", stages, extra) == extra


def test_output_dir_routes_to_merge_when_merge_stage_is_selected():
    extra = ["--output-dir", "custom-output"]

    stages_with_merge = ["translate", "migrate", "merge", "dpo"]
    assert get_stage_extra_args("translate", stages_with_merge, extra) == []
    assert get_stage_extra_args("migrate", stages_with_merge, extra) == []
    assert get_stage_extra_args("merge", stages_with_merge, extra) == extra
    assert get_stage_extra_args("dpo", stages_with_merge, extra) == []

    translate_only = ["translate"]
    assert get_stage_extra_args("translate", translate_only, extra) == extra
