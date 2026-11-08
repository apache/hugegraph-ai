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

"""Prompt templates for LLM-based evaluation metrics.

All prompts include few-shot examples derived from RAGAS and
GraphRAG-Benchmark (ICLR'26) reference implementations.

Two languages are supported:
- ``en`` (default): English prompts matching the original RAGAS / GraphRAG-Bench
  wording.
- ``zh``: Chinese prompts localized for Chinese technical-document evaluation.

Use :func:`get_prompt` to select the correct template for the current
``language`` setting.
"""


# ============================================================================
# Statement Decomposition (shared by Faithfulness, Answer Correctness)
# Reference: RAGAS StatementGeneratorPrompt + GraphRAG-Bench
# ============================================================================

STATEMENT_DECOMPOSE_PROMPT = """\
Given a question and an answer, break down each sentence in the answer into \
one or more fully understandable atomic statements. Ensure that no pronouns \
are used in any statement. Each statement should be a standalone factual claim \
that can be independently verified.

Example:
Question: Who was Albert Einstein and what is he best known for?
Answer: He was a German-born theoretical physicist, widely acknowledged to \
be one of the greatest and most influential physicists of all time. He was \
best known for developing the theory of relativity, he also made important \
contributions to the development of the theory of quantum mechanics.

Output:
{{
  "statements": [
    "Albert Einstein was a German-born theoretical physicist.",
    "Albert Einstein is recognized as one of the greatest and most influential physicists of all time.",
    "Albert Einstein was best known for developing the theory of relativity.",
    "Albert Einstein also made important contributions to the development of the theory of quantum mechanics."
  ]
}}

Now do the same for:
Question: {question}
Answer: {answer}

Output format: Return a JSON object with a single key "statements" \
containing a list of strings, each being an atomic statement.
Return one statement for each atomic claim, preserve the statement text, and \
return no additional keys or text.
"""

_STATEMENT_DECOMPOSE_PROMPT_ZH = """\
给定一个问题和一个回答，请将回答中的每个句子拆分为一个或多个完整可理解的\
原子陈述。每个陈述必须是独立的、可被单独验证的事实性主张，且不能包含代词。

示例：
问题：阿尔伯特·爱因斯坦是谁，他最著名的是什么？
回答：他是一位出生于德国的理论物理学家，被广泛认为是有史以来最伟大、\
最具影响力的物理学家之一。他因提出相对论而闻名，还对量子力学的发展做出了重要贡献。

输出：
{{
  "statements": [
    "阿尔伯特·爱因斯坦是一位出生于德国的理论物理学家。",
    "阿尔伯特·爱因斯坦被广泛认为是有史以来最伟大、最具影响力的物理学家之一。",
    "阿尔伯特·爱因斯坦因提出相对论而闻名。",
    "阿尔伯特·爱因斯坦还对量子力学的发展做出了重要贡献。"
  ]
}}

现在请对以下内容做同样处理：
问题：{question}
回答：{answer}

输出格式：返回一个 JSON 对象，包含唯一的键 "statements"，其值为字符串列表，\
每个字符串是一个原子陈述。
每个原子主张都必须对应一个陈述，保留陈述原文，不得返回其他键或文本。
"""

# ============================================================================
# Faithfulness: NLI Statement Verification
# Reference: RAGAS NLIStatementPrompt + GraphRAG-Bench faithfulness
# ============================================================================

NLI_STATEMENT_PROMPT = """\
Your task is to judge the faithfulness of a series of statements based on \
a given context. For each statement return verdict "Yes" if it can be \
directly inferred from the context, or "No" if it cannot be directly inferred.

Example 1:
Context: John is a student at XYZ University. He is pursuing a degree in \
Computer Science. He is enrolled in several courses this semester, including \
Data Structures, Algorithms, and Database Management. John is a diligent \
student and spends a significant amount of time studying and completing \
assignments. He often stays late in the library to work on his projects.

Statements:
1. John is majoring in Biology.
2. John is taking a course on Artificial Intelligence.
3. John is a dedicated student.
4. John has a part-time job.

Output:
{{
  "verdicts": [
    {{"statement": "John is majoring in Biology.", "reason": "John's major is explicitly mentioned as Computer Science.", "verdict": "No"}},
    {{"statement": "John is taking a course on Artificial Intelligence.", "reason": "AI is not mentioned in the course list.", "verdict": "No"}},
    {{"statement": "John is a dedicated student.", "reason": "The context states he spends significant time studying and stays late at the library.", "verdict": "Yes"}},
    {{"statement": "John has a part-time job.", "reason": "No information about a part-time job in the context.", "verdict": "No"}}
  ]
}}

Example 2:
Context: Photosynthesis is a process used by plants, algae, and certain \
bacteria to convert light energy into chemical energy.

Statements:
1. Albert Einstein was a genius.

Output:
{{
  "verdicts": [
    {{"statement": "Albert Einstein was a genius.", "reason": "The context and statement are unrelated.", "verdict": "No"}}
  ]
}}

Now evaluate:
Context:
{context}

Statements:
{statements}

Output format: Return a JSON object with a single key "verdicts" \
containing a list of objects, each with "statement" (str), \
"reason" (str), and "verdict" ("Yes" or "No") keys.
Return exactly one verdict object for each numbered statement, preserve the \
statement text, and return no additional keys or text.
"""

