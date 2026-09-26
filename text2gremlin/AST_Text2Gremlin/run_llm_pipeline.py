#!/usr/bin/env python3
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

"""
LLM 增强数据生成流水线统一入口

按顺序执行 4 个阶段（可通过 --stage 指定从某阶段开始）：
  1. translate  — 多风格自然语言翻译 (generalize_llm)
  2. migrate    — 多场景迁移 (migrate_scenario)
  3. merge      — 数据集合并与统计 (merge_dataset)
  4. dpo        — DPO 偏好数据生成 (generate_dpo_data)

用法:
    # 从头执行全部阶段
    python run_llm_pipeline.py

    # 从第 2 阶段开始（跳过翻译）
    python run_llm_pipeline.py --stage migrate

    # 只执行合并
    python run_llm_pipeline.py --stage merge --stop merge

    # 各阶段也可独立运行
    python -m llm_augment.generalize_llm --help
    python -m llm_augment.migrate_scenario --help
    python -m llm_augment.merge_dataset --help
    python -m llm_augment.generate_dpo_data --help
"""

import argparse
import subprocess
import sys

STAGES = ["translate", "migrate", "merge", "dpo"]

STAGE_MODULES = {
    "translate": "llm_augment.generalize_llm",
    "migrate": "llm_augment.migrate_scenario",
    "merge": "llm_augment.merge_dataset",
    "dpo": "llm_augment.generate_dpo_data",
}

STAGE_NAMES = {
    "translate": "多风格翻译",
    "migrate": "场景迁移",
    "merge": "数据集合并",
    "dpo": "DPO 偏好数据",
}

STAGE_OPTION_CANDIDATES = {
    "--translated": ("migrate", "merge"),
    "--migrated": ("merge", "dpo"),
    "--migration-mode": ("migrate",),
    "--same-operation-sample-count": ("migrate",),
    "--output-dir": ("merge",),
    "--num-a": ("dpo",),
    "--num-b": ("dpo",),
    "--num-c": ("dpo",),
    "--migrated-num-a": ("dpo",),
    "--migrated-num-b": ("dpo",),
    "--migrated-num-c": ("dpo",),
    "--skip-movie": ("dpo",),
    "--skip-migrated": ("dpo",),
}

VALUE_TAKING_OPTIONS = {
    "--translated",
    "--migrated",
    "--migration-mode",
    "--same-operation-sample-count",
    "--output-dir",
    "--num-a",
    "--num-b",
    "--num-c",
    "--migrated-num-a",
    "--migrated-num-b",
    "--migrated-num-c",
}


def run_stage(stage: str, extra_args: list[str]) -> int:
    """运行单个阶段，返回 exit code"""
    module = STAGE_MODULES[stage]
    name = STAGE_NAMES[stage]
    print(f"\n{'=' * 60}")
    print(f"▶ 阶段: {name} ({module})")
    print(f"{'=' * 60}\n")

    cmd = [sys.executable, "-m", module, *extra_args]
    # Keep child stdout/stderr attached so stage logs stream in order.
    result = subprocess.run(cmd, check=False)
    return result.returncode


def _resolve_option_owner(option: str, stages_to_run: list[str]) -> str | None:
    """Return the earliest selected stage that can consume option."""
    candidates = STAGE_OPTION_CANDIDATES.get(option, ())
    for selected_stage in stages_to_run:
        if selected_stage in candidates:
            return selected_stage
    return None


def get_stage_extra_args(stage: str, stages_to_run: list[str], extra_args: list[str]) -> list[str]:
    """Route known stage-specific args and keep unknown args on the first stage."""
    stage_args = {selected_stage: [] for selected_stage in stages_to_run}
    first_stage_args = stage_args[stages_to_run[0]]
    index = 0
    while index < len(extra_args):
        arg = extra_args[index]
        option = arg.split("=", 1)[0]
        owner = _resolve_option_owner(option, stages_to_run)
        target = stage_args.get(owner) if owner else first_stage_args
        if target is None:
            target = first_stage_args
        target.append(arg)

        has_inline_value = "=" in arg
        has_separate_value = index + 1 < len(extra_args) and not extra_args[index + 1].startswith("--")
        if owner and option in VALUE_TAKING_OPTIONS and not has_inline_value and has_separate_value:
            index += 1
            target.append(extra_args[index])
        index += 1

    return stage_args[stage]


def main():
    parser = argparse.ArgumentParser(
        description="LLM 增强数据生成流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
阶段说明:
  translate  多风格自然语言翻译（generalize_llm）
  migrate    多场景迁移（migrate_scenario）
  merge      数据集合并与统计（merge_dataset）
  dpo        DPO 偏好数据生成（generate_dpo_data）

示例:
  python run_llm_pipeline.py                    # 全部阶段
  python run_llm_pipeline.py --stage migrate    # 从迁移开始
  python run_llm_pipeline.py --stage merge --stop merge  # 只合并
        """,
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        default="translate",
        help="从哪个阶段开始（默认: translate）",
    )
    parser.add_argument(
        "--stop",
        choices=STAGES,
        default=None,
        help="在哪个阶段停止（含该阶段，默认: 执行到最后）",
    )

    args, extra = parser.parse_known_args()

    start_idx = STAGES.index(args.stage)
    stop_idx = STAGES.index(args.stop) if args.stop else len(STAGES) - 1

    if start_idx > stop_idx:
        print(f"❌ --stage ({args.stage}) 不能在 --stop ({args.stop}) 之后")
        sys.exit(1)

    stages_to_run = STAGES[start_idx : stop_idx + 1]

    print("=" * 60)
    print("🚀 LLM 增强数据生成流水线")
    print("=" * 60)
    print(f"  执行阶段: {' → '.join(stages_to_run)}")
    if extra:
        print(f"  额外参数: {extra}")

    for stage in stages_to_run:
        rc = run_stage(stage, get_stage_extra_args(stage, stages_to_run, extra))
        if rc != 0:
            print(f"\n❌ 阶段 {stage} 失败 (exit code: {rc})，流水线中止")
            sys.exit(rc)

    print(f"\n{'=' * 60}")
    print("✅ 流水线全部完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
