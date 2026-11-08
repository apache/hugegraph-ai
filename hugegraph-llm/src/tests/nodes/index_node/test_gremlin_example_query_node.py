# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from types import SimpleNamespace

from hugegraph_llm.nodes.index_node.gremlin_example_index_query import GremlinExampleIndexQueryNode


class RecordingOperator:
    def __init__(self):
        self.queries = []

    def run(self, context):
        self.queries.append(context['query'])
        return {**context, 'match_result': ['matched example']}


def test_flow_input_query_reaches_index_operator():
    operator = RecordingOperator()
    node = SimpleNamespace(wk_input=SimpleNamespace(query='alice'), operator=operator)
    result = GremlinExampleIndexQueryNode.operator_schedule(node, {})
    assert operator.queries == ['alice']
    assert result['match_result'] == ['matched example']


def test_empty_query_skips_index_search():
    operator = RecordingOperator()
    node = SimpleNamespace(wk_input=SimpleNamespace(query=''), operator=operator)
    result = GremlinExampleIndexQueryNode.operator_schedule(node, {})
    assert operator.queries == []
    assert result['match_result'] == []
