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
Gremlin 查询 LLM 多风格翻译脚本

读取 AST 泛化阶段生成的语料库（Gremlin query + 简单描述），
通过 LLM 将每条查询翻译为 6 种不同风格的自然语言表达：
  - 4 种固定风格：中文正式、中文口语、英文正式、英文口语
  - 2 种随机风格：从中英混合、省略表达、问答/指令/片段式、错别字中随机选取

用法:
    # 使用默认配置，自动找到最新的泛化结果
    python -m llm_augment.generalize_llm

    # 指定输入文件
    python -m llm_augment.generalize_llm --input output/generated_corpus_xxx.json
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

from openai import AsyncOpenAI
from pydantic import ValidationError, create_model

# 4 种固定风格（每条必须生成）
FIXED_STYLES = ["zh_formal", "zh_casual", "en_formal", "en_casual"]

# 4 种可选风格（每条随机选 2 种）
OPTIONAL_STYLES = ["mixed_lang", "abbreviated", "interactive", "typo"]

# 风格描述（用于 prompt）
STYLE_DESCRIPTIONS = {
    "zh_formal": "中文正式：用规范的书面中文描述查询意图",
    "zh_casual": "中文口语：用日常口语化的中文表达",
    "en_formal": "英文正式：用规范的英文描述查询意图",
    "en_casual": "英文口语：用日常口语化的英文表达",
    "mixed_lang": "中英混合：中英文混用，像开发者日常交流",
    "abbreviated": "省略表达：极度精简，只保留核心关键词",
    "interactive": "问答式/指令式/片段式：像用户在对话中提问或下指令",
    "typo": "夹杂错别字：在中文表达中故意引入1-2个错别字（同音字或形近字），但不影响语义",
}

# 风格示例（用于 prompt 示例部分）
STYLE_EXAMPLES = {
    "zh_formal": "查询所有电影关联的不重复流派名称",
    "zh_casual": "电影都有哪些类型啊",
    "en_formal": "Retrieve distinct genre names associated with all movies.",
    "en_casual": "What genres do the movies belong to?",
    "mixed_lang": "查一下 movie 关联的 genre name，去重",
    "abbreviated": "电影 流派 去重",
    "interactive": "给我查一下电影都有哪些类型",
    "typo": "电映都有那些类形",
}


def create_translation_model(styles: list[str]):
    """动态创建 Pydantic 模型，字段名为实际风格名"""
    fields = dict.fromkeys(styles, (str, ...))
    return create_model("TranslationResult", **fields)


def load_config(config_path: str = "config.json") -> dict:
    """加载配置文件"""
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def get_llm_config(config: dict) -> dict:
    """
    获取 LLM 配置。

    所有必需参数必须在 config.json 的 "llm" 字段中正确配置，
    缺少字段或仍为占位符值时抛出 ValueError。
    """
    llm_cfg = config.get("llm")
    if not llm_cfg:
        raise ValueError(
            "config.json 中缺少 'llm' 配置块，请添加以下配置:\n"
            '  "llm": {\n'
            '    "base_url": "http://your-llm-server:port/v1",\n'
            '    "api_key": "your-api-key",\n'
            '    "model": "your-model-name",\n'
            "    ...\n"
            "  }"
        )

    required_fields = {
        "base_url": ["your-llm-server"],
        "api_key": ["your-api-key"],
        "model": ["your-model-name"],
    }

    missing = [f for f in required_fields if f not in llm_cfg]
    if missing:
        raise ValueError(f"config.json 的 'llm' 配置中缺少必需字段: {missing}\n请在 config.json 中补充这些字段。")

    placeholder_fields = []
    for field, placeholders in required_fields.items():
        val = str(llm_cfg.get(field, ""))
        if any(p in val for p in placeholders):
            placeholder_fields.append(field)

    if placeholder_fields:
        details = ", ".join(f'{f}="{llm_cfg[f]}"' for f in placeholder_fields)
        raise ValueError(
            f"config.json 的 'llm' 配置中以下字段仍为占位符，请修改为实际值: {placeholder_fields}\n  当前值: {details}"
        )

    return {
        "base_url": llm_cfg["base_url"],
        "api_key": llm_cfg["api_key"],
        "model": llm_cfg["model"],
        "temperature": llm_cfg.get("temperature", 0.7),
        "max_retries": llm_cfg.get("max_retries", 3),
        "max_concurrency": llm_cfg.get("max_concurrency", 20),
        "save_interval": llm_cfg.get("save_interval", 50),
        "timeout": llm_cfg.get("timeout", 40),
    }


