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

# Prompt text stays on one line so the rendered instruction remains auditable.
# ruff: noqa: E501

# ============================================================================
# Entity Semantic Match (Graph Extraction — LLM-based)
# Judges whether each candidate vertex semantically matches any gold vertex.
# ============================================================================

ENTITY_SEMANTIC_MATCH_PROMPT = """\
Your task is to judge whether candidate entities (from an automated KG extractor)
semantically match gold entities (from human annotation).

For each candidate entity, determine if it is semantically equivalent to any
gold entity of the SAME type. The gold entity list is the reference standard.

Matching rules:
- Entity TYPE (label) must match exactly. Component ≠ Function, Status ≠ Specification.
- Entity NAME allows: synonym normalization, abbreviation expansion, phrasing variation.
  Example: "认证服务" matches "认证服务巡检" (same core concept, different granularity).
- Each gold entity can be matched at most once.
- Each candidate entity can be matched at most once.
- If two candidate entities match the same gold entity, the first one wins.
- Special case: A status Component in the gold that is expressed as
  Status in the candidate may still match if the semantic signal is identical
  (e.g., gold "Status(认证超时告警)" ↔ candidate "Status(认证服务超时指示)").

Return a JSON object with:
- "matches": list of objects with "candidate_index" and "gold_index" (0-indexed)
- "reasoning": brief explanation (1-2 sentences)
Indices must refer to the lists in the actual input, and each index may appear \
at most once. Return no additional keys or text.
The "reasoning" value is required even when no matches are found. Return no \
additional keys or text.

IMPORTANT: Do NOT match by position order. Candidate [0] does NOT necessarily match \
gold [0]. You MUST compare semantics across all pairs, regardless of index.

Example:
Gold entities (indexed):
[0] {{"label": "Status", "name": "认证超时告警"}}
[1] {{"label": "Component", "name": "认证服务"}}
[2] {{"label": "Specification", "name": "响应超时_5s"}}
[3] {{"label": "Component", "name": "缓存服务"}}

Candidate entities (indexed):
[0] {{"label": "Component", "name": "缓存命中率"}}
[1] {{"label": "Status", "name": "认证服务超时指示灯"}}
[2] {{"label": "Component", "name": "认证服务巡检"}}
[3] {{"label": "Specification", "name": "并发上限_1000"}}

Expected JSON:
{{
  "matches": [{{"candidate_index": 1, "gold_index": 0}}, {{"candidate_index": 2, "gold_index": 1}}],
  "reasoning": "Candidate[1] 认证服务超时指示灯 → gold[0] 认证超时告警 (semantic equivalent); \
candidate[2] 认证服务巡检 → gold[1] 认证服务 (core concept match). \
Candidate[0] 缓存命中率 does NOT match gold[3] 缓存服务 — type is Component but 气压 adds unsupported detail making it a different entity. \
Candidate[3] 并发上限_1000 does NOT match gold[2] 响应超时_5s — completely different specifications."
}}

Now evaluate the following:

Gold entities:
{gold_entities}

Candidate entities:
{candidate_entities}

Return only the JSON object.
"""

_ENTITY_SEMANTIC_MATCH_PROMPT_ZH = """\
你的任务是判断候选实体（由自动 KG 抽取器生成）是否与标准答案实体（人工标注）在语义上等价。

针对每个候选实体，判断它是否与同类型的某个标准答案实体语义等价。标准答案实体列表是参考基准。

匹配规则：
- 实体类型（label）必须一致。Component ≠ Function，Status ≠ Specification。
- 实体名称允许：同义词归一、简称展开、表述变化。
  例如："认证服务" 与 "认证服务巡检" 可匹配（核心概念相同，粒度不同）。
- 每个标准答案实体最多被匹配一次。
- 每个候选实体最多被匹配一次。
- 如果两个候选实体匹配同一个标准答案实体，取第一个。
- 特殊情况：标准答案中的状态 Component 在候选答案中以 Status 表达，若语义信号一致可匹配。

返回 JSON 对象，包含：
- "matches"：包含 "candidate_index" 和 "gold_index" 的对象列表（从0开始索引）
- "reasoning"：简要说明（1-2 句中文）
索引必须对应实际输入列表，且每个索引最多出现一次。不得返回其他键或文本。
即使没有匹配项也必须填写非空的 "reasoning"，不得返回其他键或文本。

重要提示：不要按索引顺序匹配。候选 [0] 不一定匹配标准答案 [0]。必须跨所有组合进行语义比对，索引顺序不代表匹配关系。

示例：
标准答案实体（带索引）：
[0] {{"label": "Status", "name": "认证超时告警"}}
[1] {{"label": "Component", "name": "认证服务"}}
[2] {{"label": "Specification", "name": "响应超时_5s"}}
[3] {{"label": "Component", "name": "缓存服务"}}

候选实体（带索引）：
[0] {{"label": "Component", "name": "缓存命中率"}}
[1] {{"label": "Status", "name": "认证服务超时指示灯"}}
[2] {{"label": "Component", "name": "认证服务巡检"}}
[3] {{"label": "Specification", "name": "并发上限_1000"}}

期望输出：
{{
  "matches": [{{"candidate_index": 1, "gold_index": 0}}, {{"candidate_index": 2, "gold_index": 1}}],
  "reasoning": "候选[1] 认证服务超时指示灯→标准答案[0] 认证超时告警（语义等价）；候选[2] 认证服务巡检→标准答案[1] 认证服务（核心概念匹配）。候选[0] 缓存命中率与标准答案[3] 缓存服务不匹配——虽然类型同为 Component，但「气压」引入了额外细节，属于不同实体。候选[3] 并发上限_1000与标准答案[2] 响应超时_5s不匹配——规格含义完全不同。"
}}

现在请评估：

标准答案实体：
{gold_entities}

候选实体：
{candidate_entities}

只返回 JSON 对象。
"""


