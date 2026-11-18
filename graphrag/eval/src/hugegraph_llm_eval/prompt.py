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

"""Stable prompt selection and semantic-judge protocol adaptation."""

from typing import Final, cast

from pydantic import JsonValue

from hugegraph_llm_eval.contracts.digests import canonical_digest
from hugegraph_llm_eval.prompt_templates.answer import (
    _CORRECTNESS_CLASSIFY_PROMPT_ZH,
    _NLI_STATEMENT_PROMPT_ZH,
    _STATEMENT_DECOMPOSE_PROMPT_ZH,
    CORRECTNESS_CLASSIFY_PROMPT,
    NLI_STATEMENT_PROMPT,
    STATEMENT_DECOMPOSE_PROMPT,
)
from hugegraph_llm_eval.prompt_templates.context import (
    _CLAIM_DECOMPOSE_PROMPT_ZH,
    _CONTEXT_PRECISION_PROMPT_ZH,
    _CONTEXT_RELEVANCE_PROMPT_ZH,
    _ENTITY_EXTRACT_PROMPT_ZH,
    _EVIDENCE_RECALL_PROMPT_ZH,
    CLAIM_DECOMPOSE_PROMPT,
    CONTEXT_PRECISION_PROMPT,
    CONTEXT_RELEVANCE_PROMPT,
    ENTITY_EXTRACT_PROMPT,
    EVIDENCE_RECALL_PROMPT,
)
from hugegraph_llm_eval.prompt_templates.graph import (
    _ANSWER_RELEVANCE_PROMPT_ZH,
    _ENTITY_SEMANTIC_MATCH_PROMPT_ZH,
    _TRIPLE_SEMANTIC_MATCH_PROMPT_ZH,
    ANSWER_RELEVANCE_PROMPT,
    ENTITY_SEMANTIC_MATCH_PROMPT,
    TRIPLE_SEMANTIC_MATCH_PROMPT,
)

_PROMPT_REGISTRY: Final[dict[str, dict[str, str]]] = {
    "STATEMENT_DECOMPOSE_PROMPT": {"en": STATEMENT_DECOMPOSE_PROMPT, "zh": _STATEMENT_DECOMPOSE_PROMPT_ZH},
    "NLI_STATEMENT_PROMPT": {"en": NLI_STATEMENT_PROMPT, "zh": _NLI_STATEMENT_PROMPT_ZH},
    "CORRECTNESS_CLASSIFY_PROMPT": {"en": CORRECTNESS_CLASSIFY_PROMPT, "zh": _CORRECTNESS_CLASSIFY_PROMPT_ZH},
    "CONTEXT_PRECISION_PROMPT": {"en": CONTEXT_PRECISION_PROMPT, "zh": _CONTEXT_PRECISION_PROMPT_ZH},
    "CONTEXT_RELEVANCE_PROMPT": {"en": CONTEXT_RELEVANCE_PROMPT, "zh": _CONTEXT_RELEVANCE_PROMPT_ZH},
    "ENTITY_EXTRACT_PROMPT": {"en": ENTITY_EXTRACT_PROMPT, "zh": _ENTITY_EXTRACT_PROMPT_ZH},
    "EVIDENCE_RECALL_PROMPT": {"en": EVIDENCE_RECALL_PROMPT, "zh": _EVIDENCE_RECALL_PROMPT_ZH},
    "CLAIM_DECOMPOSE_PROMPT": {"en": CLAIM_DECOMPOSE_PROMPT, "zh": _CLAIM_DECOMPOSE_PROMPT_ZH},
    "ENTITY_SEMANTIC_MATCH_PROMPT": {
        "en": ENTITY_SEMANTIC_MATCH_PROMPT,
        "zh": _ENTITY_SEMANTIC_MATCH_PROMPT_ZH,
    },
    "TRIPLE_SEMANTIC_MATCH_PROMPT": {
        "en": TRIPLE_SEMANTIC_MATCH_PROMPT,
        "zh": _TRIPLE_SEMANTIC_MATCH_PROMPT_ZH,
    },
    "ANSWER_RELEVANCE_PROMPT": {"en": ANSWER_RELEVANCE_PROMPT, "zh": _ANSWER_RELEVANCE_PROMPT_ZH},
}