def find_latest_corpus(output_dir: str = "output") -> str | None:
    """找到 output 目录下最新的泛化结果文件"""
    pattern = os.path.join(output_dir, "generated_corpus_*.json")
    files = sorted(glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def load_corpus(input_path: str) -> list[dict]:
    """加载泛化结果文件，返回 corpus 列表"""
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("corpus", [])


def pick_random_styles(n: int = 2) -> list[str]:
    """从可选风格中随机选取 n 种"""
    return random.sample(OPTIONAL_STYLES, n)


def build_translation_prompt(item: dict, all_styles: list[str]) -> str:
    """
    构建单条翻译 prompt。

    Args:
        item: 待翻译的 (query, description)
        all_styles: 6 种风格名列表（4 固定 + 2 随机，已确定）
    """
    # 构建风格要求部分
    styles_text = "\n".join(f"{i}. {style}: {STYLE_DESCRIPTIONS[style]}" for i, style in enumerate(all_styles, 1))

    # 构建输出格式
    output_fields = ",\n        ".join(f'"{style}": "..."' for style in all_styles)

    # 构建示例输出
    example_fields = ",\n        ".join(f'"{style}": "{STYLE_EXAMPLES[style]}"' for style in all_styles)

    prompt = f"""你是一个图数据库专家，需要将 Gremlin 查询语句翻译为图数据库使用者可能提出的自然语言问题。
### 任务
给你一条 Gremlin 查询及其简单描述，将 Gremlin 查询翻译为 6 种风格的自然语言。

### 风格要求：
{styles_text}

### 输出要求
1. 准确反映查询语义，不遗漏过滤条件、排序、限制数量等
2. 各风格表达方式要有明显差异，长度要自然，可根据风格适当变化
3. 专有名词保持原样，不要出现 Gremlin 术语
4. typo 风格只引入 1-2 个错别字，不影响语义
5. abbreviated 风格极度精简到核心关键词
6. interactive 风格从问答式、指令式、片段式中选一种

### 输出格式（严格 JSON）
```json
{{
    {output_fields}
}}
```

### 示例
输入:
Gremlin: g.V().hasLabel('movie').out('has_genre').dedup().values('name')
描述: 从图中开始查找所有顶点，过滤出'电影'类型的顶点，沿'has_genre'边out方向遍历，去重，获取'名称'属性值

输出:
```json
{{
    {example_fields}
}}
```

### 实际输入
结合以上要求，将以下输入的gremlin语句进行翻译：
Gremlin: {item["query"]}
简单描述: {item["description"]}
"""

    return prompt


async def translate_one(
    client: AsyncOpenAI,
    item: dict,
    semaphore: asyncio.Semaphore,
    llm_config: dict,
) -> dict:
    """
    翻译单条 Gremlin 查询为多风格表达。

    Returns:
        包含 query, description, translations 的结果
    """
    max_retries = llm_config["max_retries"]

    # 确定 6 种风格（4 固定 + 2 随机）
    extra_styles = pick_random_styles(2)
    all_styles = FIXED_STYLES + extra_styles

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_translation_prompt(item, all_styles)

                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=llm_config["model"],
                        messages=[{"role": "user", "content": prompt}],
                        temperature=llm_config["temperature"],
                    ),
                    timeout=llm_config.get("timeout", 40),
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
                TranslationModel = create_translation_model(all_styles)
                validated = TranslationModel(**data)

                # 组装结果
                translations = []
                for style in all_styles:
                    text = getattr(validated, style)
                    translations.append({"style": style, "text": text})

                return {
                    "query": item["query"],
                    "description": item["description"],
                    "metadata": item.get("metadata", {}),
                    "translations": translations,
                }

            except (json.JSONDecodeError, ValueError, KeyError, ValidationError) as e:
                if attempt < max_retries - 1:
                    continue
                else:
                    return _fallback_result(item, all_styles, error=f"翻译失败(重试{max_retries}次): {e}")
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(2**attempt, 8) + random.random() * 0.25)
                    continue
                return _fallback_result(item, all_styles, error=f"翻译异常: {e}")


def _fallback_result(item: dict, all_styles: list[str], error: str | None = None) -> dict:
    """生成兜底结果（翻译失败时用描述填充）"""
    desc = item["description"]
    result = {
        "query": item["query"],
        "description": desc,
        "metadata": item.get("metadata", {}),
        "translations": [{"style": style, "text": desc} for style in all_styles],
    }
    if error:
        result["_error"] = error
    return result


async def translate_all(
    corpus: list[dict],
    llm_config: dict,
    output_path: str,
    input_path: str,
    save_interval: int = 50,
) -> list[dict]:
    """
    流水线并发翻译所有语料，支持增量保存。
    """
    req_timeout = llm_config.get("timeout", 40)
    client = AsyncOpenAI(
        base_url=llm_config["base_url"],
        api_key=llm_config["api_key"],
        timeout=req_timeout,
    )

    semaphore = asyncio.Semaphore(llm_config["max_concurrency"])
    results = []
    completed = 0
    last_save = 0
    start_time = time.time()

    print(f"  共 {len(corpus)} 条，流水线并发")
    print("  已加载 LLM 运行配置（敏感字段不显示）")
    print("  已启用增量保存")
    print("  每条生成 6 种风格翻译 (4固定 + 2随机)")

    # 创建所有任务
    tasks = {
        asyncio.create_task(translate_one(client, item, semaphore, llm_config)): idx for idx, item in enumerate(corpus)
    }
    pending = set(tasks.keys())

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            result = task.result()
            results.append(result)
            completed += 1

            elapsed = time.time() - start_time
            speed = completed / elapsed if elapsed > 0 else 0
            print(f"\r  进度: {completed}/{len(corpus)} ({speed:.1f} 条/秒)", end="", flush=True)

            if completed - last_save >= save_interval:
                _incremental_save(results, output_path, input_path, elapsed)
                last_save = completed
                print(f" [已保存 {completed} 条]", end="", flush=True)

    print()
    return results


