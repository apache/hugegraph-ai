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
DPO 偏好数据生成脚本

基于已有的 text2gremlin 数据，生成 Groovy vs Gremlin 的偏好对齐训练数据。
支持 movie 领域（从 text2gremlin_pairs_*.json）和 20 个迁移领域（从 migrated_*.json）。

三类任务：
  A 类：多任务组合 — 选 2~5 条简单 gremlin 合成 groovy（chosen）和纯 gremlin（rejected）
  B 类：单任务 — 纯 gremlin（chosen）vs 包一层 groovy（rejected），数量为 A/C 的 1/3
  C 类：复杂长链拆解 — groovy 拆步骤（chosen）vs 原始长链（rejected）

用法:
    python -m llm_augment.generate_dpo_data
    python -m llm_augment.generate_dpo_data --input output/text2gremlin_pairs_xxx.json
    python -m llm_augment.generate_dpo_data --migrated output/migrated_xxx.json
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


class DPOCandidate(BaseModel):
    """DPO 候选（chosen 或 rejected）"""

    style: str = Field(description="groovy 或 gremlin")
    code: str = Field(description="代码内容")


class DPOSampleAWithReject(BaseModel):
    """A 类：多任务组合的 LLM 输出（支持拒绝）"""

    reject: bool = Field(default=False, description="是否拒绝合成（命令冲突或无法合成）")
    reject_reason: str | None = Field(default=None, description="拒绝原因")
    instruction: str | None = Field(default=None, description="合成的自然语言任务描述")
    chosen: DPOCandidate | None = None
    rejected: DPOCandidate | None = None
    preference_reason: list[str] | None = None


class DPOSampleA(BaseModel):
    """A 类：多任务组合的 LLM 输出"""

    instruction: str = Field(description="合成的自然语言任务描述")
    chosen: DPOCandidate
    rejected: DPOCandidate
    preference_reason: list[str] = Field(description="偏好原因")


class DPOSampleB(BaseModel):
    """B 类：单任务的 LLM 输出"""

    chosen: DPOCandidate
    rejected: DPOCandidate
    preference_reason: list[str] = Field(description="偏好原因")


class DPOSampleC(BaseModel):
    """C 类：复杂长链拆解的 LLM 输出"""

    chosen: DPOCandidate
    preference_reason: list[str] = Field(description="偏好原因")


class DPOSampleCWithSkip(BaseModel):
    """C 类带跳过标识"""

    skip: bool = Field(description="是否跳过（该语句不适合改写为 groovy）")
    chosen: DPOCandidate | None = None
    preference_reason: list[str] | None = None


def load_pairs(input_path: str) -> list[dict]:
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pairs", [])


