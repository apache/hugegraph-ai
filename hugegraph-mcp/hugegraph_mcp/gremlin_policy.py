# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""GremlinPolicy — 统一的 Gremlin 安全策略层。

所有 MCP Gremlin 读执行路径通过 GremlinPolicy.check_read() 做安全检查。
返回结构化决策，包含 allowed、classification、reason、error_type、suggestion。

本模块同时拥有 Gremlin 安全分类器的实现（原 gremlin_safety.py）。
gremlin_safety.py 保留为兼容 wrapper，重新导出公共 API。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

GremlinClassification = Literal["safe", "unsafe", "uncertain"]
GremlinSafety = GremlinClassification  # Compatibility alias.

# ========== Classifier constants ==========

_DYNAMIC_MARKERS = ("${", "#{", "->")
_MAX_REPEAT_TIMES = 10
_ALLOWED_ARG_TOKENS = {"true", "false", "null"}
_WRITE_METHODS = {
    "addv",
    "adde",
    "drop",
    "dropv",
    "drope",
    "remove",
    "clear",
    "sideeffect",
    "io",
    "call",
    "program",
}
_READ_METHODS = {
    "v",
    "e",
    "count",
    "limit",
    "range",
    "has",
    "haslabel",
    "hasid",
    "values",
    "valuemap",
    "id",
    "label",
    "keys",
    "elementmap",
    "properties",
    "out",
    "in",
    "both",
    "oute",
    "ine",
    "bothe",
    "outv",
    "inv",
    "bothv",
    "otherv",
    "path",
    "order",
    "group",
    "groupcount",
    "by",
    "dedup",
    "sample",
    "where",
    "not",
    "and",
    "or",
    "as",
    "select",
    "unfold",
    "coalesce",
    "optional",
    "repeat",
    "times",
    "until",
    "emit",
    "simplepath",
    "cyclicpath",
    "skip",
    "tail",
    "tolist",
    "toset",
    "explain",
    "profile",
}
_ANONYMOUS_READ_METHODS = {"outv", "inv", "bothv", "otherv"}


@dataclass(frozen=True)
class _GremlinToken:
    """A token produced by the conservative Gremlin scanner."""

    kind: Literal["identifier", "number", "string", "punctuation", "unknown"]
    value: str


@dataclass(frozen=True)
class _GremlinLexResult:
    tokens: tuple[_GremlinToken, ...]
    valid: bool
    normalized: str


@dataclass(frozen=True)
class _GremlinTokenAnalysis:
    method_names: tuple[str, ...]
    has_write_method: bool
    uncertain: bool


_SAFE_PUNCTUATION = frozenset(".(),[]:-")
_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
_CLOSE_TO_OPEN = {value: key for key, value in _OPEN_TO_CLOSE.items()}


def _is_identifier_start(char: str) -> bool:
    return char == "_" or (char.isascii() and char.isalpha())


def _is_identifier_part(char: str) -> bool:
    return _is_identifier_start(char) or (char.isascii() and char.isdigit())


def _append_masked(normalized: list[str], source: str) -> None:
    """Mask comments/string contents while retaining line structure."""

    normalized.extend("\n" if char == "\n" else " " for char in source)


def _consume_quoted(query: str, start: int) -> int | None:
    """Return the first offset after a quoted literal, or None if incomplete."""

    quote = query[start]
    triple = query.startswith(quote * 3, start)
    index = start + (3 if triple else 1)
    length = len(query)

    while index < length:
        char = query[index]
        if char == "\\":
            # A trailing escape cannot be a complete Groovy string.
            if index + 1 >= length:
                return None
            index += 2
            continue
        if triple:
            if query.startswith(quote * 3, index):
                return index + 3
        elif char == quote:
            return index + 1
        index += 1

    return None


