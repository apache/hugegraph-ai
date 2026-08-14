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

"""Tests for GremlinPolicy (Milestone 3)."""

from hugegraph_mcp.gremlin_policy import (
    GremlinDecision,
    GremlinPolicy,
    check_gremlin_read,
    gremlin_cost_warnings,
)


def test_safe_query_returns_allowed():
    decision = check_gremlin_read("g.V().limit(10)")

    assert decision.allowed is True
    assert decision.classification == "safe"
    assert decision.error_type is None
    assert decision.suggestion is None


def test_unsafe_query_returns_blocked():
    decision = check_gremlin_read("g.addV('person')")

    assert decision.allowed is False
    assert decision.classification == "unsafe"
    assert decision.error_type == "UNSAFE_GREMLIN"
    assert "write" in decision.reason.lower()


def test_uncertain_query_returns_blocked():
    decision = check_gremlin_read("g.V().unknownStep()")

    assert decision.allowed is False
    assert decision.classification == "uncertain"
    assert decision.error_type == "UNSAFE_GREMLIN"
    assert (
        "ambiguous" in decision.reason.lower() or "unknown" in decision.reason.lower()
    )


def test_decision_is_frozen_dataclass():
    decision = check_gremlin_read("g.V().count()")

    assert isinstance(decision, GremlinDecision)
    try:
        decision.allowed = False
        assert False, "Should be frozen"
    except AttributeError:
        pass


def test_policy_class_instance():
    policy = GremlinPolicy()

    safe = policy.check_read("g.V().count()")
    assert safe.allowed is True

    unsafe = policy.check_read("g.V().drop()")
    assert unsafe.allowed is False

    uncertain = policy.check_read("g.V().map { it }")
    assert uncertain.allowed is False


def test_newly_denied_steps_as_unsafe():
    for step in ["sideEffect", "io", "call", "program"]:
        decision = check_gremlin_read(f"g.V().{step}('x')")
        assert decision.allowed is False, f"Expected blocked: {step}"
        assert decision.classification == "unsafe"


def test_accumulator_steps_as_uncertain():
    for step in ["sack", "store", "aggregate", "cap"]:
        decision = check_gremlin_read(f"g.V().{step}('x')")
        assert decision.allowed is False, f"Expected blocked: {step}"
        assert decision.classification == "uncertain"


def test_bare_identifier_wrapped_in_parentheses_is_uncertain():
    decision = check_gremlin_read("g.V().has('age', (secret_token))")

    assert decision.allowed is False
    assert decision.classification == "uncertain"


def test_bare_identifier_nested_in_function_call_is_uncertain():
    decision = check_gremlin_read("g.V().has('age', coalesce(secret_token))")

    assert decision.allowed is False
    assert decision.classification == "uncertain"


def test_quoted_or_dynamic_members_are_uncertain():
    for query in [
        "g.V().'drop'().'iterate'()",
        'g.V()."property"(\'flag\', true)."iterate"()',
        "g.V().('drop')()",
    ]:
        decision = check_gremlin_read(query)

        assert decision.allowed is False, f"Expected blocked: {query}"
        assert decision.classification == "uncertain"


def test_allowed_literal_tokens_remain_safe():
    for query in [
        "g.V().has('active', true)",
        "g.V().has('active', false)",
        "g.V().has('deleted_at', null)",
    ]:
        decision = check_gremlin_read(query)
        assert decision.allowed is True, f"Expected allowed: {query}"


def test_edge_endpoint_where_traversal_is_safe():
    decision = check_gremlin_read(
        "g.V().hasLabel('person').has('name','Alice')"
        ".outE('knows').where(inV().hasLabel('person').has('name','Bob')).count()"
    )

    assert decision.allowed is True
    assert decision.classification == "safe"


def test_gremlin_cost_warnings_bounded_limit_query_is_empty():
    assert gremlin_cost_warnings("g.V().limit(10)") == []


def test_gremlin_cost_warnings_count_query_is_empty():
    assert gremlin_cost_warnings("g.V().count()") == []


def test_gremlin_cost_warnings_unbounded_query_mentions_limit():
    warnings = gremlin_cost_warnings("g.V()")

    assert warnings
    assert any("limit" in warning for warning in warnings)


def test_gremlin_cost_warnings_repeat_without_times():
    warnings = gremlin_cost_warnings("g.V().repeat(out())")

    assert any("repeat" in warning and "times" in warning for warning in warnings)


def test_gremlin_cost_warnings_repeat_times_exceeds_threshold(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_REPEAT_TIMES", "10")

    warnings = gremlin_cost_warnings("g.V().repeat(out()).times(100).limit(10)")

    assert any("depth" in warning or "maximum" in warning for warning in warnings)


def test_gremlin_cost_warnings_group_with_limit_is_not_heavy_warning():
    warnings = gremlin_cost_warnings('g.V().group().by("name").limit(5)')

    assert not any("Heavy step" in warning for warning in warnings)


def test_gremlin_cost_warnings_group_without_limit_is_heavy_warning():
    warnings = gremlin_cost_warnings("g.V().group()")

    assert any("Heavy step" in warning for warning in warnings)