def _incremental_save(results: list[dict], output_path: str, input_path: str, elapsed: float):
    """增量保存当前结果"""
    success_count = sum(1 for r in results if "_error" not in r)

    style_counts = {}
    for r in results:
        for t in r["translations"]:
            style_counts[t["style"]] = style_counts.get(t["style"], 0) + 1

    output_data = {
        "metadata": {
            "source_file": input_path,
            "total_queries": len(results),
            "total_translations": sum(len(r["translations"]) for r in results),
            "translations_per_query": 6,
            "fixed_styles": FIXED_STYLES,
            "optional_styles": OPTIONAL_STYLES,
            "style_distribution": style_counts,
            "success_count": success_count,
            "fail_count": len(results) - success_count,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "in_progress",
        },
        "corpus": results,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def save_results(results: list[dict], output_path: str, input_path: str, elapsed: float):
    """保存最终翻译结果"""
    success_count = sum(1 for r in results if "_error" not in r)
    total_translations = sum(len(r["translations"]) for r in results)

    style_counts = {}
    for r in results:
        for t in r["translations"]:
            style = t["style"]
            style_counts[style] = style_counts.get(style, 0) + 1

    output_data = {
        "metadata": {
            "source_file": input_path,
            "total_queries": len(results),
            "total_translations": total_translations,
            "translations_per_query": 6,
            "fixed_styles": FIXED_STYLES,
            "optional_styles": OPTIONAL_STYLES,
            "style_distribution": style_counts,
            "success_count": success_count,
            "fail_count": len(results) - success_count,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "completed",
        },
        "corpus": results,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="将泛化后的 Gremlin 查询通过 LLM 翻译为多风格自然语言表达",
    )
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--input", default=None, help="泛化结果文件路径（不指定则自动找最新的）")
    parser.add_argument("--output", default=None, help="输出文件路径")
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    llm_config = get_llm_config(config)
    output_dir = config.get("output_dir", "output")

    # 定位输入文件
    input_path = args.input
    if not input_path:
        input_path = find_latest_corpus(output_dir)
        if not input_path:
            print(f"❌ 在 {output_dir}/ 下未找到泛化结果文件 (generated_corpus_*.json)")
            sys.exit(1)

    if not os.path.exists(input_path):
        print(f"❌ 输入文件不存在: {input_path}")
        sys.exit(1)

    # 确定输出文件
    output_path = args.output
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"llm_translated_{timestamp}.json")

    # 加载语料
    corpus = load_corpus(input_path)
    if not corpus:
        print(f"❌ 输入文件中没有语料数据: {input_path}")
        sys.exit(1)

    print("=" * 60)
    print("🚀 Gremlin LLM 多风格翻译器")
    print("=" * 60)
    print("\n📋 配置:")
    print(f"  输入文件: {input_path}")
    print(f"  输出文件: {output_path}")
    print("  LLM 配置: 已加载（敏感字段不显示）")
    print("  每条翻译数: 6 (4固定 + 2随机)")
    print("  重试与保存策略: 使用配置文件设置")
    print(f"\n  语料条数: {len(corpus)}")
    print(f"  预计生成: {len(corpus) * 6} 条翻译")
    print("-" * 60)

    # 执行翻译
    start_time = time.time()
    results = asyncio.run(
        translate_all(corpus, llm_config, output_path, input_path, save_interval=llm_config["save_interval"])
    )
    elapsed = time.time() - start_time

    # 保存结果
    save_results(results, output_path, input_path, elapsed)

    # 统计
    success_count = sum(1 for r in results if "_error" not in r)
    fail_count = len(results) - success_count
    total_translations = sum(len(r["translations"]) for r in results)

    style_counts = {}
    for r in results:
        for t in r["translations"]:
            style_counts[t["style"]] = style_counts.get(t["style"], 0) + 1

    print("\n" + "=" * 60)
    print("✅ 翻译完成")
    print("=" * 60)
    print(f"  总耗时: {elapsed:.2f} 秒")
    print(f"  成功: {success_count}，失败: {fail_count}")
    print(f"  生成翻译总数: {total_translations}")
    print(f"  吞吐量: {len(results) / elapsed:.2f} 条/秒")
    print("\n📊 风格分布:")
    for style, count in sorted(style_counts.items(), key=lambda x: -x[1]):
        label = STYLE_DESCRIPTIONS.get(style, style).split("：")[0]
        print(f"  {label}: {count}")
    print(f"\n💾 结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
