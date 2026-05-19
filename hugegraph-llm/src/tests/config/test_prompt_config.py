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

from hugegraph_llm.config.prompt_config import PromptConfig


def test_extract_graph_prompt_en_defines_deterministic_vertex_id_rules():
    prompt = PromptConfig.extract_graph_prompt_EN

    assert "vertexlabels[].id" in prompt
    assert "id = \"{vertexLabelID}:{properties.<primary_key>}\"" in prompt
    assert "id = \"{vertexLabelID}:{properties.<pk1>}!{properties.<pk2>}\"" in prompt
    assert 'Never use label names such as "person:Sarah"' in prompt
    assert "outV and inV must exactly match the id of vertices in the same output" in prompt
    assert 'Every vertex must include "type":"vertex"' in prompt
    assert 'Every edge must include "type":"edge"' in prompt
    assert "Do not translate schema field names" in prompt
    assert '{"vertices": [...], "edges": [...]}' in prompt


def test_extract_graph_prompt_cn_matches_en_vertex_id_contract():
    prompt = PromptConfig.extract_graph_prompt_CN

    assert "vertexlabels[].id" in prompt
    assert 'id = "{vertexLabelID}:{properties.<primary_key>}"' in prompt
    assert 'id = "{vertexLabelID}:{properties.<pk1>}!{properties.<pk2>}"' in prompt
    assert '不要使用 "person:Sarah"' in prompt
    assert "outV 和 inV 必须严格等于本次输出 vertices 中的 id" in prompt
    assert '每个顶点必须包含 "type":"vertex"' in prompt
    assert '每条边必须包含 "type":"edge"' in prompt
    assert "不要翻译 schema 字段名" in prompt
    assert '{"vertices": [...], "edges": [...]}' in prompt
