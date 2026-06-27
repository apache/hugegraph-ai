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
Gremlin 语法分布分析工具

统计生成语料库中的 Gremlin 语法步骤、谓词分布，生成统计数据和分析报告。

用法:
    python analyze_syntax.py                          # 自动找最新语料库
    python analyze_syntax.py --input output/xxx.json  # 指定输入文件
    python analyze_syntax.py --top 30                 # 显示前30个步骤

输出:
    output/syntax_distribution_stats.json  - 统计数据
    output/SYNTAX_ANALYSIS_SUMMARY.md      - 分析报告
"""

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime
from glob import glob

# Gremlin 步骤的正则匹配模式
STEP_PATTERN = re.compile(r"\.(\w+)\s*\(")
# 起始步骤
START_PATTERN = re.compile(r"^g\.(\w+)\s*\(")
# 谓词 P.xxx(...)
PREDICATE_PATTERN = re.compile(r"P\.(\w+)\s*\(")
# 文本谓词 TextP.xxx(...)
TEXT_PREDICATE_PATTERN = re.compile(r"TextP\.(\w+)\s*\(")
# 匿名遍历 __.xxx(...)
ANONYMOUS_PATTERN = re.compile(r"__\.(\w+)\s*\(")

# 步骤分类
STEP_CATEGORIES = {
    "图遍历起始": ["V", "E"],
    "过滤步骤": [
        "hasLabel",
        "has",
        "hasId",
        "hasKey",
        "hasValue",
        "where",
        "filter",
        "is",
        "dedup",
        "simplePath",
        "cyclicPath",
        "not",
    ],
    "图导航": ["out", "in", "both", "outE", "inE", "bothE", "outV", "inV", "otherV"],
    "聚合统计": ["groupCount", "count", "sum", "mean", "max", "min", "fold", "unfold"],
    "排序限制": ["order", "limit", "range", "skip", "tail", "sample", "coin"],
    "投影转换": [
        "values",
        "valueMap",
        "elementMap",
        "properties",
        "project",
        "select",
        "label",
        "id",
        "constant",
        "identity",
    ],
    "分支条件": ["union", "coalesce", "choose", "optional"],
    "循环": ["repeat", "times", "until", "emit"],
    "路径": ["path", "tree"],
    "副作用": ["aggregate", "store", "sideEffect", "group", "cap"],
    "写操作": ["addV", "addE", "property", "drop"],
    "逻辑": ["and", "or"],
    "辅助": ["as", "by", "map", "flatMap", "barrier"],
    "终端": ["iterate", "explain", "profile", "next", "toList"],
}


def analyze_query(query: str) -> dict:
    """分析单条 Gremlin 查询，提取语法元素"""
    stats = {
        "steps": Counter(),
        "predicates": Counter(),
        "text_predicates": Counter(),
        "step_count": 0,
    }

    # 起始步骤
    start_match = START_PATTERN.search(query)
    start_step_span = None
    if start_match:
        stats["steps"][start_match.group(1)] += 1
        start_step_span = start_match.span(1)

    # 链式步骤
    for match in STEP_PATTERN.finditer(query):
        if start_step_span and match.span(1) == start_step_span:
            continue
        step_name = match.group(1)
        # 排除非步骤的方法调用（如 property 的值参数中的方法）
        if step_name not in ("get", "put", "toString"):
            stats["steps"][step_name] += 1

    # 谓词
    for match in PREDICATE_PATTERN.finditer(query):
        stats["predicates"][match.group(1)] += 1

    # 文本谓词
    for match in TEXT_PREDICATE_PATTERN.finditer(query):
        stats["text_predicates"][match.group(1)] += 1

    stats["step_count"] = sum(stats["steps"].values())
    return stats


def analyze_corpus(corpus: list) -> dict:
    """分析整个语料库"""
    total_stats = {
        "steps": Counter(),
        "predicates": Counter(),
        "text_predicates": Counter(),
        "step_counts": [],  # 每条查询的步骤数
    }

    for item in corpus:
        query = item.get("query", "")
        q_stats = analyze_query(query)
        total_stats["steps"].update(q_stats["steps"])
        total_stats["predicates"].update(q_stats["predicates"])
        total_stats["text_predicates"].update(q_stats["text_predicates"])
        total_stats["step_counts"].append(q_stats["step_count"])

    return total_stats


def compute_category_stats(steps: Counter) -> list:
    """按分类汇总步骤统计"""
    total = sum(steps.values())
    results = []
    for cat_name, step_names in STEP_CATEGORIES.items():
        count = sum(steps.get(s, 0) for s in step_names)
        if count > 0:
            results.append((cat_name, count, count / total * 100 if total else 0))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def compute_cumulative(steps: Counter) -> list:
    """计算累计占比里程碑"""
    sorted_steps = steps.most_common()
    total = sum(steps.values())
    cumulative = 0
    milestones = [50, 80, 90, 95, 99]
    milestone_idx = 0
    results = []
    for i, (name, count) in enumerate(sorted_steps, 1):
        cumulative += count
        pct = cumulative / total * 100 if total else 0
        if milestone_idx < len(milestones) and pct >= milestones[milestone_idx]:
            results.append((milestones[milestone_idx], i, name))
            milestone_idx += 1
    return results


def print_bar(name: str, count: int, max_count: int, total: int, rank: int, bar_width: int = 40):
    """打印单行条形图"""
    bar_len = int((count / max_count) * bar_width) if max_count else 0
    pct = count / total * 100 if total else 0
    print(f"  {rank:2d}. {name:<20} {'█' * bar_len} {count:>6} ({pct:5.2f}%)")


def print_results(stats: dict, total_queries: int, top_n: int = 25):
    """终端打印统计结果"""
    steps = stats["steps"]
    total_steps = sum(steps.values())
    step_counts = stats["step_counts"]

    print("\n" + "=" * 70)
    print("📊 Gremlin 语法分布统计")
    print("=" * 70)
    print(f"  总查询数:       {total_queries:,}")
    print(f"  总步骤数:       {total_steps:,}")
    print(f"  不同步骤类型:   {len(steps)}")
    if step_counts:
        avg = sum(step_counts) / len(step_counts)
        print(f"  平均步骤/查询:  {avg:.2f}")
        print(f"  最大步骤数:     {max(step_counts)}")
        print(f"  最小步骤数:     {min(step_counts)}")

    # Top 步骤
    print(f"\n{'─' * 70}")
    print(f"🏆 步骤分布 (Top {top_n})")
    print(f"{'─' * 70}")
    sorted_steps = steps.most_common(top_n)
    max_count = sorted_steps[0][1] if sorted_steps else 1
    for i, (name, count) in enumerate(sorted_steps, 1):
        print_bar(name, count, max_count, total_steps, i)

    # 谓词
    if stats["predicates"]:
        print(f"\n{'─' * 70}")
        print("🎯 谓词分布")
        print(f"{'─' * 70}")
        total_pred = sum(stats["predicates"].values())
        sorted_preds = stats["predicates"].most_common()
        max_p = sorted_preds[0][1] if sorted_preds else 1
        for i, (name, count) in enumerate(sorted_preds, 1):
            print_bar(name, count, max_p, total_pred, i)

    # 文本谓词
    if stats["text_predicates"]:
        print(f"\n{'─' * 70}")
        print("📝 文本谓词分布")
        print(f"{'─' * 70}")
        total_tp = sum(stats["text_predicates"].values())
        sorted_tp = stats["text_predicates"].most_common()
        max_tp = sorted_tp[0][1] if sorted_tp else 1
        for i, (name, count) in enumerate(sorted_tp, 1):
            print_bar(name, count, max_tp, total_tp, i)

    # 分类汇总
    print(f"\n{'─' * 70}")
    print("📂 步骤分类汇总")
    print(f"{'─' * 70}")
    print(f"  {'分类':<15} {'数量':>10} {'占比':>10}")
    print(f"  {'─' * 40}")
    for cat_name, count, pct in compute_category_stats(steps):
        print(f"  {cat_name:<15} {count:>10} {pct:>9.2f}%")

    # 累计占比
    print(f"\n{'─' * 70}")
    print("📈 累计占比")
    print(f"{'─' * 70}")
    for milestone_pct, step_count, _last_step in compute_cumulative(steps):
        print(f"  前 {step_count:2d} 个步骤覆盖 {milestone_pct}% 的使用")

    print()


def save_stats_json(stats: dict, total_queries: int, output_path: str):
    """保存统计数据到 JSON"""
    step_counts = stats["step_counts"]
    output_data = {
        "metadata": {
            "total_queries": total_queries,
            "total_steps": sum(stats["steps"].values()),
            "unique_step_types": len(stats["steps"]),
            "avg_steps_per_query": round(sum(step_counts) / len(step_counts), 2) if step_counts else 0,
            "max_steps": max(step_counts) if step_counts else 0,
            "min_steps": min(step_counts) if step_counts else 0,
            "total_predicates": sum(stats["predicates"].values()),
            "unique_predicate_types": len(stats["predicates"]),
            "total_text_predicates": sum(stats["text_predicates"].values()),
            "unique_text_predicate_types": len(stats["text_predicates"]),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "steps": dict(stats["steps"].most_common()),
        "predicates": dict(stats["predicates"].most_common()),
        "text_predicates": dict(stats["text_predicates"].most_common()),
        "step_categories": {cat: count for cat, count, _ in compute_category_stats(stats["steps"])},
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)


def generate_report(stats: dict, total_queries: int, input_file: str, report_path: str):
    """生成 Markdown 分析报告"""
    steps = stats["steps"]
    total_steps = sum(steps.values())
    step_counts = stats["step_counts"]

    lines = []
    lines.append("# Gremlin 语法分布分析报告\n")
    lines.append(f"- 数据来源: `{input_file}`")
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 概览
    lines.append("## 概览\n")
    lines.append("| 指标 | 值 |")
    lines.append("|------|---:|")
    lines.append(f"| 总查询数 | {total_queries:,} |")
    lines.append(f"| 总步骤数 | {total_steps:,} |")
    lines.append(f"| 不同步骤类型 | {len(steps)} |")
    if step_counts:
        lines.append(f"| 平均步骤/查询 | {sum(step_counts) / len(step_counts):.2f} |")
        lines.append(f"| 最大步骤数 | {max(step_counts)} |")
        lines.append(f"| 最小步骤数 | {min(step_counts)} |")
    if stats["predicates"]:
        lines.append(f"| 总谓词数 | {sum(stats['predicates'].values())} |")
    lines.append("")

    # 步骤分布
    lines.append("## 步骤分布\n")
    lines.append("| 排名 | 步骤 | 次数 | 占比 |")
    lines.append("|-----:|------|-----:|-----:|")
    for i, (name, count) in enumerate(steps.most_common(), 1):
        pct = count / total_steps * 100 if total_steps else 0
        lines.append(f"| {i} | `{name}` | {count} | {pct:.2f}% |")
    lines.append("")

    # 分类汇总
    lines.append("## 步骤分类汇总\n")
    lines.append("| 分类 | 数量 | 占比 |")
    lines.append("|------|-----:|-----:|")
    for cat_name, count, pct in compute_category_stats(steps):
        lines.append(f"| {cat_name} | {count} | {pct:.2f}% |")
    lines.append("")

    # 谓词
    if stats["predicates"]:
        lines.append("## 谓词分布\n")
        lines.append("| 谓词 | 次数 | 占比 |")
        lines.append("|------|-----:|-----:|")
        total_pred = sum(stats["predicates"].values())
        for name, count in stats["predicates"].most_common():
            pct = count / total_pred * 100 if total_pred else 0
            lines.append(f"| `P.{name}` | {count} | {pct:.2f}% |")
        lines.append("")

    if stats["text_predicates"]:
        lines.append("## 文本谓词分布\n")
        lines.append("| 文本谓词 | 次数 | 占比 |")
        lines.append("|----------|-----:|-----:|")
        total_tp = sum(stats["text_predicates"].values())
        for name, count in stats["text_predicates"].most_common():
            pct = count / total_tp * 100 if total_tp else 0
            lines.append(f"| `TextP.{name}` | {count} | {pct:.2f}% |")
        lines.append("")

    # 累计占比
    lines.append("## 累计占比\n")
    for milestone_pct, step_count, _last_step in compute_cumulative(steps):
        lines.append(f"- 前 **{step_count}** 个步骤覆盖 **{milestone_pct}%** 的使用")
    lines.append("")

    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def find_latest_corpus(output_dir: str = "output") -> str:
    """找到最新的泛化结果文件"""
    pattern = os.path.join(output_dir, "generated_corpus_*.json")
    files = sorted(glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def main():
    parser = argparse.ArgumentParser(description="Gremlin 语法分布分析")
    parser.add_argument("--input", default=None, help="语料库文件路径（不指定则自动找最新的）")
    parser.add_argument("--top", type=int, default=25, help="显示前N个步骤（默认25）")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    args = parser.parse_args()

    # 加载配置获取 output_dir
    output_dir = "output"
    if os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)
        output_dir = config.get("output_dir", "output")

    # 定位输入文件
    input_path = args.input or find_latest_corpus(output_dir)
    if not input_path or not os.path.exists(input_path):
        print("❌ 未找到语料库文件，请用 --input 指定")
        return

    # 加载语料
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    corpus = data.get("corpus", [])
    total_queries = len(corpus)

    print(f"📂 输入文件: {input_path}")
    print(f"📊 查询总数: {total_queries}")

    # 分析
    stats = analyze_corpus(corpus)

    # 终端输出
    print_results(stats, total_queries, args.top)

    # 保存 JSON
    stats_path = os.path.join(output_dir, "syntax_distribution_stats.json")
    save_stats_json(stats, total_queries, stats_path)
    print(f"💾 统计数据: {stats_path}")

    # 生成报告
    report_path = os.path.join(output_dir, "SYNTAX_ANALYSIS_SUMMARY.md")
    generate_report(stats, total_queries, input_path, report_path)
    print(f"📝 分析报告: {report_path}")


if __name__ == "__main__":
    main()