def _lex_gremlin_query(query: str) -> _GremlinLexResult:
    """Tokenize strings/comments and code in one pass.

    This is deliberately a small safety scanner, not a Groovy parser.  It only
    needs to establish that every visible member is a known call and that no
    lexical structure is incomplete.  Unknown syntax is retained as an
    ``unknown`` token so callers can fail closed instead of silently dropping it.
    """

    tokens: list[_GremlinToken] = []
    normalized: list[str] = []
    index = 0
    length = len(query)
    valid = True

    while index < length:
        char = query[index]

        if char.isspace():
            normalized.append(char)
            index += 1
            continue

        # Groovy line and block comments are recognized outside strings only.
        if char == "/" and index + 1 < length and query[index + 1] == "/":
            start = index
            index += 2
            while index < length and query[index] not in "\r\n":
                index += 1
            _append_masked(normalized, query[start:index])
            continue
        if char == "/" and index + 1 < length and query[index + 1] == "*":
            start = index
            end = query.find("*/", index + 2)
            if end < 0:
                _append_masked(normalized, query[start:])
                valid = False
                break
            index = end + 2
            _append_masked(normalized, query[start:index])
            continue

        if char in {"'", '"'}:
            start = index
            end = _consume_quoted(query, index)
            if end is None:
                _append_masked(normalized, query[start:])
                valid = False
                break
            tokens.append(_GremlinToken("string", query[start:end]))
            # Keep delimiters in the normalized form for compatibility with
            # cost-warning callers, but never expose literal contents as code.
            delimiter_length = 3 if query.startswith(char * 3, start) else 1
            normalized.extend(query[start : start + delimiter_length])
            _append_masked(
                normalized,
                query[start + delimiter_length : end - delimiter_length],
            )
            normalized.extend(query[end - delimiter_length : end])
            index = end
            continue

        if _is_identifier_start(char):
            start = index
            index += 1
            while index < length and _is_identifier_part(query[index]):
                index += 1
            value = query[start:index]
            tokens.append(_GremlinToken("identifier", value))
            normalized.extend(value)
            continue

        if char.isascii() and char.isdigit():
            start = index
            index += 1
            seen_dot = False
            while index < length:
                current = query[index]
                if current.isascii() and current.isdigit():
                    index += 1
                elif current == "." and not seen_dot:
                    seen_dot = True
                    index += 1
                else:
                    break
            value = query[start:index]
            tokens.append(_GremlinToken("number", value))
            normalized.extend(value)
            continue

        if char in _SAFE_PUNCTUATION:
            tokens.append(_GremlinToken("punctuation", char))
            normalized.append(char)
            index += 1
            continue

        # Keep operators, interpolation markers, slashy literals, and unicode
        # syntax visible.  The analyzer will reject them as unexplained rather
        # than allowing a failed extraction to become ``safe``.
        tokens.append(_GremlinToken("unknown", char))
        normalized.append(char)
        index += 1

    return _GremlinLexResult(tuple(tokens), valid, "".join(normalized))