_NLI_STATEMENT_PROMPT_ZH = """\
你的任务是根据给定的上下文，判断一系列陈述是否忠实于上下文。对于每个陈述，\
如果它能从上下文中直接推断出来，请返回 verdict 为 "Yes"；如果不能直接从上下文中\
推断出来，请返回 verdict 为 "No"。

示例 1：
上下文：约翰是 XYZ 大学的学生，正在攻读计算机科学学位。本学期他选修了多门课程，\
包括数据结构、算法和数据库管理。约翰是一名勤奋的学生，花费大量时间学习和完成作业。\
他经常待在图书馆里熬夜做项目。

陈述：
1. 约翰主修生物学。
2. 约翰正在修一门人工智能课程。
3. 约翰是一名用功的学生。
4. 约翰有一份兼职工作。

输出：
{{
  "verdicts": [
    {{"statement": "约翰主修生物学。", "reason": "上下文中明确说明约翰的专业是计算机科学。", "verdict": "No"}},
    {{"statement": "约翰正在修一门人工智能课程。", "reason": "课程列表中没有提到人工智能。", "verdict": "No"}},
    {{"statement": "约翰是一名用功的学生。", "reason": "上下文提到他花大量时间学习并经常在图书馆待到很晚。", "verdict": "Yes"}},
    {{"statement": "约翰有一份兼职工作。", "reason": "上下文中没有关于兼职工作的信息。", "verdict": "No"}}
  ]
}}

示例 2：
上下文：光合作用是植物、藻类和某些细菌将光能转化为化学能的过程。

陈述：
1. 阿尔伯特·爱因斯坦是一位天才。

输出：
{{
  "verdicts": [
    {{"statement": "阿尔伯特·爱因斯坦是一位天才。", "reason": "上下文与陈述无关。", "verdict": "No"}}
  ]
}}

现在请评估：
上下文：
{context}

陈述：
{statements}

输出格式：返回一个 JSON 对象，包含唯一的键 "verdicts"，其值为对象列表，\
每个对象包含 "statement"（字符串）、"reason"（字符串）和 "verdict"（"Yes" 或 "No"）。
必须为每条编号陈述恰好返回一个 verdict 对象，保留陈述原文，不得返回其他键或文本。
"""

# ============================================================================
# Answer Correctness: TP / FP / FN Classification
# Reference: RAGAS CorrectnessClassifier + GraphRAG-Bench answer_accuracy
# ============================================================================

CORRECTNESS_CLASSIFY_PROMPT = """\
Given a ground truth and answer statements, analyze each statement and \
classify them in one of the following categories:
- TP (true positive): statements present in answer that are also directly \
supported by one or more statements in ground truth.
- FP (false positive): statements present in the answer but not directly \
supported by any statement in ground truth.
- FN (false negative): statements found in the ground truth but not present \
in answer.

Each statement can only belong to one of the categories. Provide a reason \
for each classification.

Completeness rules (MUST follow):
- Every candidate statement must appear in exactly one of TP or FP. Do not \
skip any candidate statement.
- Every reference statement must appear in exactly one of TP or FN. Do not \
skip any reference statement.

Example 1:
Question: What powers the sun and what is its primary function?
Candidate Answer Statements:
1. The sun is powered by nuclear fission, similar to nuclear reactors on Earth.
2. The primary function of the sun is to provide light to the solar system.

Reference Answer Statements:
1. The sun is powered by nuclear fusion, where hydrogen atoms fuse to form helium.
2. This fusion process releases a tremendous amount of energy.
3. The energy provides heat and light, essential for life on Earth.
4. The sun's light plays a critical role in Earth's climate system.
5. Sunlight helps drive weather and ocean currents.

Output:
{{
  "tp": [{{"statement": "The primary function of the sun is to provide light to the solar system.", "reason": "Supported by ground truth mentioning the sun providing light."}}],
  "fp": [{{"statement": "The sun is powered by nuclear fission, similar to nuclear reactors on Earth.", "reason": "Incorrect - ground truth states nuclear fusion, not fission."}}],
  "fn": [
    {{"statement": "The sun is powered by nuclear fusion, where hydrogen atoms fuse to form helium.", "reason": "Not mentioned in answer."}},
    {{"statement": "This fusion process releases a tremendous amount of energy.", "reason": "Not mentioned in answer."}},
    {{"statement": "The energy provides heat and light, essential for life on Earth.", "reason": "Only light is mentioned in answer."}},
    {{"statement": "The sun's light plays a critical role in Earth's climate system.", "reason": "Not mentioned in answer."}},
    {{"statement": "Sunlight helps drive weather and ocean currents.", "reason": "Not mentioned in answer."}}
  ]
}}

Example 2:
Question: What is the boiling point of water?
Candidate Answer Statements:
1. The boiling point of water is 100 degrees Celsius at sea level.

Reference Answer Statements:
1. The boiling point of water is 100 degrees Celsius (212 degrees Fahrenheit) at sea level.
2. The boiling point of water can change with altitude.

Output:
{{
  "tp": [{{"statement": "The boiling point of water is 100 degrees Celsius at sea level", "reason": "Directly supported by ground truth."}}],
  "fp": [],
  "fn": [{{"statement": "The boiling point of water can change with altitude.", "reason": "Not mentioned in the answer."}}]
}}

Now classify:
Question: {question}
Candidate Answer Statements:
{candidate_statements}

Reference Answer Statements:
{reference_statements}

Output format: Return a JSON object with keys "tp", "fp", "fn", each \
containing a list of objects with "statement" and "reason" fields.
Every candidate/reference statement must appear exactly once in the required \
buckets, and the response must contain no additional keys or text.
"""

