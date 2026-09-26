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
Gremlin 场景迁移脚本

包含两个阶段：
  1. 数据准备：从 LLM 翻译结果中提取 text2gremlin 数据对
  2. 场景迁移：将数据迁移到其他业务场景（每条 × 4 个场景，轮转分配）

用法:
    # 自动从最新翻译结果提取数据并迁移
    python -m llm_augment.migrate_scenario

    # 指定翻译结果文件
    python -m llm_augment.migrate_scenario --translated output/llm_translated_xxx.json

    # 跳过数据准备，直接用已有的 pairs 文件迁移
    python -m llm_augment.migrate_scenario --input output/text2gremlin_pairs_xxx.json
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime
from glob import glob

from base.generator import check_gremlin_syntax
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from llm_augment.generalize_llm import get_llm_config, load_config


class GeneratedSample(BaseModel):
    """单条迁移生成的样本"""

    operation: str = Field(description="操作类型: read/create/update/delete")
    language_style: str = Field(description="语言风格")
    query: str = Field(description="Gremlin 查询")
    natural_language: str = Field(description="自然语言描述")


class MigrationResult(BaseModel):
    """单次迁移的 LLM 输出"""

    source_pattern: str = Field(description="原始查询模式")
    source_intent: str = Field(description="原始查询意图")
    target_domain: str = Field(description="目标领域")
    mapping_explanation: str = Field(description="映射说明")
    generated_samples: list[GeneratedSample] = Field(min_length=1)


