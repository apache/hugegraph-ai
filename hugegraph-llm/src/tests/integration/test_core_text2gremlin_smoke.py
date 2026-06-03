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

import json
from pathlib import Path

import pytest

from tests.fixtures.fake_llm import FakeLLM

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


def test_text2gremlin_smoke_normalizes_fake_llm_output():
    from hugegraph_llm.flows.text2gremlin import Text2GremlinFlow
    from hugegraph_llm.operators.llm_op.gremlin_generate import GremlinGenerateSynthesize
    from hugegraph_llm.state.ai_state import WkFlowInput

    schema_file = Path(__file__).resolve().parents[1] / "data" / "quality_program" / "text2gremlin_schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    generator = GremlinGenerateSynthesize(
        llm=FakeLLM(
            [
                "```gremlin\ng.V().hasLabel('quality_person')\n```",
                "Here is the query:\n```gremlin\ng.V().has('quality_person', 'name', 'marko')\n```",
            ]
        ),
        schema=schema,
    )

    result = generator.run({"query": "Find marko"})
    prepared = WkFlowInput()
    Text2GremlinFlow().prepare(
        prepared,
        query="Find marko",
        example_num=99,
        schema_input="hugegraph",
        gremlin_prompt_input=None,
        requested_outputs=["template_gremlin", "invalid_output"],
    )

    assert result["result"] == "g.V().has('quality_person', 'name', 'marko')"
    assert result["raw_result"] == "g.V().hasLabel('quality_person')"
    assert prepared.example_num == 10
    assert prepared.requested_outputs == ["template_gremlin"]


def test_text2gremlin_smoke_invalid_query_fails_explicitly():
    from hugegraph_llm.operators.llm_op.gremlin_generate import GremlinGenerateSynthesize

    generator = GremlinGenerateSynthesize(llm=FakeLLM(["g.V()", "g.V()"]))

    with pytest.raises(ValueError, match="query is required"):
        generator.run({"query": ""})