def _analyze_tokens(lexed: _GremlinLexResult) -> _GremlinTokenAnalysis:
    tokens = lexed.tokens
    methods: list[str] = []
    has_write_method = False
    uncertain = not lexed.valid or not tokens
    stack: list[str] = []

    for index, token in enumerate(tokens):
        if token.kind == "unknown":
            uncertain = True
            continue

        if token.kind == "string" and any(
            marker in token.value for marker in _DYNAMIC_MARKERS
        ):
            # GStrings can interpolate arbitrary Groovy expressions.  Treat
            # them as ambiguous even though their contents are not code tokens.
            uncertain = True
            continue

        if token.kind == "punctuation":
            if token.value in _OPEN_TO_CLOSE:
                stack.append(token.value)
            elif token.value in _CLOSE_TO_OPEN:
                if not stack or stack.pop() != _CLOSE_TO_OPEN[token.value]:
                    uncertain = True
            elif token.value in {";", "+", "=", "?", "!", "*", "%", "/"}:
                uncertain = True
            continue

        if token.kind != "identifier":
            continue

        lowered = token.value.lower()
        previous = tokens[index - 1] if index else None
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        is_member = previous is not None and previous.value == "."
        is_call = following is not None and following.value == "("

        if is_member:
            # A member must be a call.  This closes the old gap where a bare
            # write identifier was consumed by a separate loose regex.
            if not is_call:
                uncertain = True
                if lowered in _WRITE_METHODS or lowered in {"property", "iterate"}:
                    has_write_method = True
                continue
            methods.append(lowered)
            if lowered in _WRITE_METHODS or lowered in {"property", "iterate"}:
                has_write_method = True
            continue

        if is_call:
            # Only the anonymous traversal steps supported by the old
            # classifier are explainable without a receiver (for example
            # ``inV()`` inside ``where``). Treat every other bare call as
            # unexplained rather than allowing ``count()``/a user function to
            # masquerade as a valid traversal step.
            if lowered in _ANONYMOUS_READ_METHODS:
                methods.append(lowered)
            elif lowered in _WRITE_METHODS or lowered in {"property", "iterate"}:
                has_write_method = True
            else:
                uncertain = True
            continue

        if index == 0 and lowered == "g":
            continue
        if lowered in _ALLOWED_ARG_TOKENS:
            continue
        # Every remaining identifier is an unexplained variable, enum, map key,
        # or dynamic expression.  It must not be silently ignored.
        uncertain = True

    if stack:
        uncertain = True

    # The public read contract starts at exactly g.V(...) or g.E(...).
    if len(tokens) < 4:
        uncertain = True
    else:
        root = tokens[:4]
        if not (
            root[0].kind == "identifier"
            and root[0].value.lower() == "g"
            and root[1].value == "."
            and root[2].kind == "identifier"
            and root[2].value.lower() in {"v", "e"}
            and root[3].value == "("
        ):
            uncertain = True

    # Dynamic member names (``.\"drop\"()`` / ``.(expr)()``) never enter the
    # identifier stream and therefore need an explicit structural rejection.
    for index, token in enumerate(tokens):
        if token.value == ".":
            next_token = tokens[index + 1] if index + 1 < len(tokens) else None
            if next_token is None or next_token.kind != "identifier":
                uncertain = True

    if any(marker in lexed.normalized for marker in _DYNAMIC_MARKERS):
        uncertain = True

    if any(token.value in {"{", "}"} for token in tokens):
        uncertain = True

    return _GremlinTokenAnalysis(tuple(methods), has_write_method, uncertain)


# ========== Classifier implementation ==========


def classify_gremlin_read_safety(gremlin_query: str) -> GremlinSafety:
    """Classify a Gremlin query for use by the read-only execution tool.

    The classifier intentionally rejects ambiguous queries. It is a conservative
    safety gate, not a complete Gremlin parser.
    """

    if not isinstance(gremlin_query, str) or not gremlin_query.strip():
        return "uncertain"

    lexed = _lex_gremlin_query(gremlin_query)
    analysis = _analyze_tokens(lexed)

    if analysis.has_write_method:
        return "unsafe"
    if analysis.uncertain:
        return "uncertain"
    if any(method not in _READ_METHODS for method in analysis.method_names):
        return "uncertain"

    return "safe"


def is_safe_gremlin_read(gremlin_query: str) -> bool:
    """Return True only when the query is confidently read-only."""
    return classify_gremlin_read_safety(gremlin_query) == "safe"


def _extract_method_names(query_without_strings: str) -> list[str]:
    lexed = _lex_gremlin_query(query_without_strings)
    return list(_analyze_tokens(lexed).method_names)


def _has_unsafe_write_steps(
    query_without_strings: str, lowered_methods: list[str]
) -> bool:
    del lowered_methods  # The shared lexer is the source of truth.
    return _analyze_tokens(_lex_gremlin_query(query_without_strings)).has_write_method


def _has_dynamic_construction_markers(
    original_query: str, query_without_strings: str
) -> bool:
    del query_without_strings
    # Analyze the original source so interpolation and dynamic member markers
    # that occur inside a quoted literal are still visible to this compatibility
    # helper.  The public classifier uses the same source directly.
    return _analyze_tokens(_lex_gremlin_query(original_query)).uncertain