def load_schemas(path: str = "db_data/reference/schemas_data.json") -> list[dict]:
    """加载场景 schema 列表，按 index 排序"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    scenarios = data.get("scenarios", {})
    result = []
    for key, val in scenarios.items():
        result.append(
            {
                "key": key,
                "index": val["index"],
                "name_zh": val["name_zh"],
                "domain": val["domain"],
                "schema": val["schema"],
            }
        )
    result.sort(key=lambda x: x["index"])
    return result


PICK_STYLES = ["zh_formal", "zh_casual", "en_formal", "en_casual"]
MIGRATION_MODES = ("same_operation", "mixed_operations")
DEFAULT_MIGRATION_MODE = "same_operation"
DEFAULT_SAME_OPERATION_SAMPLE_COUNT = 3


def infer_operation_type(query: str) -> str:
    """Infer the broad Gremlin operation type used by migration prompts."""
    normalized = query.replace(" ", "").lower()
    if "addv(" in normalized or "adde(" in normalized:
        return "create"
    if ".drop(" in normalized:
        return "delete"
    if ".property(" in normalized:
        return "update"
    return "read"


def operation_query_example(operation: str) -> str:
    """Return a query example that matches the requested operation type."""
    examples = {
        "read": "g.V().hasLabel('target_label')",
        "create": "g.addV('target_label').property('name', 'value')",
        "update": "g.V().hasLabel('target_label').has('id', 'value').property('name', 'new_value')",
        "delete": "g.V().hasLabel('target_label').has('id', 'value').drop()",
    }
    return examples.get(operation, examples["read"])


def get_migration_config(config: dict) -> dict:
    """Read scenario migration options from config with stable defaults."""
    migration_cfg = config.get("migration", {})
    migration_mode = migration_cfg.get("migration_mode", DEFAULT_MIGRATION_MODE)
    if migration_mode not in MIGRATION_MODES:
        raise ValueError(f"migration.migration_mode must be one of {MIGRATION_MODES}, got: {migration_mode}")

    sample_count = migration_cfg.get("same_operation_sample_count", DEFAULT_SAME_OPERATION_SAMPLE_COUNT)
    if not isinstance(sample_count, int) or sample_count <= 0:
        raise ValueError("migration.same_operation_sample_count must be a positive integer")

    return {
        "migration_mode": migration_mode,
        "same_operation_sample_count": sample_count,
    }


def filter_generated_samples(samples: list[GeneratedSample], source_operation: str, migration_mode: str) -> list[dict]:
    """Filter validated samples according to migration mode semantics."""
    valid_samples = []
    for sample in samples:
        if migration_mode == "same_operation":
            if sample.operation != source_operation:
                continue
            if infer_operation_type(sample.query) != source_operation:
                continue
        valid_samples.append(sample.model_dump())
    return valid_samples


def find_latest_translated(output_dir: str = "output") -> str | None:
    """找到 output 目录下最新的 LLM 翻译结果文件"""
    pattern = os.path.join(output_dir, "llm_translated_*.json")
    files = sorted(glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def prepare_pairs(translated_path: str, output_dir: str = "output") -> tuple[str, list[dict]]:
    """
    从 LLM 翻译结果中提取 text2gremlin 数据对。

    对每条数据，从 zh_formal/zh_casual/en_formal/en_casual 中随机选一个作为 text，
    与 gremlin query 组成一对，打乱后保存。
    """
    with open(translated_path, encoding="utf-8") as f:
        data = json.load(f)

    corpus = data.get("corpus", [])
    pairs = []
    style_counts = {}

    for item in corpus:
        if "_error" in item:
            continue

        style_map = {t["style"]: t["text"] for t in item["translations"]}
        available = [s for s in PICK_STYLES if s in style_map]
        if not available:
            continue

        chosen_style = random.choice(available)
        pairs.append(
            {
                "text": style_map[chosen_style],
                "gremlin": item["query"],
                "style": chosen_style,
                "source_metadata": item.get("metadata", {}),
            }
        )
        style_counts[chosen_style] = style_counts.get(chosen_style, 0) + 1

    random.shuffle(pairs)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pairs_path = os.path.join(output_dir, f"text2gremlin_pairs_{timestamp}.json")

    output_data = {
        "metadata": {
            "source_file": translated_path,
            "total_pairs": len(pairs),
            "style_distribution": style_counts,
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "pairs": pairs,
    }

    os.makedirs(os.path.dirname(os.path.abspath(pairs_path)), exist_ok=True)
    with open(pairs_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 数据准备完成: {len(pairs)} 条 text2gremlin 数据")
    print(f"  风格分布: {style_counts}")
    print(f"  已保存到: {pairs_path}")

    return pairs_path, pairs


def find_latest_pairs(output_dir: str = "output") -> str | None:
    pattern = os.path.join(output_dir, "text2gremlin_pairs_*.json")
    files = sorted(glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def load_pairs(input_path: str) -> list[dict]:
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pairs", [])


def build_migration_prompt(
    source_nl: str,
    source_query: str,
    target_schema: dict,
    migration_mode: str = DEFAULT_MIGRATION_MODE,
    sample_count: int = DEFAULT_SAME_OPERATION_SAMPLE_COUNT,
) -> str:
    """构建场景迁移 prompt"""
    if migration_mode not in MIGRATION_MODES:
        raise ValueError(f"migration_mode must be one of {MIGRATION_MODES}, got: {migration_mode}")
    if sample_count <= 0:
        raise ValueError("sample_count must be a positive integer")

    schema_json = json.dumps(target_schema, ensure_ascii=False, indent=2)
    source_operation = infer_operation_type(source_query)

    if migration_mode == "same_operation":
        query_example = operation_query_example(source_operation)
        operation_goal = f"4. 只生成与原始 Gremlin 同类型的 {source_operation} 操作。"
        generation_requirements = f"""1. 生成 {sample_count} 条样本。