_CORRECTNESS_CLASSIFY_PROMPT_ZH = """\
给定标准答案和候选答案中的若干陈述，请对每个陈述进行分析，并将其归入以下类别之一：
- TP（真正例）：候选答案中出现，并且能被标准答案中的陈述直接支持的陈述。
- FP（假正例）：候选答案中出现，但不能被标准答案中的任何陈述直接支持的陈述。
- FN（假反例）：标准答案中有，但候选答案中未出现的陈述。

每个陈述只能属于一个类别，并请注明分类理由。

完备性要求（必须遵守）：
- 每条候选答案陈述必须恰好出现在 TP 或 FP 中的一个。不得遗漏任何候选答案陈述。
- 每条标准答案陈述必须恰好出现在 TP 或 FN 中的一个。不得遗漏任何标准答案陈述。

示例 1：
问题：太阳的能量来源是什么，它的主要功能是什么？
候选答案陈述：
1. 太阳的能量来源是核裂变，类似于地球上的核反应堆。
2. 太阳的主要功能是为太阳系提供光。

标准答案陈述：
1. 太阳的能量来源是核聚变，氢原子聚变形成氦。
2. 这一聚变过程释放出巨大的能量。
3. 这些能量提供热和光，对地球上的生命至关重要。
4. 太阳的光在地球气候系统中起着关键作用。
5. 阳光有助于驱动天气和洋流。

输出：
{{
  "tp": [{{"statement": "太阳的主要功能是为太阳系提供光。", "reason": "标准答案中提到太阳提供光。"}}],
  "fp": [{{"statement": "太阳的能量来源是核裂变，类似于地球上的核反应堆。", "reason": "错误——标准答案指出是核聚变，而非核裂变。"}}],
  "fn": [
    {{"statement": "太阳的能量来源是核聚变，氢原子聚变形成氦。", "reason": "候选答案未提及。"}},
    {{"statement": "这一聚变过程释放出巨大的能量。", "reason": "候选答案未提及。"}},
    {{"statement": "这些能量提供热和光，对地球上的生命至关重要。", "reason": "候选答案只提到了光。"}},
    {{"statement": "太阳的光在地球气候系统中起着关键作用。", "reason": "候选答案未提及。"}},
    {{"statement": "阳光有助于驱动天气和洋流。", "reason": "候选答案未提及。"}}
  ]
}}

示例 2：
问题：水的沸点是多少？
候选答案陈述：
1. 在标准大气压下，水的沸点是 100 摄氏度。

标准答案陈述：
1. 在标准大气压下，水的沸点是 100 摄氏度（212 华氏度）。
2. 水的沸点会随海拔变化。

输出：
{{
  "tp": [{{"statement": "在标准大气压下，水的沸点是 100 摄氏度。", "reason": "被标准答案直接支持。"}}],
  "fp": [],
  "fn": [{{"statement": "水的沸点会随海拔变化。", "reason": "候选答案未提及。"}}]
}}

现在请分类：
问题：{question}
候选答案陈述：
{candidate_statements}

标准答案陈述：
{reference_statements}

输出格式：返回一个 JSON 对象，包含键 "tp"、"fp"、"fn"，每个键对应的值为\
包含 "statement" 和 "reason" 字段的对象列表。
每条候选/标准答案陈述必须恰好出现在规定的分类中一次，且不得返回其他键或文本。
"""
