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


"""Validate the shipped faithfulness prompt as the Judge sees it."""

import re

import pytest

from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import (
    FaithfulnessJudgeOutput,
)
from hugegraph_llm_eval.prompt import graph_judge_prompt

_EXAMPLE_OUTPUT_HEADING = {"en": "Example output:\n", "zh": "示例输出：\n"}


@pytest.mark.parametrize("language", ("en", "zh"))
def test_faithfulness_example_output_matches_the_judge_schema(language: str) -> None:
    prompt = graph_judge_prompt("faithfulness", language)
    output = FaithfulnessJudgeOutput.model_validate_json(prompt.split(_EXAMPLE_OUTPUT_HEADING[language], 1)[1])

    unsupported_vertices = {index for group in output.unsupported_vertex_groups for index in group.item_indices}
    assert output.supported_vertex_indices == (0,)
    assert 1 in unsupported_vertices


@pytest.mark.parametrize("language", ("en", "zh"))
def test_faithfulness_prompt_defines_edge_direction(language: str) -> None:
    prompt = graph_judge_prompt("faithfulness", language)

    assert "out_v" in prompt
    assert "in_v" in prompt
    assert "{{" not in prompt


def test_english_faithfulness_prompt_has_no_chinese() -> None:
    assert re.search(r"[\u4e00-\u9fff]", graph_judge_prompt("faithfulness", "en")) is None
