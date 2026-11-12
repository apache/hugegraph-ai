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

# ============================================================================
# Context Precision: Per-context relevance binary judgment
# Reference: RAGAS ContextPrecisionPrompt
# ============================================================================

CONTEXT_PRECISION_PROMPT = """\
Given a question and a ground truth answer, determine whether the following \
context passage is useful for correctly answering the question.

Example 1:
Question: What can you tell me about Albert Einstein?
Ground Truth: Albert Einstein, born on 14 March 1879, was a German-born \
theoretical physicist, widely held to be one of the greatest scientists of \
all time. He received the 1921 Nobel Prize in Physics.
Context: Albert Einstein (14 March 1879 - 18 April 1955) was a German-born \
theoretical physicist, widely held to be one of the greatest and most \
influential scientists of all time. Best known for developing the theory of \
relativity, he also made important contributions to quantum mechanics.

Output: {{"verdict": "Yes"}}

Example 2:
Question: What is the tallest mountain in the world?
Ground Truth: Mount Everest is the tallest mountain in the world.
Context: The Andes is the longest continental mountain range in the world, \
located in South America. It features many of the highest peaks in the \
Western Hemisphere.

Output: {{"verdict": "No"}}

Now evaluate:
Question: {question}
Ground Truth Answer: {ground_truth}
Context Passage: {context}

Output format: Return a JSON object with a single key "verdict" \
containing "Yes" or "No".
Return no explanation, additional keys, or additional text.
"""

_CONTEXT_PRECISION_PROMPT_ZH = """\
给定一个问题和对应的标准答案，请判断下面的上下文段落是否有助于正确回答该问题。

示例 1：
问题：你能告诉我关于阿尔伯特·爱因斯坦的什么信息？
标准答案：阿尔伯特·爱因斯坦，1879 年 3 月 14 日出生，是一位出生于德国的理论物理学家，\
被广泛认为是有史以来最伟大的科学家之一。他获得了 1921 年的诺贝尔物理学奖。
上下文：阿尔伯特·爱因斯坦（1879 年 3 月 14 日—1955 年 4 月 18 日）是一位出生于德国的理论物理学家，\
被广泛认为是有史以来最伟大、最具影响力的科学家之一。他因提出相对论而闻名，\
还对量子力学做出了重要贡献。

输出：{{"verdict": "Yes"}}

示例 2：
问题：世界上最高的山是什么？
标准答案：珠穆朗玛峰是世界上最高的山。
上下文：安第斯山脉是世界上最长的陆地山脉，位于南美洲。它拥有西半球许多最高的山峰。

输出：{{"verdict": "No"}}

现在请评估：
问题：{question}
标准答案：{ground_truth}
上下文段落：{context}

输出格式：返回一个 JSON 对象，包含唯一的键 "verdict"，其值为 "Yes" 或 "No"。
不得返回解释、其他键或其他文本。
"""

# ============================================================================
# Context Relevancy: Per-context graded relevance score (0-2)
# Reference: GraphRAG-Benchmark context_relevance.py
# ============================================================================

CONTEXT_RELEVANCE_PROMPT = """\
### Instructions
You are a world class expert designed to evaluate the relevance score of a \
Context in order to answer the Question.
Your task is to determine if the Context contains proper information to \
answer the Question.
Do not rely on your previous knowledge about the Question.
Use only what is written in the Context and in the Question.

Scoring rules:
0. If the context does not contain any relevant information to answer the \
question, score 0.
1. If the context partially contains relevant information to answer the \
question, score 1.
2. If the context fully contains relevant information to answer the question, \
score 2.

Output format:
You must output strictly in JSON format with a single key "score".
No explanation, no additional text.
The score must be exactly one of 0, 1, or 2.

Example:
Question: What is the capital of France?
Context: Paris is the capital of France.
Output:
{{ "score": 2 }}

Now evaluate the following:
Question: {question}
Context: {context}
"""

_CONTEXT_RELEVANCE_PROMPT_ZH = """\
### 指令
你是一位顶尖专家，负责评估“上下文”对回答“问题”的相关性得分。
你的任务是判断上下文是否包含回答该问题的恰当信息。
请不要依赖你对该问题的先验知识，仅使用上下文和问题中明确写出的内容。

评分规则：
0. 如果上下文不包含任何回答问题的相关信息，得分为 0。
1. 如果上下文包含部分回答问题的相关信息，得分为 1。
2. 如果上下文包含完整回答问题的相关信息，得分为 2。

输出格式：
你必须严格以 JSON 格式输出，只包含一个键 "score"。
不要解释，不要附加任何其他文本。
得分必须严格为 0、1 或 2 之一。

示例：
问题：法国的首都是哪里？
上下文：巴黎是法国的首都。
输出：
{{ "score": 2 }}

现在请评估以下内容：
问题：{question}
上下文：{context}
"""

# ============================================================================
# Entity Extraction (Context Entity Recall)
# Reference: RAGAS ContextEntityRecall (ExtractEntitiesPrompt)
# ============================================================================

ENTITY_EXTRACT_PROMPT = """\
Given a text, extract unique entities without repetition. Ensure you consider \
different forms or mentions of the same entity as a single entity. An entity \
is any named or specifically-identified concept the text treats as a \
discrete thing — this includes persons, locations, organizations, dates, \
monetary amounts, and other proper nouns, but is NOT limited to that list. \
In domain-specific text (e.g. a service manual), entities also include named \
components, parts, statuses/warning indicators, and specifications/parameters \
(e.g. "auth service", "auth timeout alarm", "timeout 5s").

Example:
Text: The Eiffel Tower, located in Paris, France, is one of the most iconic \
landmarks globally. Completed in 1889, it was constructed in time for the \
1889 World's Fair.

Output:
{{
  "entities": ["Eiffel Tower", "Paris", "France", "1889", "World's Fair"]
}}

Now do the same for:
Text: {text}

Output format: Return a JSON object with a single key "entities" containing \
a list of strings, each a unique named entity. Return no additional keys or text.
"""

