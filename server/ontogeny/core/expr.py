# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""mini-expr: the deterministic expression language of the DSL.

Single evaluation source for Action rules, derived properties, effect values
and EvalSuite assertions (dsl-spec §7). Deliberately NOT Turing complete:
lexer -> Pratt parser -> AST -> tree-walking evaluator. No ``eval()`` ever.

Grammar (precedence low->high):
    or < and < comparison(== != < <= > >= in has) < ?? < +- < */ < unary- < postfix(.)
Literals: numbers, "strings", true/false/null, [list]
Roots:   target.* parameters.* ; functions now() user() newId(pfx)
Datetime arithmetic: ts - ts -> milliseconds (float); ts +/- number -> ts.
``x ?? y`` coalesces null/missing. ``a in [..]`` membership. ``x has f``
presence check (used by Cedar-style conditions too).
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any

from ..errors import ExpressionError

# ----------------------------------------------------------------------------
# Lexer
# ----------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==|!=|<=|>=|\?\?|[+\-*/()<>[\],.:])
    """,
    re.VERBOSE,
)
_KEYWORDS = {"and", "or", "not", "in", "true", "false", "null", "has"}


@dataclass(frozen=True)
class Tok:
    kind: str  # 'string' | 'number' | 'ident' | 'op' | 'kw'
    text: str
    pos: int


def tokenize(src: str) -> list[Tok]:
    toks, pos = [], 0
    while pos < len(src):
        m = _TOKEN_RE.match(src, pos)
        if not m:
            raise ExpressionError(f"unexpected character {src[pos]!r} at {pos}", details={"src": src})
        pos = m.end()
        if m.lastgroup == "ws":
            continue
        text = m.group()
        if m.lastgroup == "ident" and text in _KEYWORDS:
            toks.append(Tok("kw", text, m.start()))
        else:
            toks.append(Tok(m.lastgroup, text, m.start()))  # type: ignore[arg-type]
    toks.append(Tok("op", "", len(src)))  # EOF sentinel
    return toks


# ----------------------------------------------------------------------------
# AST
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    pass


@dataclass(frozen=True)
class Lit(Node):
    value: Any


@dataclass(frozen=True)
class Path(Node):
    parts: tuple[str, ...]


@dataclass(frozen=True)
class Call(Node):
    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class ListLit(Node):
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Bin(Node):
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Un(Node):
    op: str
    operand: Node


_CMP = {"==", "!=", "<", "<=", ">", ">=", "in", "has"}
_BP: dict[str, int] = {"or": 10, "and": 20}
_CMP_BP = 30
_NULLCO_BP = 33
_ADD_BP = 40
_MUL_BP = 50


class _Parser:
    def __init__(self, toks: list[Tok], src: str) -> None:
        self.toks, self.i, self.src = toks, 0, src

    def peek(self) -> Tok:
        return self.toks[self.i]

    def next(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect_op(self, text: str) -> None:
        t = self.next()
        if t.kind != "op" or t.text != text:
            raise ExpressionError(f"expected {text!r} got {t.text!r} at {t.pos}", details={"src": self.src})

    def parse(self) -> Node:
        node = self.expr(0)
        if self.peek().text != "":  # EOF sentinel is op ''
            raise ExpressionError(f"trailing input at {self.peek().pos}", details={"src": self.src})
        return node

    def expr(self, min_bp: int) -> Node:
        left = self.prefix()
        while True:
            t = self.peek()
            op = t.text
            if t.kind == "kw" and op in ("and", "or"):
                bp = _BP[op]
                if bp < min_bp:
                    break
                self.next()
                left = Bin(op, left, self.expr(bp + 1))
            elif (t.kind == "op" and op in _CMP) or (t.kind == "kw" and op in ("in", "has")):
                if _CMP_BP < min_bp:
                    break
                self.next()
                left = Bin(op, left, self.expr(_CMP_BP + 1))
            elif t.kind == "op" and op == "??":
                if _NULLCO_BP < min_bp:
                    break
                self.next()
                left = Bin("??", left, self.expr(_NULLCO_BP))  # right-assoc
            elif t.kind == "op" and op in ("+", "-"):
                if _ADD_BP < min_bp:
                    break
                self.next()
                left = Bin(op, left, self.expr(_ADD_BP + 1))
            elif t.kind == "op" and op in ("*", "/"):
                if _MUL_BP < min_bp:
                    break
                self.next()
                left = Bin(op, left, self.expr(_MUL_BP + 1))
            else:
                break
        return left

    def prefix(self) -> Node:
        t = self.peek()
        if t.kind == "kw" and t.text == "not":
            self.next()
            return Un("not", self.expr(_CMP_BP))
        if t.kind == "op" and t.text == "-":
            self.next()
            return Un("-", self.expr(_MUL_BP))
        return self.postfix(self.atom())

    def atom(self) -> Node:
        t = self.next()
        if t.kind == "number":
            return Lit(float(t.text) if "." in t.text else int(t.text))
        if t.kind == "string":
            raw = t.text[1:-1]
            return Lit(raw.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\"))
        if t.kind == "kw" and t.text == "true":
            return Lit(True)
        if t.kind == "kw" and t.text == "false":
            return Lit(False)
        if t.kind == "kw" and t.text == "null":
            return Lit(None)
        if t.kind == "op" and t.text == "[":
            items: list[Node] = []
            if not (self.peek().kind == "op" and self.peek().text == "]"):
                while True:
                    items.append(self.expr(0))
                    if self.peek().kind == "op" and self.peek().text == ",":
                        self.next()
                        continue
                    break
            self.expect_op("]")
            return ListLit(tuple(items))
        if t.kind == "op" and t.text == "(":
            node = self.expr(0)
            self.expect_op(")")
            return node
        if t.kind == "ident":
            if self.peek().kind == "op" and self.peek().text == "(":
                self.next()
                args: list[Node] = []
                if not (self.peek().kind == "op" and self.peek().text == ")"):
                    while True:
                        args.append(self.expr(0))
                        if self.peek().kind == "op" and self.peek().text == ",":
                            self.next()
                            continue
                        break
                self.expect_op(")")
                return Call(t.text, tuple(args))
            return Path((t.text,))
        raise ExpressionError(f"unexpected token {t.text!r} at {t.pos}", details={"src": self.src})

    def postfix(self, node: Node) -> Node:
        while self.peek().kind == "op" and self.peek().text == ".":
            self.next()
            ident = self.next()
            if ident.kind not in ("ident", "kw"):
                raise ExpressionError(f"expected field name after '.' at {ident.pos}", details={"src": self.src})
            node = Path((*node.parts, ident.text)) if isinstance(node, Path) else Bin(".", node, Path((ident.text,)))
        return node


# ----------------------------------------------------------------------------
# Evaluation context
# ----------------------------------------------------------------------------


@dataclass
class ExprContext:
    """Roots and ambient functions injected by the runtime.

    ``now`` is injected (never wall-clock read inside eval) so replay/eval are
    deterministic. ``id_seed`` seeds newId() for reproducible creates.
    """

    target: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    principal: dict[str, Any] = field(default_factory=dict)
    now: _dt.datetime = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    id_seed: int = 0
    _seq: dict[str, int] = field(default_factory=dict)

    def root(self, name: str) -> Any:
        if name == "target":
            return self.target if self.target is not None else {}
        if name == "parameters":
            return self.parameters if self.parameters is not None else {}
        if name == "user":
            return self.principal.get("id")
        if name == "principal":
            return self.principal
        raise ExpressionError(f"unknown root {name!r}")


# ----------------------------------------------------------------------------
# Evaluator
# ----------------------------------------------------------------------------

_MISSING = object()


_KNOWN_ROOTS = ("target", "parameters", "user", "principal")


def _lookup(ctx: ExprContext, path: Path) -> Any:
    if len(path.parts) == 1:
        name = path.parts[0]
        if name in _KNOWN_ROOTS:
            return ctx.root(name)
        # bare-name sugar for derived expressions: "closed_at" == "target.closed_at"
        return (ctx.target or {}).get(name)
    value: Any = ctx.root(path.parts[0])
    for seg in path.parts[1:]:
        if isinstance(value, dict):
            value = value.get(seg, _MISSING)
        else:
            value = getattr(value, seg, _MISSING)
        if value is _MISSING:
            return None  # missing -> null (so ?? and has work naturally)
    return value


def _truthy(v: Any) -> bool:
    return bool(v)


def _as_number(v: Any) -> float | int:
    if isinstance(v, bool):
        raise ExpressionError("boolean used in arithmetic")
    if isinstance(v, (int, float)):
        return v
    raise ExpressionError(f"expected number, got {type(v).__name__}")


def _as_utc(value: _dt.datetime) -> _dt.datetime:
    """Treat naive datetimes as UTC.

    Stores before the UTC type decorator (and any external data) can hand us a
    naive value; mixing it with an aware `now()` used to raise TypeError and
    silently blank out every derived timestamp expression.
    """
    return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, _dt.datetime) and isinstance(b, _dt.datetime):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b if isinstance(a, bool) and isinstance(b, bool) else a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def eval_node(node: Node, ctx: ExprContext) -> Any:
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, ListLit):
        return [eval_node(i, ctx) for i in node.items]
    if isinstance(node, Path):
        return _lookup(ctx, node)
    if isinstance(node, Call):
        return _call(node, ctx)
    if isinstance(node, Un):
        v = eval_node(node.operand, ctx)
        if node.op == "not":
            return not _truthy(v)
        return -_as_number(v)
    if isinstance(node, Bin):
        return _bin(node, ctx)
    raise ExpressionError(f"unknown node {node}")  # pragma: no cover


def _call(node: Call, ctx: ExprContext) -> Any:
    name = node.name
    if name == "now" and not node.args:
        return ctx.now
    if name == "user" and not node.args:
        return ctx.principal.get("id")
    if name == "newId" and len(node.args) == 1:
        pfx = eval_node(node.args[0], ctx)
        if not isinstance(pfx, str):
            raise ExpressionError("newId() prefix must be a string")
        n = ctx._seq.get(pfx, ctx.id_seed) + 1
        ctx._seq[pfx] = n
        return f"{pfx}-{n:06d}"
    raise ExpressionError(f"unknown function {name!r}")


def _bin(node: Bin, ctx: ExprContext) -> Any:
    op = node.op
    if op == ".":
        raise ExpressionError("misplaced '.'")  # handled in postfix
    if op == "??":
        left = eval_node(node.left, ctx)
        return left if left is not None else eval_node(node.right, ctx)
    if op == "and":
        return _truthy(eval_node(node.left, ctx)) and _truthy(eval_node(node.right, ctx))
    if op == "or":
        return _truthy(eval_node(node.left, ctx)) or _truthy(eval_node(node.right, ctx))

    a = eval_node(node.left, ctx)
    b = eval_node(node.right, ctx)

    if op == "has":
        if not (isinstance(node.right, Path) and len(node.right.parts) == 1):
            raise ExpressionError("'has' requires a bare field name")
        name = node.right.parts[0]
        return isinstance(a, dict) and a.get(name) is not None

    if op == "in":
        if not isinstance(b, list):
            raise ExpressionError("'in' requires a list literal")
        return any(_eq(a, item) for item in b)

    if op == "==":
        return _eq(a, b)
    if op == "!=":
        return not _eq(a, b)

    if op in ("<", "<=", ">", ">="):
        try:
            if a is None or b is None:
                return False
            if op == "<":
                return a < b
            if op == "<=":
                return a <= b
            if op == ">":
                return a > b
            return a >= b
        except TypeError as exc:
            raise ExpressionError(f"cannot compare {type(a).__name__} and {type(b).__name__}") from exc

    # arithmetic
    if isinstance(a, _dt.datetime) and isinstance(b, _dt.datetime):
        if op == "-":
            return (_as_utc(a) - _as_utc(b)).total_seconds() * 1000.0  # milliseconds
        raise ExpressionError("datetime supports only subtraction")
    if isinstance(a, _dt.datetime) and isinstance(b, (int, float)) and not isinstance(b, bool):
        if op == "+":
            return a + _dt.timedelta(milliseconds=b)
        if op == "-":
            return a - _dt.timedelta(milliseconds=b)
        raise ExpressionError("datetime supports only +/- with numbers")
    x, y = _as_number(a), _as_number(b)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if op == "/":
        if y == 0:
            raise ExpressionError("division by zero")
        return x / y
    raise ExpressionError(f"unknown operator {op!r}")  # pragma: no cover


def _lookup_holder(ctx: ExprContext, path: Path) -> Any:
    """For `x has f`: resolve x's container (dict) rather than f's value."""
    if len(path.parts) == 1:
        return ctx.root(path.parts[0])
    value: Any = ctx.root(path.parts[0])
    for seg in path.parts[1:-1]:
        if isinstance(value, dict):
            value = value.get(seg)
        else:
            value = getattr(value, seg, None)
        if value is None:
            return None
    return value


# ----------------------------------------------------------------------------
# Public API (with parse cache) + static analysis
# ---------------------------------------------------------------------------


_cache: dict[str, Node] = {}


_MAX_EXPR_LEN = 8192  # expressions are authored DSL, not programs


def parse(src: str) -> Node:
    if len(src) > _MAX_EXPR_LEN:
        raise ExpressionError(
            f"expression exceeds {_MAX_EXPR_LEN} characters", details={"src": src[:80]})
    node = _cache.get(src)
    if node is None:
        try:
            node = _Parser(tokenize(src), src).parse()
        except RecursionError:
            # A deeply nested expression must be a validation error, never a
            # crash of the publish/import gate that calls analyze().
            raise ExpressionError(
                "expression too deeply nested", details={"src": src[:80]}) from None
        if len(_cache) > 4096:
            _cache.clear()
        _cache[src] = node
    return node


def is_bare_identifier(src: str) -> str | None:
    """Return the name if ``src`` is exactly one bare identifier.

    Effect values like ``status: OPEN`` are enum literals written as bare
    identifiers. Callers decide: if the name is a property of the object under
    modification it resolves to that property's value; otherwise it is treated
    as a string literal (enum member).
    """
    try:
        node = parse(src)
    except ExpressionError:
        return None
    if isinstance(node, Path) and len(node.parts) == 1:
        return node.parts[0]
    return None


def evaluate(src: str, ctx: ExprContext) -> Any:
    try:
        return eval_node(parse(src), ctx)
    except ExpressionError:
        raise
    except Exception as exc:  # defensive: wrap stray type errors
        raise ExpressionError(f"{type(exc).__name__}: {exc}", details={"src": src}) from exc


def analyze(src: str) -> set[tuple[str, str]]:
    """Collect (root, field) references for static validation. Throws on parse errors."""
    out: set[tuple[str, str]] = set()

    def walk(n: Node) -> None:
        if isinstance(n, Path):
            if len(n.parts) >= 2 and n.parts[0] in ("target", "parameters", "principal"):
                out.add((n.parts[0], n.parts[1]))
            elif len(n.parts) == 1 and n.parts[0] not in ("target", "parameters", "user", "principal"):
                out.add(("target", n.parts[0]))  # bare-name sugar for derived expressions
        elif isinstance(n, (Lit,)):
            return
        elif isinstance(n, ListLit):
            for i in n.items:
                walk(i)
        elif isinstance(n, Call):
            for a in n.args:
                walk(a)
        elif isinstance(n, Un):
            walk(n.operand)
        elif isinstance(n, Bin):
            walk(n.left)
            if n.op != "has":
                # the right side of `x has f` is a field NAME, not a reference:
                # walking it recorded (target, f) and mis-flagged legal rules
                # like `principal has site` as unknown target paths.
                walk(n.right)

    walk(parse(src))
    return out
