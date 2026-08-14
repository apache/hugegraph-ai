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

from hugegraph_mcp.gremlin_safety import classify_gremlin_read_safety


def test_safe_read_queries():
    queries = [
        "g.V().count()",
        "g.E().limit(10)",
        "g.V().hasLabel('person').values('name')",
        "g.V().both().id()",
        "g.V().out().path()",
        "g.V().has('name', 'alice').valueMap()",
        "g.E().range(0, 5).elementMap()",
        "g.V().hasLabel('person').has('name','Alice').outE('knows').where(inV().hasLabel('person').has('name','Bob')).count()",
    ]

    for query in queries:
        assert classify_gremlin_read_safety(query) == "safe"


def test_unsafe_write_queries():
    queries = [
        "g.addV('person')",
        "g.addE('knows')",
        "g.V().drop()",
        "g.E().dropE()",
        "g.V().property('name','x')",
        "g.V().has('name','x').drop()",
        "g.V().remove()",
        "g.E().clear()",
        "g.V().hasLabel('person').drop().iterate()",
    ]

    for query in queries:
        assert classify_gremlin_read_safety(query) == "unsafe"


def test_uncertain_queries():
    queries = [
        "g.V().unknownStep()",
        "query + g.V().count()",
        "g.V().hasLabel(label)",
        "def q = g.V().count(); q",
        "graph.traversal().V().count()",
        "g.V().map{ it.get() }",
    ]

    for query in queries:
        assert classify_gremlin_read_safety(query) == "uncertain"


def test_case_insensitive():
    assert classify_gremlin_read_safety("G.V().COUNT()") == "safe"
    assert classify_gremlin_read_safety("G.ADDV('person')") == "unsafe"
    assert classify_gremlin_read_safety("g.V().DROP()") == "unsafe"


def test_existing_keyword_tests_still_pass():
    queries = [
        "g.addV('person')",
        "g.addE('knows')",
        "g.V().dropV()",
        "g.E().dropE()",
        "g.V().property('name', 'alice')",
    ]

    for query in queries:
        assert classify_gremlin_read_safety(query) == "unsafe"


def test_newly_denied_high_risk_steps():
    """M1: sideEffect, io, call, program must be classified as unsafe."""
    queries = [
        "g.V().sideEffect('x')",
        "g.V().io('file')",
        "g.V().call('func')",
        "g.V().program('script')",
    ]

    for query in queries:
        assert classify_gremlin_read_safety(query) == "unsafe", (
            f"Expected unsafe: {query}"
        )


def test_side_effect_accumulators_are_uncertain():
    """sack, store, aggregate, cap are not in read whitelist → classified as uncertain."""
    queries = [
        "g.V().sack(sum).by('age')",
        "g.V().store('x')",
        "g.V().aggregate('x')",
        "g.V().cap('x')",
    ]

    for query in queries:
        assert classify_gremlin_read_safety(query) == "uncertain", (
            f"Expected uncertain: {query}"
        )
