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
数据集合并脚本

从 llm_translated 和 migrated 文件中提取所有 text2gremlin 数据对，
合并为统一数据集，并统计 CRUD 分布。

用法:
    python -m llm_augment.merge_dataset
    python -m llm_augment.merge_dataset --translated output/llm_translated_xxx.json --migrated output/migrated_xxx.json
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from glob import glob


def find_latest_translated(output_dir: str = "output") -> str | None:
    pattern = os.path.join(output_dir, "llm_translated_*.json")
    files = sorted(glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def find_latest_migrated(output_dir: str = "output") -> str | None:
    pattern = os.path.join(output_dir, "migrated_*.json")
    files = sorted(glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def load_from_translated(path: str) -> list[dict]:
    """从 llm_translated 文件提取数据对。
    每条 gremlin 对应多种语气翻译，展开为多条。
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    corpus = data.get("corpus", [])
    pairs = []
    for item in corpus:
        if "_error" in item:
            continue
        query = item.get("query", "")
        if not query:
            continue
        translations = item.get("translations", [])
        for t in translations:
            text = t.get("text", "")
            style = t.get("style", "unknown")
            if text:
                pairs.append(
                    {
                        "text": text,
                        "gremlin": query,
                        "source": "llm_translated",
                        "language_style": style,
                        "domain": "movie",
                        "source_metadata": item.get("metadata", {}),
                    }
                )
    return pairs


def load_from_migrated(path: str) -> list[dict]:
    """从 migrated 文件提取所有场景迁移后的数据对。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    migrations = data.get("migrations", [])
    pairs = []
    for m in migrations:
        domain = m.get("target_domain", "unknown")
        source_metadata = m.get("source_metadata", {})
        for sample in m.get("generated_samples", []):
            query = sample.get("query", "")
            nl = sample.get("natural_language", "")
            if query and nl:
                pairs.append(
                    {
                        "text": nl,
                        "gremlin": query,
                        "source": "migrated",
                        "language_style": sample.get("language_style", "unknown"),
                        "domain": domain,
                        "operation": sample.get("operation", "unknown"),
                        "source_metadata": source_metadata,
                    }
                )
    return pairs


def guess_operation(gremlin: str) -> str:
    """基于简单规则猜测 CRUD 类型。"""
    has_add = bool(re.search(r"\.(addV|addE)\s*\(", gremlin))
    has_drop = bool(re.search(r"\.drop\s*\(", gremlin))
    has_property = bool(re.search(r"\.property\s*\(", gremlin))

    if has_add:
        return "create"
    if has_drop:
        return "delete"
    if has_property and not has_add:
        return "update"
    return "read"


def compute_crud_stats(pairs: list[dict]) -> dict:
    """统计 CRUD 分布。"""
    counter = Counter()
    for p in pairs:
        op = p.get("operation")
        if not op or op == "unknown":
            op = guess_operation(p["gremlin"])
            p["operation"] = op
        counter[op] += 1
    return dict(counter.most_common())


def main():
    parser = argparse.ArgumentParser(description="合并 text2gremlin 数据集")
    parser.add_argument("--translated", default=None, help="llm_translated 文件路径（不指定则自动找最新的）")
    parser.add_argument("--migrated", default=None, help="migrated 文件路径（不指定则自动找最新的）")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    args = parser.parse_args()

    translated_path = args.translated or find_latest_translated(args.output_dir)
    migrated_path = args.migrated or find_latest_migrated(args.output_dir)

    if not translated_path or not os.path.exists(translated_path):
        print("❌ 未找到 llm_translated 文件，请用 --translated 指定", file=sys.stderr)
        sys.exit(1)
    if not migrated_path or not os.path.exists(migrated_path):
        print("❌ 未找到 migrated 文件，请用 --migrated 指定", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("📦 合并 text2gremlin 数据集")
    print("=" * 60)

    print(f"\n📂 加载 llm_translated: {translated_path}")
    translated_pairs = load_from_translated(translated_path)
    print(f"   提取: {len(translated_pairs)} 条")

    print(f"\n📂 加载 migrated: {migrated_path}")
    migrated_pairs = load_from_migrated(migrated_path)
    print(f"   提取: {len(migrated_pairs)} 条")

    all_pairs = translated_pairs + migrated_pairs
    print(f"\n📊 合并总数: {len(all_pairs)} 条")

    # CRUD 统计
    print("\n" + "-" * 60)
    print("📊 CRUD 分布统计")
    print("-" * 60)

    translated_crud = compute_crud_stats(translated_pairs)
    migrated_crud = compute_crud_stats(migrated_pairs)
    total_crud = compute_crud_stats(all_pairs)

    print(f"\n  llm_translated ({len(translated_pairs)} 条, 规则推断):")
    for op, cnt in translated_crud.items():
        pct = cnt / len(translated_pairs) * 100
        print(f"    {op:8s}: {cnt:6d} ({pct:.1f}%)")

    print(f"\n  migrated ({len(migrated_pairs)} 条, 标签统计):")
    for op, cnt in migrated_crud.items():
        pct = cnt / len(migrated_pairs) * 100
        print(f"    {op:8s}: {cnt:6d} ({pct:.1f}%)")

    print(f"\n  总计 ({len(all_pairs)} 条):")
    for op, cnt in total_crud.items():
        pct = cnt / len(all_pairs) * 100
        print(f"    {op:8s}: {cnt:6d} ({pct:.1f}%)")

    domain_counter = Counter(p["domain"] for p in all_pairs)
    print(f"\n📊 领域分布 ({len(domain_counter)} 个领域):")
    for domain, cnt in domain_counter.most_common():
        print(f"    {domain:20s}: {cnt:6d}")

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(args.output_dir, f"text2gremlin_dataset_{ts}.json")
    os.makedirs(args.output_dir, exist_ok=True)

    output_data = {
        "metadata": {
            "total": len(all_pairs),
            "sources": {
                "llm_translated": {"file": translated_path, "count": len(translated_pairs)},
                "migrated": {"file": migrated_path, "count": len(migrated_pairs)},
            },
            "crud_distribution": total_crud,
            "domain_distribution": dict(domain_counter.most_common()),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "corpus": [
            {
                "query": p["gremlin"],
                "text": p["text"],
                "domain": p["domain"],
                "operation": p["operation"],
                "language_style": p["language_style"],
                "source": p["source"],
                "source_metadata": p.get("source_metadata", {}),
            }
            for p in all_pairs
        ],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n💾 数据集已保存: {output_path}")
    print("   (corpus 格式兼容 analyze_syntax.py)")

    print("\n" + "=" * 60)
    print("✅ 完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