def get_prompt(name: str, language: str = "zh") -> str:
    """Return the requested historical prompt, defaulting to Chinese."""
    variants = _PROMPT_REGISTRY.get(name)
    if variants is None:
        raise KeyError(f"Unknown LLM-Judge prompt: {name}")
    return variants.get(language, variants["en"])


def answer_judge_prompt(kind: str, language: str = "zh") -> str:
    """Adapt the historical answer-evaluation prompt to the current typed protocol."""
    prompt_name = {
        "decompose": "STATEMENT_DECOMPOSE_PROMPT",
        "verify": "NLI_STATEMENT_PROMPT",
        "correctness": "CORRECTNESS_CLASSIFY_PROMPT",
    }.get(kind)
    if prompt_name is None:
        raise ValueError(f"Unsupported answer judge prompt kind: {kind}")
    historical = get_prompt(prompt_name, language)
    protocol = {
        "decompose": """\
当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 question 和 text 是待拆分内容。
只返回 {\"claims\": [\"原子主张 1\", \"原子主张 2\"]}，不得返回 statements 或其他键。""",
        "verify": """\
当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中包含 context，以及带零基
statement_index 的 statements。必须为每个 statement_index 恰好返回一项 verdict：
{\"verdicts\": [{\"statement_index\": 0, \"entailed\": true, \"reason\": \"上下文支持该主张。\"}]}。
不得返回 statement 或 Yes/No verdict 字段，也不得遗漏任一索引。""",
        "correctness": """\
当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 candidate 与 reference 都带零基
statement_index。返回 {\"matches\": [{\"candidate_index\": 0, \"reference_index\": 1, \"reason\": \"语义等价。\"}],
\"false_positives\": [{\"statement_index\": 2, \"reason\": \"标准答案不支持。\"}],
\"false_negatives\": [{\"statement_index\": 3, \"reason\": \"候选答案遗漏。\"}]}。
每个 candidate index 必须恰好出现在 matches 或 false_positives，每个 reference index 必须恰好出现在
matches 或 false_negatives；不得返回 tp、fp、fn 或其他键。""",
    }[kind]
    return f"{historical}\n\n---\n\n{protocol}"


def answer_judge_prompt_digest(language: str = "zh") -> str:
    """Digest the built-in answer prompts so prompt edits change evaluator identity."""
    texts = {kind: answer_judge_prompt(kind, language) for kind in ("decompose", "verify", "correctness")}
    return canonical_digest(cast(JsonValue, texts)).value


def retrieval_judge_prompt(kind: str, language: str = "zh") -> str:
    """Adapt Chinese retrieval few-shot prompts to the current batched verdict protocols."""
    prompt_name = {
        "context_precision": "CONTEXT_PRECISION_PROMPT",
        "context_relevancy": "CONTEXT_RELEVANCE_PROMPT",
        "evidence_recall": "EVIDENCE_RECALL_PROMPT",
    }.get(kind)
    if prompt_name is None:
        raise ValueError(f"Unsupported retrieval judge prompt kind: {kind}")
    historical = get_prompt(prompt_name, language)
    protocol = {
        "context_precision": (
            "当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 contexts 带零基 context_index。"
            "必须为每个 context_index 恰好返回一项 verdict："
            '{"verdicts":[{"context_index":0,"relevant":true,"reason":"该段能支持回答问题。"}]}。'
            "不得返回单个 verdict、Yes/No 字段或其他键。"
        ),
        "context_relevancy": (
            "当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 contexts 带零基 context_index。"
            "必须为每个 context_index 恰好返回一项 verdict："
            '{"verdicts":[{"context_index":0,"score":2,"reason":"该段完整回答问题。"}]}。'
            "score 只能为 0、1 或 2；不得返回单个 score 或其他键。"
        ),
        "evidence_recall": (
            "当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 evidence 带零基 evidence_index。"
            "必须为每个 evidence_index 恰好返回一项 verdict："
            '{"verdicts":[{"evidence_index":0,"attributed":true,"reason":"上下文直接支持该证据。"}]}。'
            "attributed 必须是布尔值；不得返回 classifications、statement 或其他键。"
        ),
    }[kind]
    return f"{historical}\n\n---\n\n{protocol}"