def _has_bare_identifier_arguments(query_without_strings: str) -> bool:
    return _analyze_tokens(_lex_gremlin_query(query_without_strings)).uncertain


def _strip_string_literals(query: str) -> str:
    """Replace strings/comments with masked text using the shared scanner."""

    return _lex_gremlin_query(query).normalized


# ========== Structured decision ==========


@dataclass(frozen=True)
class GremlinDecision:
    """Gremlin 安全检查的结构化决策。"""

    allowed: bool
    classification: GremlinClassification
    reason: str
    error_type: str | None
    suggestion: str | None


class GremlinPolicy:
    """统一的 Gremlin 安全策略。

    所有 MCP Gremlin 读执行路径必须通过 check_read() 检查。
    """

    def check_read(self, gremlin_query: str) -> GremlinDecision:
        """检查 Gremlin 查询是否允许作为只读查询执行。"""
        classification = classify_gremlin_read_safety(gremlin_query)

        if classification == "safe":
            return GremlinDecision(
                allowed=True,
                classification="safe",
                reason="Query is a known read-only traversal.",
                error_type=None,
                suggestion=None,
            )

        if classification == "unsafe":
            return GremlinDecision(
                allowed=False,
                classification="unsafe",
                reason="Query contains write or mutate operations.",
                error_type="UNSAFE_GREMLIN",
                suggestion=(
                    "Use execute_gremlin_write for write operations "
                    "when write access is enabled."
                ),
            )

        # classification == "uncertain"
        return GremlinDecision(
            allowed=False,
            classification="uncertain",
            reason="Query contains unknown or ambiguous steps; cannot confirm read-only safety.",
            error_type="UNSAFE_GREMLIN",
            suggestion="Use a clearly read-only Gremlin traversal starting with g.V() or g.E().",
        )


# Module-level singleton.
_policy = GremlinPolicy()


def check_gremlin_read(gremlin_query: str) -> GremlinDecision:
    """便捷函数：使用默认策略检查 Gremlin 查询。"""
    return _policy.check_read(gremlin_query)


def _parse_repeat_threshold() -> int:
    value = os.getenv("HUGEGRAPH_MCP_MAX_REPEAT_TIMES")
    if value is None or value.strip() == "":
        return _MAX_REPEAT_TIMES
    try:
        parsed = int(value)
    except ValueError:
        return _MAX_REPEAT_TIMES
    if parsed <= 0:
        return _MAX_REPEAT_TIMES
    return parsed


def gremlin_cost_warnings(gremlin_query: str) -> list[str]:
    """轻量成本边界检查：只产 warning 不阻断。非完整 parser，仅挡明显风险。"""

    query_without_strings = _strip_string_literals(gremlin_query)
    methods = [
        method.lower() for method in _extract_method_names(query_without_strings)
    ]
    method_set = set(methods)
    warnings: list[str] = []

    if method_set.isdisjoint({"limit", "range", "count"}):
        warnings.append(
            "Unbounded traversal: result set is not limited; consider adding "
            ".limit() or .range()."
        )

    if "repeat" in method_set:
        if "times" not in method_set:
            warnings.append(
                "repeat() without times() may recurse without an explicit depth bound."
            )
        else:
            max_times = _parse_repeat_threshold()
            match = re.search(r"times\(\s*(\d+)\s*\)", query_without_strings)
            if match is not None:
                depth = int(match.group(1))
                if depth > max_times:
                    warnings.append(
                        f"repeat().times(n) depth {depth} exceeds recommended "
                        f"maximum {max_times}."
                    )

    if any(
        method in method_set for method in ("path", "group", "profile")
    ) and method_set.isdisjoint({"limit", "range"}):
        warnings.append(
            "Heavy step (path/group/profile) without limit/range may be expensive."
        )

    return list(dict.fromkeys(warnings))