# ============================================================================
# Triple Semantic Match (Graph Extraction — LLM-based)
# Judges whether each candidate triple (edge) semantically matches any gold triple.
# ============================================================================

TRIPLE_SEMANTIC_MATCH_PROMPT = """\
Your task is to judge whether candidate triples (from an automated KG extractor)
semantically match gold triples (from human annotation).

Each triple is expressed as: [source_entity_name] --relation_type--> [target_entity_name].

A triple match requires ALL of the following:
1. Source entity: semantically equivalent (same rules as entity matching)
2. Relation type: semantically equivalent. Allow synonym relations if clearly
   expressing the same relationship (e.g., HAS_STATUS ≈ SYSTEM_HAS_STATUS).
3. Target entity: semantically equivalent
4. Direction: must be identical (source→target, not reversed)

Matching rules:
- Each gold triple can be matched at most once.
- Each candidate triple can be matched at most once.
- If the relation type differs but the semantic meaning is identical
  (e.g., "HAS_STATUS" for a status carrier vs "HAS_COMPONENT"
  for a physical part), judge based on whether the factual claim is the same.
- Partial matches (e.g., source OK but relation wrong) are NOT counted as matches.

Return a JSON object with:
- "matches": list of objects with "candidate_index" and "gold_index" (0-indexed)
- "reasoning": brief explanation (1-2 sentences)
Indices must refer to the lists in the actual input, and each index may appear \
at most once. Return no additional keys or text.
The "reasoning" value is required even when no matches are found. Return no \
additional keys or text.

IMPORTANT: Do NOT match by position order. Candidate [0] does NOT necessarily match \
gold [0]. You MUST compare semantics across all pairs, regardless of index.

Example:
Gold triples:
[0] [认证服务] --HAS_SPEC--> [超时:5s]
[1] [组合仪表] --HAS_STATUS--> [认证超时告警点亮]
[2] [服务集群] --HAS_COMPONENT--> [鉴权服务]

Candidate triples:
[0] [监控面板] --HAS_STATUS--> [认证超时告警触发]
[1] [认证服务] --HAS_COMPONENT--> [网关服务]
[2] [服务集群] --HAS_COMPONENT--> [鉴权服务]

Expected JSON:
{{
  "matches": [{{"candidate_index": 0, "gold_index": 1}}, {{"candidate_index": 2, "gold_index": 2}}],
  "reasoning": "Candidate[0] 监控面板--HAS_STATUS-->认证超时告警触发 matches gold[1] (source and target semantically equivalent, same relation). \
Candidate[2] 服务集群--HAS_COMPONENT-->鉴权服务 matches gold[2] (服务集群≈服务集群, exact relation and target). \
Candidate[1] 认证服务--HAS_COMPONENT-->网关服务 does NOT match gold[0] 认证服务--HAS_SPEC-->超时:5s — relation and target are completely different factual claims."
}}

Now evaluate:

Gold triples:
{gold_triples}

Candidate triples:
{candidate_triples}

Return only the JSON object.
"""