_FAITHFULNESS_PROMPT_ZH: Final = """\
你是知识图谱抽取质量的评审员。判断候选图中的每个顶点和每条边，是否被原始文本 source_text 忠实支持。

输入是一条 JSON 消息：source_text 是唯一的证据；items 是当前批次的候选项，item_index 是原始图中的全局索引，顶点和边分别编号。保留输入中的索引，不得在批次内重新编号；只判断本批次提供的项。顶点包含 label、name、properties、source_snippet；边包含 label、out_v、in_v、out_v_label、in_v_label、properties、source_snippet。

判定规则：
- 把每个顶点或边视为一个完整的图事实断言。只有 source_text 明确陈述完整断言，或无需引入外部事实即可无歧义地推出时，才判为忠实。
- 断言中任一重要部分没有依据、属于过度推断，或与 source_text 矛盾，整项判为不忠实。
- 顶点检查实体身份及其全部属性；边检查关系、两个端点的身份、方向及其全部属性。
- 边是有方向的：out_v 是关系的起点（source），in_v 是终点（target）。关系必须按 out_v 到 in_v 的方向与 source_text 一致，方向相反判为不忠实。
- 判断的是事实内容，不是字面措辞。不能仅因为 label（顶点 label、边 label、端点 label）没有在 source_text 中逐字出现就判为不忠实：边 label 只要对应 source_text 用其他说法陈述的同一关系（例如"总部位于"对应 LOCATED_IN）就算被支持；source_text 陈述的属性或数值被建模成独立的顶点或边时，只要对象、数值、单位与 source_text 一致，也算被支持。模式合法性由独立指标检查。
- source_snippet 只是定位提示，不是证据；不得使用常识、外部知识或模式预期。source_text 为空或与该项无关时判为不忠实。

输出要求：只返回一个 JSON 对象，包含 supported_vertex_indices、supported_edge_indices、unsupported_vertex_groups、unsupported_edge_groups 四个键，不得包含其他键或文本。
- 每个顶点索引和每个边索引必须恰好出现一次：要么在对应的 supported_*_indices 中，要么在某一个 unsupported_*_groups 的 item_indices 中。忠实项不出现在任何 group 中。
- 一个 group 包含 item_indices、error_categories、support_reason、error_reason、evidence_quote；原因和类别相同的不忠实项可以放进同一个 group。
- error_categories 至少一个，只能从下面选择：unsupported_claim、numeric_mismatch、unit_mismatch、condition_loss、range_loss、temporal_mismatch、polarity_reversal、subject_scope_error。source_text 完全不支持该断言时使用 unsupported_claim；同一项可以同时返回多个类别。
- support_reason 只写被 source_text 支持的部分，没有时为 null；error_reason 只写不支持、矛盾或错误的部分，不得把两类内容混写在同一字段。evidence_quote 是 source_text 中的原文摘录，没有则为 null。

示例输入（省略了 properties、out_v_label、in_v_label 和 source_snippet）：
{"source_text": "认证服务使用 OAuth 2.0 令牌。令牌存储在配置中心内。每 24 小时或 10,000 次请求轮换令牌。", "items": [
  {"item_kind": "vertex", "item_index": 0, "label": "Component", "name": "认证服务"},
  {"item_kind": "vertex", "item_index": 1, "label": "Specification", "name": "认证服务更换周期:2年"},
  {"item_kind": "vertex", "item_index": 2, "label": "Component", "name": "日志服务"},
  {"item_kind": "edge", "item_index": 0, "label": "HAS_SPEC", "out_v": "认证服务", "in_v": "令牌类型:OAuth1"},
  {"item_kind": "edge", "item_index": 1, "label": "LOCATED_IN", "out_v": "令牌存储", "in_v": "配置中心"}
]}

示例输出：
{"supported_vertex_indices": [0], "supported_edge_indices": [1],
 "unsupported_vertex_groups": [
  {"item_indices": [1], "error_categories": ["unsupported_claim", "temporal_mismatch"], "support_reason": null, "error_reason": "原文是每 24 小时或 10,000 次请求轮换令牌，没有每 2 年更换认证服务的说法；操作对象和时间间隔都没有依据。", "evidence_quote": "每 24 小时或 10,000 次请求轮换令牌"},
  {"item_indices": [2], "error_categories": ["unsupported_claim"], "support_reason": null, "error_reason": "原文从未提到日志服务。", "evidence_quote": null}],
 "unsupported_edge_groups": [
  {"item_indices": [0], "error_categories": ["numeric_mismatch"], "support_reason": "原文确实说认证服务使用令牌。", "error_reason": "原文使用的是 OAuth 2.0，该项声称 OAuth1，与原文矛盾。", "evidence_quote": "认证服务使用 OAuth 2.0 令牌"}]}
"""
_FAITHFULNESS_PROMPT_EN: Final = """\
You review the quality of a knowledge-graph extraction. Decide whether each candidate vertex and edge is faithfully supported by the original text, source_text.

The input is one JSON message. source_text is the only evidence. items are the candidates in this batch; item_index is a global index in the original graph, with separate vertex and edge namespaces. Preserve the supplied indices without renumbering; evaluate only the items in this batch. A vertex has label, name, properties and source_snippet. An edge has label, out_v, in_v, out_v_label, in_v_label, properties and source_snippet.

Rules:
- Treat each vertex or edge as one complete factual claim. Mark it faithful only when source_text states the whole claim explicitly, or entails it unambiguously without external facts.
- If any material part of the claim lacks support, is over-extrapolated, or contradicts source_text, mark the whole item unsupported.
- For a vertex, check the entity identity and every property. For an edge, check the relation, the identity of both endpoints, the direction, and every property.
- An edge is directed: out_v is its source (start) and in_v its target (end). The relation must run from out_v to in_v exactly as source_text states it; a reversed edge is unsupported.
- Judge the factual content, not the wording. Do not reject an item only because a label (vertex label, edge label or endpoint label) is not written literally in source_text. An edge label is supported when source_text states the same relation in other words (for example "headquartered in" for LOCATED_IN). A property or measurement that source_text states may be modelled as its own vertex or edge, and is supported as long as its object, value and unit agree with source_text. Schema legality is checked by a separate metric.
- source_snippet is only a locator, not evidence. Do not use world knowledge or schema expectations. If source_text is empty or unrelated to the item, mark it unsupported.

Output format: return only one JSON object with the four keys supported_vertex_indices, supported_edge_indices, unsupported_vertex_groups and unsupported_edge_groups, and no other keys or text.
- Every vertex index and every edge index must appear exactly once: either in the matching supported_*_indices, or in the item_indices of exactly one unsupported_*_groups entry. Faithful items never appear in a group.
- A group has item_indices, error_categories, support_reason, error_reason and evidence_quote. Unsupported items with the same categories and reasons may share one group.
- error_categories needs at least one value, chosen only from: unsupported_claim, numeric_mismatch, unit_mismatch, condition_loss, range_loss, temporal_mismatch, polarity_reversal, subject_scope_error. Use unsupported_claim when source_text gives the claim no support at all. An item may have several categories.
- support_reason covers only the part that source_text supports and is null when nothing is supported; error_reason covers only what is unsupported, contradicted or wrong. Never mix the two in one field. evidence_quote is a verbatim excerpt of source_text, or null.

Example input (properties, out_v_label, in_v_label and source_snippet omitted):
{"source_text": "The auth service uses OAuth 2.0 tokens. Token storage is located in the configuration center. Rotate tokens every 24 hours or 10,000 requests.", "items": [
  {"item_kind": "vertex", "item_index": 0, "label": "Component", "name": "auth service"},
  {"item_kind": "vertex", "item_index": 1, "label": "Specification", "name": "auth service replacement cycle: 2 years"},
  {"item_kind": "vertex", "item_index": 2, "label": "Component", "name": "log service"},
  {"item_kind": "edge", "item_index": 0, "label": "HAS_SPEC", "out_v": "auth service", "in_v": "token type: OAuth1"},
  {"item_kind": "edge", "item_index": 1, "label": "LOCATED_IN", "out_v": "token storage", "in_v": "configuration center"}
]}

Example output:
{"supported_vertex_indices": [0], "supported_edge_indices": [1],
 "unsupported_vertex_groups": [
  {"item_indices": [1], "error_categories": ["unsupported_claim", "temporal_mismatch"], "support_reason": null, "error_reason": "The text rotates tokens every 24 hours or 10,000 requests; it never says the auth service is replaced every 2 years, so both the action and the interval lack support.", "evidence_quote": "Rotate tokens every 24 hours or 10,000 requests"},
  {"item_indices": [2], "error_categories": ["unsupported_claim"], "support_reason": null, "error_reason": "The text never mentions a log service.", "evidence_quote": null}],
 "unsupported_edge_groups": [
  {"item_indices": [0], "error_categories": ["numeric_mismatch"], "support_reason": "The text does say the auth service uses tokens.", "error_reason": "The text specifies OAuth 2.0 but the item claims OAuth1, which contradicts the source.", "evidence_quote": "The auth service uses OAuth 2.0 tokens"}]}
"""