2. 每条样本都必须是 {source_operation} 类型，operation 字段固定填写 "{source_operation}"。
3. 保持或近似保持原始查询的核心模式，并迁移到目标 schema 中合理的节点、边和属性。
4. 如果无法高质量生成 {sample_count} 条，可以少生成，但不要编造。"""
        output_example = f"""{{
  "source_pattern": "...",
  "source_intent": "...",
  "target_domain": "...",
  "mapping_explanation": "...",
  "generated_samples": [
    {{
      "operation": "{source_operation}",
      "language_style": "...",
      "query": "{query_example}",
      "natural_language": "..."
    }}
  ]
}}"""
    else:
        operation_goal = "4. 可生成 read / create / update / delete 四类操作。"
        generation_requirements = """1. 生成 5 条样本，优先包含：
   - 2 条 read类型语句
   - 1 条 create类型语句
   - 1 条 update类型
   - 1 条 delete类型语句
2. 若 create / update / delete 三种类型不适合，请全部生成 read类型语句，但要保证模式多样化。
3. 在常见场景之外，部分生成的样本可以考虑不常见或难度高的场景和 Gremlin 用法，以增加泛化性。
4. 如果某条样本无法高质量生成，请不要编造。"""
        output_example = """{
  "source_pattern": "...",
  "source_intent": "...",
  "target_domain": "...",
  "mapping_explanation": "...",
  "generated_samples": [
    {
      "operation": "read",
      "language_style": "...",
      "query": "g.V()...",
      "natural_language": "..."
    },
    {
      "operation": "read",
      "language_style": "...",
      "query": "g.V()...",
      "natural_language": "..."
    },
    {
      "operation": "create",
      "language_style": "...",
      "query": "g.addV()...",
      "natural_language": "..."
    },
    {
      "operation": "update",
      "language_style": "...",
      "query": "...",
      "natural_language": "..."
    },
    {
      "operation": "delete",
      "language_style": "...",
      "query": "...",
      "natural_language": "..."
    }
  ]
}"""

    prompt = f"""你是一个专门做 text2gremlin 数据增强的助手。

## 【你的任务】
给定一条来自电影领域的 text2gremlin 样本，以及一个目标业务场景的 graph schema，
你需要先识别原始 Gremlin 查询的"查询模式"，再在目标 schema 中生成若干条合法、自然、可执行的 Gremlin 样本及对应自然语言。

## 【目标】
1. 保持或近似保持原始查询的核心模式，可以适当增加多样性
2. 迁移到目标场景时，尽量使用目标 schema 中定义的节点、边、属性，可以为了增加多样性适当增加一些节点、边、属性，但必须要符合当前的schema场景。
3. 生成的自然语言要像真实用户会说的话，而不是 Gremlin 逐步解释。
{operation_goal}
5. 若原模式不适合生成某类操作，可以少生成或跳过，不要强行凑数。

## 【输入】
原始领域：movie
### 原始自然语言：
{source_nl}

### 原始 Gremlin：
{source_query}

### 目标 schema：
{schema_json}

## 【请先完成以下分析】
1. 识别原始查询的 pattern，格式例如：
   - start_vertex
   - one_hop_traversal
   - two_hop_traversal
   - reverse_traversal
   - filter_by_property
   - dedup
   - count
   - group
   - order_limit
   - path_query
2. 用一句话说明原始查询的业务意图。
3. 判断该模式在目标 schema 中最适合映射到哪些节点和边。

## 【生成要求】
{generation_requirements}
5. 每条样本必须：
   - query 合法
   - 符合目标 schema 定义场景
   - 自然语言与 query 严格对应
6. 每条gremlin的自然语言字段随机选择下面的一个语气类型进行生成：
   - zh_formal：中文正式的语气
   - zh_casual：中文口语的语气
   - en_formal：英文正式的语气
   - en_casual：英文口语的语气

## 【Gremlin 风格要求】
1. 尽量简洁。
2. 语句运行效率高效。