def find_latest_pairs(output_dir: str = "output") -> str | None:
    pattern = os.path.join(output_dir, "text2gremlin_pairs_*.json")
    files = sorted(glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def find_latest_migrated(output_dir: str = "output") -> str | None:
    """查找最新的迁移数据文件"""
    pattern = os.path.join(output_dir, "migrated_*.json")
    files = sorted(glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def load_migrated_data(migrated_path: str) -> dict:
    """加载迁移数据并按领域分组"""
    with open(migrated_path, encoding="utf-8") as f:
        data = json.load(f)

    migrations = data.get("migrations", [])
    domain_data = {}

    for m in migrations:
        domain = m.get("target_domain")
        if not domain:
            continue

        samples = m.get("generated_samples", [])
        if not samples:
            continue

        if domain not in domain_data:
            domain_data[domain] = []

        for s in samples:
            # 转换为与 pairs 相同的格式
            pair = {
                "text": s.get("natural_language", ""),
                "gremlin": s.get("query", ""),
                "style": s.get("language_style", ""),
                "operation": s.get("operation", ""),
            }
            if pair["text"] and pair["gremlin"]:
                domain_data[domain].append(pair)

    return domain_data


def count_gremlin_steps(gremlin: str) -> int:
    """粗略统计 gremlin 语句的步数（以 '.' 分隔的方法调用数）"""
    in_str = False
    dots = 0
    for _i, ch in enumerate(gremlin):
        if ch in ("'", '"'):
            in_str = not in_str
        elif ch == "." and not in_str:
            dots += 1
    return dots


def classify_pairs(pairs: list[dict]) -> dict:
    """将数据按步数分类。"""
    short, medium, long_ = [], [], []
    for p in pairs:
        steps = count_gremlin_steps(p["gremlin"])
        p["_steps"] = steps
        if steps <= 5:
            short.append(p)
        elif steps > 8:
            long_.append(p)
        else:
            medium.append(p)
    return {"short": short, "medium": medium, "long": long_}


def select_related_group(short_pairs: list[dict], n: int, check_duplicate_gremlin: bool = False) -> list[dict]:
    """从短查询中选取 n 条相关的查询（同 label 或同操作类型优先）。

    Args:
        short_pairs: 短查询列表
        n: 需要选取的数量
        check_duplicate_gremlin: 是否检查重复 gremlin（用于 A 类任务避免选择同一查询的不同语气版本）
    """
    label_groups = {}
    for p in short_pairs:
        g = p["gremlin"]
        labels = []
        idx = 0
        while True:
            pos = g.find("hasLabel('", idx)
            if pos == -1:
                break
            start = pos + len("hasLabel('")
            end = g.find("'", start)
            if end != -1:
                labels.append(g[start:end])
            idx = end + 1 if end != -1 else len(g)

        key = tuple(sorted(set(labels))) if labels else ("_no_label",)
        label_groups.setdefault(key, []).append(p)

    candidates = sorted(label_groups.values(), key=len, reverse=True)

    for group in candidates:
        if len(group) >= n:
            if check_duplicate_gremlin:
                # 对于 A 类任务，需要确保选取的查询 gremlin 不重复
                # 先按 gremlin 去重，每个 gremlin 只保留一条
                gremlin_to_pair = {}
                for p in group:
                    gremlin = p["gremlin"]
                    if gremlin not in gremlin_to_pair:
                        gremlin_to_pair[gremlin] = p
                unique_pairs = list(gremlin_to_pair.values())
                if len(unique_pairs) >= n:
                    return random.sample(unique_pairs, n)
            else:
                return random.sample(group, n)

    # 如果没有足够大的组，从所有数据中选取
    if check_duplicate_gremlin:
        gremlin_to_pair = {}
        for p in short_pairs:
            gremlin = p["gremlin"]
            if gremlin not in gremlin_to_pair:
                gremlin_to_pair[gremlin] = p
        unique_pairs = list(gremlin_to_pair.values())
        return random.sample(unique_pairs, min(n, len(unique_pairs)))

    return random.sample(short_pairs, min(n, len(short_pairs)))


def build_prompt_type_a(selected_pairs: list[dict]) -> str:
    """A 类 prompt：多任务组合，合成 groovy 和纯 gremlin"""
    queries_text = ""
    for i, p in enumerate(selected_pairs, 1):
        op = p.get("operation", "unknown")
        queries_text += f"  {i}. [操作类型: {op}] 自然语言: {p['text']}\n     Gremlin: {p['gremlin']}\n"

    styles = [p.get("style", "") for p in selected_pairs]
    style_hint = ""
    if any("zh" in s for s in styles):
        style_hint = "中文"
    elif any("en" in s for s in styles):
        style_hint = "英文"
    else:
        style_hint = "与原始输入语句的语言风格保持一致"

    prompt = f"""你是一个图数据库专家，擅长 Gremlin 和 Groovy 编程。

## 任务
给你 {len(selected_pairs)} 条来自同一场景的简单 Gremlin 查询及其自然语言描述。
请你先分析这些命令是否可以合理地组合成一个复合任务，然后决定是否生成。

## 原始子查询
{queries_text}

## 第一步：分析命令是否可以合成
请检查以下情况：
1. **操作冲突**：如果存在删除某元素后又更新/查询该元素的情况，需要调整顺序或拒绝
2. **依赖关系**：如果命令之间有依赖（如先创建再查询），需要按正确顺序组合
3. **语义冲突**：如果命令之间存在语义矛盾（如先删除后修改同一元素），当你不能转化为合理的命令和语句时，应拒绝
4. **无法合成**：如果这些命令完全不相关，无法形成有意义的复合任务，应拒绝

如果可以合成，请调整命令顺序使其合理（如：创建 → 更新 → 查询 → 删除）。
如果无法合成，请设置 reject=true 并说明原因。

## 第二步：如果可以合成
1. 将这些查询组合成一个复合任务，生成一段自然语言描述（instruction）
2. 用 Groovy 命令式写法实现这个复合任务（chosen，style=groovy）
3. 用纯 Gremlin 函数式写法实现同样的任务（rejected，style=gremlin）
4. 说明为什么 Groovy 写法更优

## 要求
1. instruction 必须是一个自然的复合任务描述，语言风格为{style_hint}，像真实用户会说的话
2. Groovy 写法：用 def 定义中间变量，每条 traversal 调用 .next() 或 .toList()，最后返回一个 map
3. 纯 Gremlin 写法：用 project/union/inject 等方式强行写成一条语句，要体现出复杂和难读
4. 两种写法的语义必须等价
5. Groovy 中的变量命名要统一、清晰
6. preference_reason 说明 Groovy 更优的具体原因
7. **重要**：生成的 Gremlin 代码必须语法正确，可以被 ANTLR 解析
8. **禁止注释**：代码中不要包含任何注释（// 或 /* */），只输出纯代码

## 输出格式（严格 JSON）

如果可以合成：
```json
{{
  "reject": false,
  "instruction": "...",
  "chosen": {{
    "style": "groovy",
    "code": "..."
  }},
  "rejected": {{
    "style": "gremlin",
    "code": "..."
  }},
  "preference_reason": ["...", "..."]
}}
```

如果无法合成：
```json
{{
  "reject": true,
  "reject_reason": "说明为什么无法合成，如：删除操作在更新操作之前，存在逻辑冲突"
}}
```"""
    return prompt


def build_prompt_type_b(pair: dict) -> str:
    """B 类 prompt：单任务，纯 gremlin 更好，生成包一层 groovy 的负样本"""
    prompt = f"""你是一个图数据库专家，擅长 Gremlin 和 Groovy 编程。

## 任务
给你一条简单的 Gremlin 查询，这条查询用单条 Gremlin 就能很好地完成。
请你生成一个"过度工程化"的 Groovy 写法作为负样本。

## 原始查询
自然语言: {pair["text"]}
Gremlin: {pair["gremlin"]}

## 要求
1. rejected 的 Groovy 写法要体现"过度包装"：用 def 变量、.next()、返回 map 等，但实际上完全没必要
2. chosen 就是原始的 Gremlin 语句
3. preference_reason 说明为什么单条 Gremlin 更好
4. **禁止注释**：代码中不要包含任何注释（// 或 /* */），只输出纯代码

## 输出格式（严格 JSON）
```json
{{
  "chosen": {{
    "style": "gremlin",
    "code": "..."
  }},
  "rejected": {{
    "style": "groovy",
    "code": "..."
  }},
  "preference_reason": ["...", "..."]
}}
```"""
    return prompt


def build_prompt_type_c(pair: dict) -> str:
    """C 类 prompt：复杂长链拆解为 groovy"""
    prompt = f"""你是一个图数据库专家，擅长 Gremlin 和 Groovy 编程。

## 任务
给你一条复杂的长链 Gremlin 查询。请判断：
- 如果这条查询适合拆解为多步 Groovy 写法（更清晰、更易读），请生成 Groovy 版本
- 如果这条查询用 Gremlin 写已经是最优的（无法有意义地拆分），请标记 skip=true

## 原始查询
自然语言: {pair["text"]}
Gremlin: {pair["gremlin"]}

## 要求
1. 如果适合改写：
   - chosen 的 Groovy 写法要把长链拆成多个有意义的中间步骤
   - 用 def 定义中间变量，变量命名清晰
   - 最后返回结果
   - preference_reason 说明为什么拆解后更好
2. 如果不适合改写（skip=true）：
   - chosen 和 preference_reason 可以不填
   - 不要强行包一层 Groovy
3. **禁止注释**：代码中不要包含任何注释（// 或 /* */），只输出纯代码

## 输出格式（严格 JSON）

适合改写时：
```json
{{
  "skip": false,
  "chosen": {{
    "style": "groovy",
    "code": "..."
  }},
  "preference_reason": ["...", "..."]
}}
```

不适合改写时：
```json
{{
  "skip": true
}}
```"""
    return prompt


async def call_llm(
    client: AsyncOpenAI,
    prompt: str,
    llm_config: dict,
    max_connection_retries: int = 5,
) -> str:
    """统一的 LLM 调用，返回原始文本内容，带连接错误重试"""
    from openai import APIConnectionError, APITimeoutError, RateLimitError

    for attempt in range(max_connection_retries):
        try:
            response = await client.chat.completions.create(
                model=llm_config["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=llm_config["temperature"],
            )
            content = response.choices[0].message.content

            if not content or not content.strip():
                raise ValueError("LLM 返回内容为空")
            return content
        except (APIConnectionError, APITimeoutError, RateLimitError):
            if attempt < max_connection_retries - 1:
                wait_time = 2 ** (attempt + 1)
                await asyncio.sleep(wait_time)
                continue
            raise


def extract_json(content: str) -> dict:
    """从 LLM 返回内容中提取 JSON"""
    json_str = content
    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0]
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0]
    return json.loads(json_str.strip())


def extract_gremlin_from_groovy(groovy_code: str) -> list[str]:
    """从 Groovy 代码中提取所有 g.V()/g.E()/g.addV() 等 Gremlin 语句"""
    import re

    gremlins = []
    # 匹配 g.V()... 或 g.E()... 或 g.addV()... 等模式
    pattern = r"g\.[VEa][^;}\n]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*\([^)]*\))*"
    matches = re.findall(pattern, groovy_code)
    for m in matches:
        # 清理末尾的 .next() 或 .toList() 等 Groovy 特有方法
        cleaned = re.sub(r"\.(next|toList|iterate|tryNext)\(\)$", "", m.strip())
        if cleaned:
            gremlins.append(cleaned)
    return gremlins


def validate_gremlin_code(code: str, style: str) -> tuple[bool, str]:
    """验证代码中的 Gremlin 语法

    Args:
        code: 代码内容
        style: "gremlin" 或 "groovy"

    Returns:
        (is_valid, error_message)
    """
    if style == "gremlin":
        # 纯 Gremlin，直接检查
        return check_gremlin_syntax(code)
    # elif style == "groovy":
    #     # Groovy 代码，提取其中的 Gremlin 语句检查
    #     gremlins = extract_gremlin_from_groovy(code)
    #     if not gremlins:
    #         # 没有提取到 Gremlin，可能是纯 Groovy 逻辑，跳过检查
    #         return True, "No Gremlin found in Groovy code"

    #     for g in gremlins:
    #         ok, msg = check_gremlin_syntax(g)
    #         if not ok:
    #             return False, f"Gremlin syntax error in: {g[:50]}... - {msg}"
    #     return True, "All Gremlin statements OK"
    elif style == "groovy":
        # Groovy 代码中的 Gremlin 会使用变量名，ANTLR 纯 Gremlin 语法解析器无法识别
        # 跳过 Groovy 中的 Gremlin 语法检查
        return True, "Groovy code, skipped ANTLR check"
    else:
        return True, "Unknown style, skipped"


def _error_result(task_id: str, task_type: str, domain: str, error: str) -> dict:
    """生成错误结果"""
    return {
        "task_id": task_id,
        "task_type": task_type,
        "domain": domain,
        "_error": error,
    }


# ---- 单条任务处理 ----


async def process_type_a(
    client: AsyncOpenAI,
    task: dict,
    semaphore: asyncio.Semaphore,
    llm_config: dict,
) -> dict | None:
    """处理 A 类任务：多任务组合"""
    max_retries = llm_config["max_retries"]
    domain = task.get("domain", "movie")

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_prompt_type_a(task["pairs"])
                content = await call_llm(client, prompt, llm_config)
                data = extract_json(content)

                # 先用支持拒绝的模型验证
                validated = DPOSampleAWithReject(**data)

                # 如果 LLM 拒绝合成
                if validated.reject:
                    return {
                        "task_id": task["task_id"],
                        "task_type": "A",
                        "domain": domain,
                        "source_queries": [{"text": p["text"], "gremlin": p["gremlin"]} for p in task["pairs"]],
                        "_rejected": True,
                        "_reject_reason": validated.reject_reason or "LLM 拒绝合成",
                    }

                # 验证必要字段
                if not validated.instruction or not validated.chosen or not validated.rejected:
                    raise ValueError("reject=false 但缺少必要字段")

                # 语法检查：A 类必须检查
                # 检查 rejected（纯 Gremlin）
                ok, msg = validate_gremlin_code(validated.rejected.code, validated.rejected.style)
                if not ok:
                    raise ValueError(f"rejected Gremlin 语法错误: {msg}")

                # 检查 chosen（Groovy 中的 Gremlin）
                ok, msg = validate_gremlin_code(validated.chosen.code, validated.chosen.style)
                if not ok:
                    raise ValueError(f"chosen Groovy 中 Gremlin 语法错误: {msg}")

                return {
                    "task_id": task["task_id"],
                    "task_type": "A",
                    "domain": domain,
                    "source_queries": [{"text": p["text"], "gremlin": p["gremlin"]} for p in task["pairs"]],
                    "input": {"instruction": validated.instruction},
                    "chosen": validated.chosen.model_dump(),
                    "rejected": validated.rejected.model_dump(),
                    "preference_reason": validated.preference_reason,
                }
            except (json.JSONDecodeError, ValueError, KeyError, ValidationError) as e:
                if attempt < max_retries - 1:
                    continue
                return _error_result(task["task_id"], "A", domain, f"A 类失败(重试{max_retries}次): {e}")
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                return _error_result(task["task_id"], "A", domain, f"A 类异常(重试{max_retries}次): {e}")


async def process_type_b(
    client: AsyncOpenAI,
    task: dict,
    semaphore: asyncio.Semaphore,
    llm_config: dict,
) -> dict | None:
    """处理 B 类任务：单任务，纯 gremlin 更好"""
    max_retries = llm_config["max_retries"]
    pair = task["pair"]
    domain = task.get("domain", "movie")

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_prompt_type_b(pair)
                content = await call_llm(client, prompt, llm_config)
                data = extract_json(content)
                validated = DPOSampleB(**data)

                # B 类语法检查：检查 LLM 生成的 chosen（应该是原始 gremlin）和 rejected（groovy）
                # chosen 是原始 gremlin，理论上已经验证过，但 LLM 可能抄错
                ok, msg = validate_gremlin_code(validated.chosen.code, validated.chosen.style)
                if not ok:
                    raise ValueError(f"chosen Gremlin 语法错误: {msg}")

                # rejected 是 groovy，检查其中的 gremlin
                ok, msg = validate_gremlin_code(validated.rejected.code, validated.rejected.style)
                if not ok:
                    raise ValueError(f"rejected Groovy 中 Gremlin 语法错误: {msg}")

                return {
                    "task_id": task["task_id"],
                    "task_type": "B",
                    "domain": domain,
                    "input": {"instruction": pair["text"]},
                    "chosen": validated.chosen.model_dump(),
                    "rejected": validated.rejected.model_dump(),
                    "preference_reason": validated.preference_reason,
                }
            except (json.JSONDecodeError, ValueError, KeyError, ValidationError) as e:
                if attempt < max_retries - 1:
                    continue
                return _error_result(task["task_id"], "B", domain, f"B 类失败(重试{max_retries}次): {e}")
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                return _error_result(task["task_id"], "B", domain, f"B 类异常(重试{max_retries}次): {e}")


async def process_type_c(
    client: AsyncOpenAI,
    task: dict,
    semaphore: asyncio.Semaphore,
    llm_config: dict,
) -> dict | None:
    """处理 C 类任务：复杂长链拆解"""
    max_retries = llm_config["max_retries"]
    pair = task["pair"]
    domain = task.get("domain", "movie")

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_prompt_type_c(pair)
                content = await call_llm(client, prompt, llm_config)
                data = extract_json(content)
                validated = DPOSampleCWithSkip(**data)

                if validated.skip:
                    return None

                if not validated.chosen or not validated.preference_reason:
                    raise ValueError("skip=false 但缺少 chosen 或 preference_reason")

                # C 类语法检查：检查 LLM 生成的 chosen（groovy）
                ok, msg = validate_gremlin_code(validated.chosen.code, validated.chosen.style)
                if not ok:
                    raise ValueError(f"chosen Groovy 中 Gremlin 语法错误: {msg}")

                return {
                    "task_id": task["task_id"],
                    "task_type": "C",
                    "domain": domain,
                    "input": {"instruction": pair["text"]},
                    "chosen": validated.chosen.model_dump(),
                    "rejected": {
                        "style": "gremlin",
                        "code": pair["gremlin"],
                    },
                    "preference_reason": validated.preference_reason,
                }
            except (json.JSONDecodeError, ValueError, KeyError, ValidationError) as e:
                if attempt < max_retries - 1:
                    continue
                return _error_result(task["task_id"], "C", domain, f"C 类失败(重试{max_retries}次): {e}")
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                return _error_result(task["task_id"], "C", domain, f"C 类异常(重试{max_retries}次): {e}")


def prepare_tasks(
    classified: dict,
    num_a: int,
    num_b: int,
    num_c: int | None = None,
    domain: str = "movie",
    check_duplicate_gremlin: bool = False,
) -> list[dict]:
    """准备所有任务。

    Args:
        classified: 分类后的数据
        num_a: A 类任务数量
        num_b: B 类任务数量
        num_c: C 类任务数量（默认 None 表示使用所有长链）
        domain: 领域名称
        check_duplicate_gremlin: 是否检查重复 gremlin（用于迁移领域的 A 类任务）
    """
    tasks = []
    task_counter = 0
    domain_prefix = domain[:4].upper()  # 取前4个字符作为前缀

    short_pairs = classified["short"]
    long_pairs = classified["long"]
    medium_pairs = classified["medium"]

    # A 类：从 short 中选取相关组
    for _i in range(num_a):
        n = random.randint(2, 5)
        group = select_related_group(short_pairs, n, check_duplicate_gremlin=check_duplicate_gremlin)
        if len(group) < 2:  # 至少需要 2 条才能组合
            continue
        task_counter += 1
        tasks.append(
            {
                "task_id": f"pref_{domain_prefix}_A_{task_counter:04d}",
                "type": "A",
                "domain": domain,
                "pairs": group,
            }
        )

    # B 类：从 short + medium 中选单条
    b_pool = short_pairs + medium_pairs
    b_selected = random.sample(b_pool, min(num_b, len(b_pool)))
    for pair in b_selected:
        task_counter += 1
        tasks.append(
            {
                "task_id": f"pref_{domain_prefix}_B_{task_counter:04d}",
                "type": "B",
                "domain": domain,
                "pair": pair,
            }
        )

    # C 类：从 long 中选取（如果指定了 num_c 则随机选取，否则全部）
    c_selected = random.sample(long_pairs, num_c) if num_c is not None and num_c < len(long_pairs) else long_pairs

    for pair in c_selected:
        task_counter += 1
        tasks.append(
            {
                "task_id": f"pref_{domain_prefix}_C_{task_counter:04d}",
                "type": "C",
                "domain": domain,
                "pair": pair,
            }
        )

    return tasks


async def run_pipeline(
    tasks: list[dict],
    llm_config: dict,
    output_path: str,
    input_path: str,
    save_interval: int = 50,
    migrated_path: str | None = None,
) -> list[dict]:
    """流水线并发处理所有任务"""
    req_timeout = llm_config.get("timeout", 40)
    client = AsyncOpenAI(
        base_url=llm_config["base_url"],
        api_key=llm_config["api_key"],
        timeout=req_timeout,
    )

    semaphore = asyncio.Semaphore(llm_config["max_concurrency"])
    handler_map = {"A": process_type_a, "B": process_type_b, "C": process_type_c}

    results = []
    completed = 0
    last_save = 0
    skipped = 0
    start_time = time.time()

    print(f"  共 {len(tasks)} 个任务")
    print("  已加载 LLM 运行配置（敏感字段不显示）")
    print("  已启用增量保存")

    # 分批处理，每批最多 100 个任务
    batch_size = 100
    task_queue = list(tasks)

    pending = set()
    task_index = 0

    def add_tasks(n: int):
        """添加 n 个新任务到 pending 集合"""
        nonlocal task_index
        added = 0
        while task_index < len(task_queue) and added < n:
            task = task_queue[task_index]
            handler = handler_map[task["type"]]
            coro = handler(client, task, semaphore, llm_config)
            async_task = asyncio.create_task(coro)
            pending.add(async_task)
            task_index += 1
            added += 1

    # 初始添加一批任务
    add_tasks(batch_size)

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            result = task.result()
            completed += 1

            if result is None:
                skipped += 1
            else:
                results.append(result)

            elapsed = time.time() - start_time
            speed = completed / elapsed if elapsed > 0 else 0
            # 统计：有效样本（无 _error 且无 _rejected）
            valid = len([r for r in results if "_error" not in r and "_rejected" not in r])
            rejected = len([r for r in results if "_rejected" in r])
            print(
                f"\r  进度: {completed}/{len(task_queue)} (有效:{valid} 拒绝:{rejected} 跳过:{skipped} {speed:.1f}条/秒)",
                end="",
                flush=True,
            )

            if len(results) - last_save >= save_interval and results:
                _incremental_save(results, output_path, input_path, elapsed, migrated_path)
                last_save = len(results)
                print(" [已保存]", end="", flush=True)

        # 补充新任务，保持 pending 队列有足够的任务
        if task_index < len(task_queue):
            add_tasks(len(done))

    print()
    return results


def _incremental_save(
    results: list[dict], output_path: str, input_path: str, elapsed: float, migrated_path: str | None = None
):
    # 分类：成功、拒绝、错误（拒绝的不保存到文件）
    success = [r for r in results if "_error" not in r and "_rejected" not in r]
    rejected_count = sum(1 for r in results if "_rejected" in r)
    errors = [r for r in results if "_error" in r]

    type_counts = {}
    domain_counts = {}
    for r in success:
        t = r.get("task_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
        d = r.get("domain", "?")
        domain_counts[d] = domain_counts.get(d, 0) + 1

    output_data = {
        "metadata": {
            "source_file": input_path,
            "migrated_file": migrated_path,
            "total_samples": len(success),
            "rejected_count": rejected_count,
            "error_count": len(errors),
            "type_distribution": type_counts,
            "domain_distribution": domain_counts,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "in_progress",
        },
        "samples": success,
        "errors": errors,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def save_results(
    results: list[dict], output_path: str, input_path: str, elapsed: float, migrated_path: str | None = None
):
    # 分类：成功、拒绝、错误（拒绝的不保存到文件）
    success = [r for r in results if "_error" not in r and "_rejected" not in r]
    rejected_count = sum(1 for r in results if "_rejected" in r)
    errors = [r for r in results if "_error" in r]

    type_counts = {}
    domain_counts = {}
    for r in success:
        t = r.get("task_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
        d = r.get("domain", "?")
        domain_counts[d] = domain_counts.get(d, 0) + 1

    output_data = {
        "metadata": {
            "source_file": input_path,
            "migrated_file": migrated_path,
            "total_samples": len(success),
            "rejected_count": rejected_count,
            "error_count": len(errors),
            "type_distribution": type_counts,
            "domain_distribution": domain_counts,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "completed",
        },
        "samples": success,
        "errors": errors,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="生成 DPO 偏好训练数据 (Groovy vs Gremlin)")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--input", default=None, help="text2gremlin 数据文件 (movie 领域)")
    parser.add_argument("--migrated", default=None, help="迁移数据文件 (20 个领域)")
    parser.add_argument("--output", default=None, help="输出文件路径")
    # 默认参数说明：
    # - 目标有效总量：7000-8000 条
    # - A 类是主力，约 50% 拒绝率
    # - B 类有效约 2000 条
    # - C 类有效约 2000 条（15% 跳过率）
    # 预估有效总量：
    #   A 类: 7000 任务 × 50% = 3500 有效 (46.7%)
    #   B 类: 2000 任务 = 2000 有效 (26.7%)
    #   C 类: 2353 任务 × 85% = 2000 有效 (26.7%)
    #   总计约 7,500 有效样本
    parser.add_argument("--num-a", type=int, default=350, help="A 类任务数量（多任务组合，movie 领域）")
    parser.add_argument("--num-b", type=int, default=100, help="B 类任务数量（单任务，movie 领域）")
    parser.add_argument("--num-c", type=int, default=72, help="C 类任务数量（长链拆解，movie 领域）")
    parser.add_argument("--migrated-num-a", type=int, default=333, help="每个迁移领域的 A 类任务数量")
    parser.add_argument("--migrated-num-b", type=int, default=95, help="每个迁移领域的 B 类任务数量")
    parser.add_argument("--migrated-num-c", type=int, default=115, help="每个迁移领域的 C 类任务数量")
    parser.add_argument("--skip-movie", action="store_true", help="跳过 movie 领域，只处理迁移领域")
    parser.add_argument("--skip-migrated", action="store_true", help="跳过迁移领域，只处理 movie 领域")
    args = parser.parse_args()

    config = load_config(args.config)
    llm_config = get_llm_config(config)
    output_dir = config.get("output_dir", "output")

    # 确定输出路径
    output_path = args.output
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pref_dir = os.path.join(output_dir, "preference_data")
        output_path = os.path.join(pref_dir, f"dpo_data_{timestamp}.json")

    all_tasks = []
    input_path = None
    migrated_path = None

    # 处理 movie 领域
    if not args.skip_movie:
        input_path = args.input or find_latest_pairs(output_dir)
        if input_path and os.path.exists(input_path):
            pairs = load_pairs(input_path)
            if pairs:
                classified = classify_pairs(pairs)
                num_a = args.num_a
                num_b = args.num_b
                num_c = args.num_c

                movie_tasks = prepare_tasks(
                    classified, num_a, num_b, num_c=num_c, domain="movie", check_duplicate_gremlin=False
                )

                actual_c = len(classified["long"]) if num_c is None else min(num_c, len(classified["long"]))
                print("\n📊 Movie 领域数据分类:")
                print(f"  短查询 (≤5步): {len(classified['short'])} 条 → A/B 类")
                print(f"  中等查询 (6-8步): {len(classified['medium'])} 条 → B 类")
                print(f"  长查询 (>8步): {len(classified['long'])} 条 → C 类")
                print(f"  任务数: A={num_a}, B={num_b}, C={actual_c}")
                print(f"  总计: {len(movie_tasks)} 个任务")

                all_tasks.extend(movie_tasks)
            else:
                print(f"⚠️ Movie 数据文件为空: {input_path}")
        else:
            print("⚠️ 未找到 movie 领域数据文件")

    # 处理 20 个迁移领域
    if not args.skip_migrated:
        migrated_path = args.migrated or find_latest_migrated(output_dir)
        if migrated_path and os.path.exists(migrated_path):
            domain_data = load_migrated_data(migrated_path)

            if domain_data:
                migrated_num_a = args.migrated_num_a
                migrated_num_b = args.migrated_num_b
                migrated_num_c = args.migrated_num_c

                c_desc = "全部" if migrated_num_c is None else str(migrated_num_c)
                print(f"\n📊 迁移领域数据 ({len(domain_data)} 个领域):")
                print(f"  每领域任务数: A={migrated_num_a}, B={migrated_num_b}, C={c_desc}")

                for domain, pairs in sorted(domain_data.items()):
                    # 为每个领域的数据分类
                    classified = classify_pairs(pairs)

                    # 迁移领域需要检查重复 gremlin（因为同一查询有多种语气版本）
                    domain_tasks = prepare_tasks(
                        classified,
                        migrated_num_a,
                        migrated_num_b,
                        num_c=migrated_num_c,
                        domain=domain,
                        check_duplicate_gremlin=True,
                    )

                    print(
                        f"  {domain}: {len(pairs)} 条数据 → "
                        f"short={len(classified['short'])}, "
                        f"medium={len(classified['medium'])}, "
                        f"long={len(classified['long'])} → "
                        f"{len(domain_tasks)} 任务"
                    )

                    all_tasks.extend(domain_tasks)
            else:
                print(f"⚠️ 迁移数据文件为空: {migrated_path}")
        else:
            print("⚠️ 未找到迁移数据文件")

    if not all_tasks:
        print("❌ 没有任务可执行")
        sys.exit(1)

    # 打乱所有任务
    random.shuffle(all_tasks)

    # 统计任务分布
    task_type_counts = {}
    domain_counts = {}
    for t in all_tasks:
        task_type_counts[t["type"]] = task_type_counts.get(t["type"], 0) + 1
        domain_counts[t.get("domain", "?")] = domain_counts.get(t.get("domain", "?"), 0) + 1

    print("\n" + "=" * 60)
    print("🚀 DPO 偏好数据生成器")
    print("=" * 60)
    print("\n📋 配置:")
    print(f"  Movie 数据: {input_path or '无'}")
    print(f"  迁移数据: {migrated_path or '无'}")
    print(f"  输出文件: {output_path}")
    print("  LLM 配置: 已加载（敏感字段不显示）")
    print("  重试与保存策略: 使用配置文件设置")
    print("\n📊 任务分布:")
    print(f"  类型: {task_type_counts}")
    print(f"  领域: {len(domain_counts)} 个")
    print(f"  总计: {len(all_tasks)} 个任务")
    print("-" * 60)

    start_time = time.time()
    results = asyncio.run(
        run_pipeline(
            all_tasks,
            llm_config,
            output_path,
            input_path or "",
            save_interval=llm_config["save_interval"],
            migrated_path=migrated_path,
        )
    )
    elapsed = time.time() - start_time

    save_results(results, output_path, input_path or "", elapsed, migrated_path)

    # 分类统计
    success = [r for r in results if "_error" not in r and "_rejected" not in r]
    rejected = [r for r in results if "_rejected" in r]
    errors = [r for r in results if "_error" in r]

    type_counts = {}
    domain_counts = {}
    for r in success:
        t = r.get("task_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
        d = r.get("domain", "?")
        domain_counts[d] = domain_counts.get(d, 0) + 1

    print("\n" + "=" * 60)
    print("✅ DPO 数据生成完成")
    print("=" * 60)
    print(f"  总耗时: {elapsed:.2f} 秒")
    print(f"  有效样本: {len(success)}")
    print(f"  拒绝合成: {len(rejected)} (命令冲突/无法合成)")
    print(f"  调用失败: {len(errors)}")
    print(f"  类型分布: {type_counts}")
    print(f"  领域数: {len(domain_counts)}")
    print(f"  吞吐量: {len(results) / elapsed:.2f} 条/秒" if elapsed > 0 else "")
    print(f"\n💾 结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