_ENTITY_EXTRACT_PROMPT_ZH = """\
给定一段文本，请提取其中不重复的唯一实体。同一实体的不同表述形式或提法\
应视为同一个实体。实体是文本中被当作独立概念对待的、有名称或可具体指代的\
事物——包括但不限于人名、地名、组织机构名、日期、金额及其他专有名词。\
在领域文本中（例如服务运维手册），实体还包括具名的部件/零件、状态或告警指示、\
规格参数（例如"认证服务"、"认证超时告警"、"响应超时5秒"）。

示例：
文本：埃菲尔铁塔位于法国巴黎，是全球最具标志性的地标之一。它于1889年建成，\
是为1889年世界博览会而修建的。

输出：
{{
  "entities": ["埃菲尔铁塔", "巴黎", "法国", "1889年", "世界博览会"]
}}

现在请对以下内容做同样处理：
文本：{text}

输出格式：返回一个 JSON 对象，包含唯一的键 "entities"，其值为字符串列表，\
每个字符串是一个唯一命名实体。不得返回其他键或文本。
"""

# ============================================================================
# Evidence Recall: Gold evidence support verification
# Reference: GraphRAG-Bench evidence_recall.py
# ============================================================================
EVIDENCE_RECALL_PROMPT = """\
### Task
You are given a list of evidences and a Context. For each evidence, determine \
whether it can be attributed to the Context.

Respond ONLY with a JSON object containing a "classifications" list. Each \
item should include:
- "statement": the exact evidence string
- "reason": a brief explanation (1 sentence)
- "attributed": 1 if the evidence can be attributed to the Context, otherwise 0
Return exactly one classification for each evidence item, preserve each \
statement verbatim, and return no additional keys or text.

### Example
Input:
Context: "Einstein won the Nobel Prize in 1921 for physics."
Evidence: ["Einstein received the Nobel Prize", "He was born in Germany"]

Output:
{{
  "classifications": [
    {{
      "statement": "Einstein received the Nobel Prize",
      "reason": "Matches context about Nobel Prize for physics in 1921.",
      "attributed": 1
    }},
    {{
      "statement": "He was born in Germany",
      "reason": "Birth information not present in context.",
      "attributed": 0
    }}
  ]
}}

### Actual Input
Context: "{context}"
Evidence: {evidence}
Question: "{question}" (for reference only)

### Your Response:
"""

_EVIDENCE_RECALL_PROMPT_ZH = """\
### 任务
给定一组证据和一个上下文，请判断每条证据是否可以从该上下文中得到归因。

请只返回一个 JSON 对象，其中包含 "classifications" 列表。每个条目包括：
- "statement"：证据的原文
- "reason"：简要说明（一句话）
- "attributed"：如果证据可以从上下文中得到归因则为 1，否则为 0
必须为每条证据恰好返回一个分类，保留每条证据原文，不得返回其他键或文本。

### 示例
输入：
上下文："爱因斯坦于 1921 年获得了诺贝尔物理学奖。"
证据：["爱因斯坦获得了诺贝尔奖", "他出生于德国"]

输出：
{{
  "classifications": [
    {{
      "statement": "爱因斯坦获得了诺贝尔奖",
      "reason": "与上下文中关于 1921 年获得诺贝尔物理学奖的信息一致。",
      "attributed": 1
    }},
    {{
      "statement": "他出生于德国",
      "reason": "上下文中没有关于出生地的信息。",
      "attributed": 0
    }}
  ]
}}

### 实际输入
上下文："{context}"
证据：{evidence}
问题："{question}"（仅供参考）

### 你的回答：
"""


# ============================================================================
# Claim Decomposition (Factual Correctness — bidirectional precision/recall)
# Reference: RAGAS ClaimDecompositionPrompt (factual_correctness)
# ============================================================================

CLAIM_DECOMPOSE_PROMPT = """\
You are given a question and a piece of text. Break down the text \
into a list of distinct, independently verifiable claims. \
Each claim should be a standalone assertion that can be checked on its own.

Example:
Question: What causes seasons?
Text: "Seasonal changes result from Earth's axial tilt. This tilt \
causes different hemispheres to receive varying sunlight."

Output:
{{
  "facts": [
    "Seasonal changes result from Earth's axial tilt",
    "The axial tilt causes different hemispheres to receive varying sunlight"
  ]
}}

Now do the same for:
Question: {question}
Text: {reference}

Output format: Return a JSON object with a single key "facts" containing a list \
of strings, each being an independently verifiable claim.
Return no additional keys or text.
"""

_CLAIM_DECOMPOSE_PROMPT_ZH = """\
给定一个问题和一段文本，请将该文本拆分为一系列独立的、可单独验证的\
主张（facts）。每个主张必须是可独立核查的完整断言。

示例：
问题：季节更替是由什么引起的？
文本："季节变化由地球自转轴倾斜造成。这种倾斜导致不同半球接收到的阳光不同。"

输出：
{{
  "facts": [
    "季节变化由地球自转轴倾斜造成",
    "自转轴倾斜导致不同半球接收到不同的阳光"
  ]
}}

现在请对以下内容做同样处理：
问题：{question}
文本：{reference}

输出格式：返回一个 JSON 对象，包含唯一的键 "facts"，其值为字符串列表，\
每个字符串是一个可独立验证的主张。
不得返回其他键或文本。
"""