_FAITHFULNESS_PROMPTS: Final = {"zh": _FAITHFULNESS_PROMPT_ZH, "en": _FAITHFULNESS_PROMPT_EN}


def graph_judge_prompt(kind: str, language: str = "zh") -> str:
    """Return the graph-evaluation judge prompt for the current typed protocol."""
    if kind != "faithfulness":
        raise ValueError(f"Unsupported graph judge prompt kind: {kind}")
    return _FAITHFULNESS_PROMPTS.get(language, _FAITHFULNESS_PROMPT_EN)


_GRAPH_JUDGE_RUBRICS: Final[dict[str, dict[str, str]]] = {
    "faithfulness": {
        "zh": (
            "把每个候选顶点或边视为一个完整事实断言。只有 source_text 明确陈述，或无需引入外部知识即可直接推出该完整断言时，"
            "才能判定为忠实；名称、关系方向、端点或属性任一关键部分缺少依据时，整项判定为不忠实。"
            "不得依赖外部知识。source_snippet 只是定位提示，不是独立证据，必须以 source_text 为准验证。对不支持的项说明缺失的断言，"
            "并从协议规定的 error_categories 中选择一个或多个错误类别；若包含数值、单位、条件、范围、时间、否定或适用对象错误，"
            "必须优先标记对应的具体类别，不要只返回 unsupported_claim。"
            "support_reason 只说明断言中被支持的部分，error_reason 只说明错误或缺失的部分，不要混写。"
        ),
        "en": (
            "Treat each candidate vertex or edge as one complete factual claim. Mark it faithful only when source_text explicitly states "
            "the complete claim or unambiguously entails it without external knowledge. If the entity name, relation direction, "
            "endpoint, or property lacks support, mark the whole item unsupported. Do not rely on external knowledge. "
            "source_snippet is only a locator, not evidence; validate against source_text, explain unsupported claims, and return one or more "
            "controlled error categories for every unsupported item. Separate supported and unsupported portions into support_reason and error_reason."
        ),
    }
}


