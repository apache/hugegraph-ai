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

import pytest

from hugegraph_llm_sdk.graph_utils import primary_key_id
from hugegraph_llm_sdk.extraction_runtime.property_graph import _primary_keys
from hugegraph_llm_sdk.schema import validate_schema


@pytest.mark.parametrize('strategy', [None, 'DEFAULT', 'PRIMARY_KEY'])
def test_primary_key_strategy_generates_identity(strategy):
    label = {'id': 1, 'id_strategy': strategy, 'primary_keys': ['name']}
    assert primary_key_id(label, {'name': 'alice'}) == '1:alice'
    assert primary_key_id(label, {}) is None
    assert _primary_keys(label) == ['name']


def test_automatic_strategy_does_not_generate_primary_identity():
    label = {'id': 1, 'id_strategy': 'AUTOMATIC', 'primary_keys': ['name']}
    assert primary_key_id(label, {'name': 'alice'}) is None
    assert _primary_keys(label) == []


@pytest.mark.parametrize('strategy', [None, 'DEFAULT', 'PRIMARY_KEY'])
def test_primary_key_must_not_be_nullable(strategy):
    schema = {
        'vertexlabels': [{'id': 1, 'name': 'person', 'properties': ['name'],
                          'id_strategy': strategy, 'primary_keys': ['name'],
                          'nullable_keys': ['name']}],
        'edgelabels': [],
        'propertykeys': [{'name': 'name', 'data_type': 'TEXT', 'cardinality': 'SINGLE'}],
    }
    issues = validate_schema(schema)
    assert any('cannot be nullable' in issue.message for issue in issues)