_TRIPLE_SEMANTIC_MATCH_PROMPT_ZH = """\
你的任务是判断候选三元组（自动 KG 抽取结果）是否与标准答案三元组（人工标注）语义等价。

每个三元组表示为：[源实体名] --关系类型--> [目标实体名]。

一个三元组匹配必须同时满足以下全部条件：
1. 源实体：语义等价（与实体匹配规则相同）
2. 关系类型：语义等价。允许等价关系映射（如 HAS_STATUS ≈ SYSTEM_HAS_STATUS）。
3. 目标实体：语义等价
4. 方向：必须一致（源→目标，不可反向）

匹配规则：
- 每个标准答案三元组最多被匹配一次。
- 每个候选三元组最多被匹配一次。
- 关系类型不同但语义完全一致时，以事实声明是否相同为准。
- 部分匹配（如源实体匹配但关系错误）不算命中。

返回 JSON 对象，包含：
- "matches"：包含 "candidate_index" 和 "gold_index" 的对象列表（从0开始索引）
- "reasoning"：简要说明（1-2 句中文）
索引必须对应实际输入列表，且每个索引最多出现一次。不得返回其他键或文本。
即使没有匹配项也必须填写非空的 "reasoning"，不得返回其他键或文本。

重要提示：不要按索引顺序匹配。候选 [0] 不一定匹配标准答案 [0]。必须跨所有组合进行语义比对，索引顺序不代表匹配关系。

示例：
标准答案三元组：
[0] [认证服务] --HAS_SPEC--> [超时:5s]
[1] [组合仪表] --HAS_STATUS--> [认证超时告警点亮]
[2] [服务集群] --HAS_COMPONENT--> [鉴权服务]

候选三元组：
[0] [监控面板] --HAS_STATUS--> [认证超时告警触发]
[1] [认证服务] --HAS_COMPONENT--> [网关服务]
[2] [服务集群] --HAS_COMPONENT--> [鉴权服务]

期望输出：
{{
  "matches": [{{"candidate_index": 0, "gold_index": 1}}, {{"candidate_index": 2, "gold_index": 2}}],
  "reasoning": "候选[0] 监控面板→认证超时告警触发与标准答案[1]语义等价（源实体和目标均等价，关系一致）；候选[2] 服务集群→鉴权服务与标准答案[2]匹配（服务集群≈服务集群，关系和目标完全一致）；候选[1] 认证服务--HAS_COMPONENT-->网关服务与标准答案[0] 认证服务--HAS_SPEC-->超时:5s不匹配——关系类型和目标实体完全不同，事实声明不同。"
}}

现在请评估：

标准答案三元组：
{gold_triples}

候选三元组：
{candidate_triples}

只返回 JSON 对象。
"""


# ============================================================================
# Answer Relevancy: reverse-question generation + noncommittal detection
# Reference: RAGAS AnswerRelevancePrompt (metrics/collections/answer_relevancy)
# NOT currently wired to a registered metric — see
# metrics/answer/answer_relevancy.py (awaiting an embeddings service).
# ============================================================================

ANSWER_RELEVANCE_PROMPT = """\
Generate a question for the given answer and identify if the answer is \
noncommittal. Give noncommittal as 1 if the answer is noncommittal (evasive, \
vague, or ambiguous) and 0 if the answer is substantive. Examples of \
noncommittal answers: "I don't know", "I'm not sure", "It depends".

Example 1:
Answer: Albert Einstein was born in Germany.
Output:
{{"question": "Where was Albert Einstein born?", "noncommittal": 0}}

Example 2:
Answer: I don't know about the groundbreaking feature of the smartphone \
invented in 2023 as I am unaware of information beyond 2022.
Output:
{{"question": "What was the groundbreaking feature of the smartphone invented in 2023?", "noncommittal": 1}}

Now do the same for:
Answer: {response}

Output format: Return a JSON object with keys "question" (str) and \
"noncommittal" (0 or 1). Return no additional keys or text.
"""

_ANSWER_RELEVANCE_PROMPT_ZH = """\
针对给定的回答生成一个问题，并判断该回答是否为敷衍性回答。若回答是敷衍性的\
（回避、含糊或模棱两可）则 noncommittal 为 1，若回答是实质性的则为 0。\
敷衍性回答示例："我不知道"、"我不确定"、"这要看情况"。

示例 1：
回答：阿尔伯特·爱因斯坦出生于德国。
输出：
{{"question": "阿尔伯特·爱因斯坦出生在哪里？", "noncommittal": 0}}

示例 2：
回答：我不了解 2023 年发明的智能手机的突破性功能，因为我不了解 2022 年之后的信息。
输出：
{{"question": "2023 年发明的智能手机的突破性功能是什么？", "noncommittal": 1}}

现在请对以下内容做同样处理：
回答：{response}

输出格式：返回一个 JSON 对象，包含键 "question"（字符串）和 "noncommittal"\
（0 或 1）。不得返回其他键或文本。
"""
