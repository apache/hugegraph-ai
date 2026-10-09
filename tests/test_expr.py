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
"""mini-expr: parsing, precedence, semantics, determinism, static analysis."""
from __future__ import annotations

import datetime as dt

import pytest

from ontogeny.core.expr import ExprContext, analyze, evaluate, parse
from ontogeny.errors import ExpressionError


def ctx(**kw) -> ExprContext:
    base = dict(
        target={"status": "OPEN", "priority": "HIGH", "site": "north", "n": 10,
                "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                "closed_at": None},
        parameters={"resolution": "fixed", "downtime_minutes": 42},
        principal={"id": "u1", "Role": {"maintenance_supervisor"}, "site": "north"},
    )
    base.update(kw)
    return ExprContext(**base)


class TestBasics:
    def test_arithmetic_precedence(self):
        assert evaluate("1 + 2 * 3", ctx()) == 7
        assert evaluate("(1 + 2) * 3", ctx()) == 9
        assert evaluate("10 / 4", ctx()) == 2.5
        assert evaluate("-3 + 5", ctx()) == 2

    def test_string_and_enum(self):
        assert evaluate("target.status == 'OPEN'", ctx()) is True
        assert evaluate('target.status == "OPEN"', ctx()) is True
        assert evaluate("target.status != 'CLOSED'", ctx()) is True

    def test_logic_and_not(self):
        assert evaluate("target.status == 'OPEN' and target.priority == 'HIGH'", ctx()) is True
        assert evaluate("not (target.status == 'OPEN')", ctx()) is False
        assert evaluate("false or true", ctx()) is True

    def test_membership(self):
        assert evaluate("target.priority in ['HIGH', 'CRITICAL']", ctx()) is True
        assert evaluate("target.priority in ['LOW']", ctx()) is False

    def test_null_coalescing(self):
        assert evaluate("target.closed_at ?? 'none'", ctx()) == "none"
        assert evaluate("parameters.downtime_minutes ?? 0", ctx()) == 42
        assert evaluate("target.missing ?? parameters.downtime_minutes", ctx()) == 42

    def test_has(self):
        assert evaluate("principal has site", ctx()) is True
        assert evaluate("principal has nosuch", ctx()) is False

    def test_missing_path_is_null(self):
        assert evaluate("target.does_not_exist", ctx()) is None
        assert evaluate("target.does_not_exist == null", ctx()) is True

    def test_precedence_comparison_over_arithmetic(self):
        assert evaluate("1 + 1 == 2", ctx()) is True
        assert evaluate("2 * 2 >= 3", ctx()) is True


class TestDatetime:
    def test_subtraction_milliseconds(self):
        v = evaluate(
            "target.closed_at - target.created_at",
            ctx(target={
                "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                "closed_at": dt.datetime(2026, 1, 1, 0, 30, tzinfo=dt.timezone.utc),
            }),
        )
        assert v == 30 * 60 * 1000

    def test_minutes_derived_pattern(self):
        v = evaluate(
            "(closed_at - created_at) / 60000",
            ExprContext(target={
                "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                "closed_at": dt.datetime(2026, 1, 1, 0, 30, tzinfo=dt.timezone.utc),
            }),
        )
        assert v == 30

    def test_now_injected_deterministic(self):
        t0 = dt.datetime(2026, 9, 18, 12, 0, tzinfo=dt.timezone.utc)
        assert evaluate("now()", ExprContext(now=t0)) == t0


class TestFunctions:
    def test_user(self):
        assert evaluate("user()", ctx()) == "u1"

    def test_newid_seeded(self):
        c1, c2 = ctx(id_seed=0), ctx(id_seed=0)
        assert evaluate("newId('WO')", c1) == "WO-000001"
        assert evaluate("newId('WO')", c1) == "WO-000002"  # increments in-context
        assert evaluate("newId('WO')", c2) == "WO-000001"  # fresh ctx restarts from seed


class TestErrors:
    def test_parse_error(self):
        with pytest.raises(ExpressionError):
            parse("1 +")

    def test_unknown_root(self):
        with pytest.raises(ExpressionError):
            evaluate("bogus.x", ctx())

    def test_division_by_zero(self):
        with pytest.raises(ExpressionError):
            evaluate("1 / 0", ctx())

    def test_unknown_function(self):
        with pytest.raises(ExpressionError):
            evaluate("sin(1)", ctx())


class TestAnalysis:
    def test_collect_paths(self):
        paths = analyze("target.status == 'OPEN' and parameters.resolution != ''")
        assert ("target", "status") in paths
        assert ("parameters", "resolution") in paths

    def test_analyze_parse_error_raises(self):
        from ontogeny.errors import ExpressionError as EE

        with pytest.raises(EE):
            analyze("(((")