def graph_judge_rubric(kind: str, language: str = "zh") -> str:
    """Return the centralized rubric for a graph judge."""
    rubrics = _GRAPH_JUDGE_RUBRICS.get(kind)
    if rubrics is None:
        raise ValueError(f"Unsupported graph judge rubric kind: {kind}")
    return rubrics.get(language, rubrics["en"])


def semantic_verdict_prompt(kind: str, language: str = "zh") -> str:
    """Propose semantic pairs without discarding alternatives before assignment."""
    if kind not in {"entity", "triple"}:
        raise ValueError(f"Unsupported semantic graph item kind: {kind}")
    if language == "zh":
        rules = {
            "entity": (
                "实体名称的语义等价是命中条件。label 不一致仍可命中，记录 label_mismatch；"
                "不得仅因 label 不一致返回 candidate_index=null。properties 只作辅助证据，"
                "属性差异记录 property_mismatch，不影响实体匹配。名称含义不对应则不得命中。"
                "例如 Component/auth service 与 Service/authentication service 可以命中并记录"
                " label_mismatch；不能仅因同为 Service 就把 auth service 和 log service 判为等价。"
            ),
            "triple": (
                "关系边是有方向的事实。关系类型只是名称表达，同义词、别名或缩写可命中并记录"
                " relation_mismatch。起点 out_v 和终点 in_v 必须分别语义对应，反向边不得命中。"
                "out_v_label 和 in_v_label 不同仅记录 endpoint_label_mismatch，不能否决名称对应的端点。"
                "properties 只作辅助证据，属性差异记录 property_mismatch。"
                "例如 A DEPENDS_ON B 与 A REQUIRES B 可以命中；B REQUIRES A 不能与前者匹配。"
            ),
        }[kind]
        protocol = (
            "candidates 是当前候选窗口，references 是当前标准答案窗口。对每个 reference_index，"
            "返回当前窗口中所有语义等价候选的独立 pair，不要只选最高分候选，也不要在窗口内做一对一分配。"
            "同一个 reference_index 可以对应多个 candidate_index，同一个 candidate_index 也可以对应多个"
            " reference_index；由后处理对所有窗口返回的 pair 统一按调用方选定策略做一对一匹配。"
            "每个 (reference_index, candidate_index) 只能出现一次；仅当该 reference 在当前窗口完全没有"
            "语义等价候选时，返回一条 candidate_index=null 的记录，不得与该 reference 的命中 pair 混用。"
            "每个 reference 都必须被覆盖，不能输出未提供的 reference 或当前窗口以外的 candidate。"
            "命中时给出 0 到 100 的 match_score；未命中时 match_score=null 并包含 no_semantic_match。"
            "reason 必须说明对应名称、关系、方向或属性的具体依据，不能只写语义等价，不得编造输入证据。"
        )
        output_rule = "只返回下面形式的 JSON；示例展示多个备选 pair，索引仅用于说明结构："
    else:
        rules = {
            "entity": (
                "Match semantically equivalent entity names. A label difference is a soft label_mismatch; "
                "never reject equivalent names solely because their labels differ. Properties are supporting "
                "evidence only; report property_mismatch without rejecting an otherwise valid match. "
                "For example, Component/auth service and Service/authentication service may match with "
                "label_mismatch, whereas auth service and log service are not equivalent just because "
                "both have the Service label."
            ),
            "triple": (
                "Match the same directed fact: out_v and in_v must correspond separately and direction "
                "must agree. Relation aliases may match with relation_mismatch; different facts may not. "
                "Differences in out_v_label/in_v_label are soft endpoint_label_mismatch issues. Property "
                "differences are soft property_mismatch issues. For example, A DEPENDS_ON B and A REQUIRES B "
                "may match, but B REQUIRES A reverses the fact and must not match."
            ),
        }[kind]
        protocol = (
            "candidates is the current candidate window; references is the current reference window. "
            "For every reference_index, return ALL semantically valid candidate pairs in this window. "
            "Do not keep only the best candidate and do not assign one-to-one within a window. "
            "Both reference_index and candidate_index may occur in multiple distinct pairs. The caller "
            "selects a one-to-one matching over all pairs from all windows using its configured strategy. "
            "Each (reference_index, candidate_index) pair must be unique. Only when a reference has no "
            "valid candidate in this window, return exactly one null candidate_index for it; never mix "
            "a null verdict with matched pairs for the same reference. Cover every reference and use "
            "only supplied global indices. Matched pairs require match_score in [0, 100]; unmatched "
            "verdicts require match_score=null and no_semantic_match. Give a concrete reason grounded "
            "in the supplied names, relation, direction or properties; do not invent evidence."
        )
        output_rule = "Return only JSON in this shape; the illustrative indices show alternative pairs:"
    issues = {
        "entity": "label_mismatch, property_mismatch, name_mismatch, no_semantic_match",
        "triple": (
            "relation_mismatch, endpoint_label_mismatch, endpoint_mismatch, direction_mismatch, "
            "property_mismatch, no_semantic_match"
        ),
    }[kind]
    return f"""{rules}

{protocol}

Allowed match_issues: {issues}. Use [] when none apply. name_mismatch,
endpoint_mismatch and direction_mismatch are hard conflicts: never put them on
an accepted pair. Use no_semantic_match only on an unmatched reference verdict.

{output_rule}
{{
  "verdicts": [
    {{"reference_index": 0, "candidate_index": 12, "match_score": 88, "match_issues": [], "reason": "Evidence for pair 0/12"}},
    {{"reference_index": 0, "candidate_index": 13, "match_score": 92, "match_issues": [], "reason": "Evidence for alternative 0/13"}},
    {{"reference_index": 1, "candidate_index": 12, "match_score": 86, "match_issues": [], "reason": "Evidence for alternative 1/12"}},
    {{"reference_index": 2, "candidate_index": null, "match_score": null, "match_issues": ["no_semantic_match"], "reason": "No valid candidate in this window"}}
  ]
}}"""