## 【输出格式】
严格输出 JSON：
```json
{output_example}
```"""
    return prompt


async def migrate_one(
    client: AsyncOpenAI,
    pair: dict,
    target_schema: dict,
    semaphore: asyncio.Semaphore,
    llm_config: dict,
    migration_config: dict,
) -> dict:
    """
    将单条 text2gremlin 数据迁移到一个目标场景。

    生成后对每条 gremlin 做语法检查：
    - 至少有一条通过语法检查才算成功，只保留通过的
    - 全部语法错误则重试
    """
    max_retries = llm_config["max_retries"]
    timeout = llm_config.get("timeout", 40)

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_migration_prompt(
                    pair["text"],
                    pair["gremlin"],
                    target_schema["schema"],
                    migration_mode=migration_config["migration_mode"],
                    sample_count=migration_config["same_operation_sample_count"],
                )

                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=llm_config["model"],
                        messages=[{"role": "user", "content": prompt}],
                        temperature=llm_config["temperature"],
                    ),
                    timeout=timeout,
                )
                content = response.choices[0].message.content

                if not content or not content.strip():
                    raise ValueError("LLM 返回内容为空")

                # 提取 JSON
                json_str = content
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0]

                data = json.loads(json_str.strip())

                # Pydantic 验证
                validated = MigrationResult(**data)
                source_operation = infer_operation_type(pair["gremlin"])

                # 语法检查：过滤掉语法错误的 sample
                syntax_valid_samples = []
                for s in validated.generated_samples:
                    ok, _msg = check_gremlin_syntax(s.query)
                    if ok:
                        syntax_valid_samples.append(s)
                valid_samples = filter_generated_samples(
                    syntax_valid_samples, source_operation, migration_config["migration_mode"]
                )

                if not valid_samples:
                    raise ValueError(f"所有 {len(validated.generated_samples)} 条 gremlin 语法检查均失败")

                return {
                    "source_text": pair["text"],
                    "source_gremlin": pair["gremlin"],
                    "source_metadata": pair.get("source_metadata", {}),
                    "target_domain": target_schema["domain"],
                    "target_name_zh": target_schema["name_zh"],
                    "source_pattern": validated.source_pattern,
                    "source_intent": validated.source_intent,
                    "mapping_explanation": validated.mapping_explanation,
                    "generated_samples": valid_samples,
                }

            except (json.JSONDecodeError, ValueError, KeyError, ValidationError) as e:
                if attempt < max_retries - 1:
                    continue
                else:
                    return _fallback_migration(pair, target_schema, f"迁移失败(重试{max_retries}次): {e}")
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(2**attempt, 8) + random.random() * 0.25)
                    continue
                error_message = str(e) or "no message"
                return _fallback_migration(pair, target_schema, f"迁移异常 {type(e).__name__}: {error_message}")


def _fallback_migration(pair: dict, target_schema: dict, error: str) -> dict:
    return {
        "source_text": pair["text"],
        "source_gremlin": pair["gremlin"],
        "source_metadata": pair.get("source_metadata", {}),
        "target_domain": target_schema["domain"],
        "target_name_zh": target_schema["name_zh"],
        "source_pattern": "",
        "source_intent": "",
        "mapping_explanation": "",
        "generated_samples": [],
        "_error": error,
    }


async def migrate_all(
    pairs: list[dict],
    schemas: list[dict],
    llm_config: dict,
    output_path: str,
    input_path: str,
    migration_config: dict,
    save_interval: int = 50,
) -> list[dict]:
    """
    流水线并发迁移所有数据。

    每条数据迁移到 4 个场景，场景按顺序轮转。
    """
    req_timeout = llm_config.get("timeout", 40)
    client = AsyncOpenAI(
        base_url=llm_config["base_url"],
        api_key=llm_config["api_key"],
        timeout=req_timeout,
    )

    semaphore = asyncio.Semaphore(llm_config["max_concurrency"])
    num_schemas = len(schemas)
    total_tasks = len(pairs) * 4

    print(f"  共 {len(pairs)} 条数据 × 4 场景 = {total_tasks} 个迁移任务")
    print("  已加载 LLM 运行配置（敏感字段不显示）")
    print("  已启用增量保存")
    print(f"  场景数: {num_schemas}，轮转分配")

    # 创建所有任务：每条数据迁移到 4 个连续场景
    tasks = {}
    for idx, pair in enumerate(pairs):
        base_schema_idx = (idx * 4) % num_schemas
        for j in range(4):
            schema_idx = (base_schema_idx + j) % num_schemas
            target_schema = schemas[schema_idx]
            task = asyncio.create_task(
                migrate_one(client, pair, target_schema, semaphore, llm_config, migration_config)
            )
            tasks[task] = (idx, j)

    pending = set(tasks.keys())
    results = []
    completed = 0
    last_save = 0
    start_time = time.time()

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            result = task.result()
            results.append(result)
            completed += 1

            elapsed = time.time() - start_time
            speed = completed / elapsed if elapsed > 0 else 0
            print(f"\r  进度: {completed}/{total_tasks} ({speed:.1f} 条/秒)", end="", flush=True)

            if completed - last_save >= save_interval:
                _incremental_save(results, output_path, input_path, elapsed, migration_config)
                last_save = completed
                print(f" [已保存 {completed} 条]", end="", flush=True)

    print()
    return results


def _load_existing_keys(output_path: str) -> set:
    """从已保存的文件中加载已有的 (gremlin, language_style) 集合"""
    if not os.path.exists(output_path):
        return set()
    try:
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        keys = set()
        for m in data.get("migrations", []):
            for s in m.get("generated_samples", []):
                keys.add((s["query"], s["language_style"]))
        return keys
    except (json.JSONDecodeError, KeyError):
        return set()


def _dedup_results(results: list[dict], existing_keys: set) -> tuple[list[dict], set]:
    """对 results 中的 generated_samples 去重。"""
    deduped = []
    for r in results:
        if "_error" in r:
            deduped.append(r)
            continue

        unique_samples = []
        for s in r["generated_samples"]:
            key = (s["query"], s["language_style"])
            if key not in existing_keys:
                existing_keys.add(key)
                unique_samples.append(s)

        r_copy = dict(r)
        r_copy["generated_samples"] = unique_samples
        deduped.append(r_copy)

    return deduped, existing_keys


def _incremental_save(
    results: list[dict], output_path: str, input_path: str, elapsed: float, migration_config: dict | None = None
):
    existing_keys = _load_existing_keys(output_path)
    deduped, _ = _dedup_results(results, existing_keys)

    success_count = sum(1 for r in deduped if "_error" not in r)
    total_samples = sum(len(r["generated_samples"]) for r in deduped)

    output_data = {
        "metadata": {
            "source_file": input_path,
            "total_migrations": len(deduped),
            "total_generated_samples": total_samples,
            "success_count": success_count,
            "fail_count": len(deduped) - success_count,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "in_progress",
            "migration_config": migration_config or {},
        },
        "migrations": deduped,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def save_results(results: list[dict], output_path: str, input_path: str, elapsed: float, migration_config: dict):
    existing_keys = set()
    deduped, _ = _dedup_results(results, existing_keys)

    success_count = sum(1 for r in deduped if "_error" not in r)
    total_samples = sum(len(r["generated_samples"]) for r in deduped)

    domain_counts = {}
    for r in deduped:
        d = r["target_domain"]
        domain_counts[d] = domain_counts.get(d, 0) + 1

    output_data = {
        "metadata": {
            "source_file": input_path,
            "total_migrations": len(deduped),
            "total_generated_samples": total_samples,
            "success_count": success_count,
            "fail_count": len(deduped) - success_count,
            "domain_distribution": domain_counts,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "completed",
            "migration_config": migration_config,
        },
        "migrations": deduped,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="将 text2gremlin 数据迁移到多个业务场景")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--translated", default=None, help="LLM 翻译结果文件（自动提取 pairs）")
    parser.add_argument("--input", default=None, help="已有的 text2gremlin pairs 文件（跳过数据准备）")
    parser.add_argument("--schemas", default="db_data/reference/schemas_data.json", help="场景 schema 文件")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument(
        "--migration-mode",
        choices=MIGRATION_MODES,
        default=None,
        help="场景迁移模式: same_operation 只生成同类型语句, mixed_operations 生成混合 CRUD",
    )
    parser.add_argument(
        "--same-operation-sample-count", type=int, default=None, help="同类型迁移模式下每次生成的样本数"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    llm_config = get_llm_config(config)
    migration_config = get_migration_config(config)
    if args.migration_mode:
        migration_config["migration_mode"] = args.migration_mode
    if args.same_operation_sample_count is not None:
        if args.same_operation_sample_count <= 0:
            raise ValueError("--same-operation-sample-count must be a positive integer")
        migration_config["same_operation_sample_count"] = args.same_operation_sample_count
    output_dir = config.get("output_dir", "output")

    # 加载 schema
    schemas = load_schemas(args.schemas)
    print(f"📋 加载了 {len(schemas)} 个场景 schema")

    # ---- 阶段 1: 数据准备 ----
    if args.input:
        input_path = args.input
        if not os.path.exists(input_path):
            print(f"❌ 文件不存在: {input_path}")
            sys.exit(1)
        pairs = load_pairs(input_path)
        print(f"📂 直接使用已有数据: {input_path} ({len(pairs)} 条)")
    else:
        translated_path = args.translated or find_latest_translated(output_dir)
        if translated_path and os.path.exists(translated_path):
            print(f"\n{'=' * 60}")
            print("📦 阶段 1: 数据准备")
            print(f"{'=' * 60}")
            print(f"  翻译结果: {translated_path}")
            input_path, pairs = prepare_pairs(translated_path, output_dir)
        else:
            input_path = find_latest_pairs(output_dir)
            if not input_path or not os.path.exists(input_path):
                print("❌ 未找到翻译结果或 text2gremlin 数据文件")
                sys.exit(1)
            pairs = load_pairs(input_path)
            print(f"📂 使用已有数据: {input_path} ({len(pairs)} 条)")

    if not pairs:
        print("❌ 数据为空")
        sys.exit(1)

    # ---- 阶段 2: 场景迁移 ----
    output_path = args.output
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"migrated_{timestamp}.json")

    total_tasks = len(pairs) * 4

    print(f"\n{'=' * 60}")
    print("🚀 阶段 2: 场景迁移")
    print("=" * 60)
    print("\n📋 配置:")
    print(f"  输入文件: {input_path}")
    print(f"  输出文件: {output_path}")
    print("  LLM 配置: 已加载（敏感字段不显示）")
    print("  重试与保存策略: 使用配置文件设置")
    print(f"  迁移模式: {migration_config['migration_mode']}")
    print(f"  同类型迁移样本数: {migration_config['same_operation_sample_count']}")
    print(f"\n  数据条数: {len(pairs)}")
    print("  每条迁移: 4 个场景")
    print(f"  总任务数: {total_tasks}")
    print(f"  场景数: {len(schemas)}")
    print("-" * 60)

    start_time = time.time()
    results = asyncio.run(
        migrate_all(
            pairs,
            schemas,
            llm_config,
            output_path,
            input_path,
            migration_config,
            save_interval=llm_config["save_interval"],
        )
    )
    elapsed = time.time() - start_time

    save_results(results, output_path, input_path, elapsed, migration_config)

    success_count = sum(1 for r in results if "_error" not in r)
    fail_count = len(results) - success_count
    total_samples = sum(len(r["generated_samples"]) for r in results)

    print("\n" + "=" * 60)
    print("✅ 场景迁移完成")
    print("=" * 60)
    print(f"  总耗时: {elapsed:.2f} 秒")
    print(f"  成功: {success_count}，失败: {fail_count}")
    print(f"  生成样本总数: {total_samples}")
    print(f"  吞吐量: {len(results) / elapsed:.2f} 条/秒")
    print(f"\n💾 结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
