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

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Union

from hugegraph_llm.config import prompt
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.models.llms.init_llm import LLMs
from hugegraph_llm.utils.log import log


class GremlinGenerateSynthesize:
    def __init__(
        self,
        llm: BaseLLM = None,
        schema: Optional[Union[dict, str]] = None,
        vertices: Optional[List[str]] = None,
        gremlin_prompt: Optional[str] = None,
    ) -> None:
        self.llm = llm or LLMs().get_text2gql_llm()
        if isinstance(schema, dict):
            schema = json.dumps(schema, ensure_ascii=False)
        self.schema = schema
        self.vertices = vertices
        self.gremlin_prompt = gremlin_prompt or prompt.gremlin_generate_prompt

    # TODO: Tag is used to standardize gql output, maybe remove it in future
    def _extract_response(self, response: str, label: str = "gremlin") -> str:
        match = re.search(f"```{label}(.*?)```", response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return response.strip()

    def _format_examples(self, examples: Optional[List[Dict[str, str]]]) -> Optional[str]:
        if not examples:
            return None
        example_strings = []
        for example in examples:
            example_strings.append(f"- query: {example['query']}\n- gremlin:\n```gremlin\n{example['gremlin']}\n```")
        return "\n\n".join(example_strings)

    def _format_vertices(self, vertices: Optional[List[str]]) -> Optional[str]:
        if not vertices:
            return None
        return "\n".join([f"- '{vid}'" for vid in vertices])

    def _format_properties(self, properties: Optional[List[tuple]]) -> Optional[str]:
        if not properties:
            return None
        return str(properties)

    async def async_generate(self, context: Dict[str, Any]):
        async_tasks = {}
        query = context.get("query")
        raw_example = [{"query": "who is peter", "gremlin": "g.V().has('name', 'peter')"}]
        raw_prompt = self.gremlin_prompt.format(
            query=query,
            schema=self.schema,
            example=self._format_examples(examples=raw_example),
            vertices=self._format_vertices(vertices=self.vertices),
            properties=self._format_properties(properties=None),
        )
        async_tasks["raw_answer"] = asyncio.create_task(self.llm.agenerate(prompt=raw_prompt))

        examples = context.get("match_result")
        init_prompt = self.gremlin_prompt.format(
            query=query,
            schema=self.schema,
            example=self._format_examples(examples=examples),
            vertices=self._format_vertices(vertices=self.vertices),
            properties=self._format_properties(properties=None),
        )
        async_tasks["initialized_answer"] = asyncio.create_task(self.llm.agenerate(prompt=init_prompt))

        raw_response = await async_tasks["raw_answer"]
        initialized_response = await async_tasks["initialized_answer"]
        log.debug(
            "Text2Gremlin with tmpl prompt:\n %s,\n LLM Response: %s",
            init_prompt,
            initialized_response,
        )

        context["result"] = self._extract_response(response=initialized_response)
        context["raw_result"] = self._extract_response(response=raw_response)
        context["call_count"] = context.get("call_count", 0) + 2

        return context

    def sync_generate(self, context: Dict[str, Any]):
        query = context.get("query")
        raw_example = [{"query": "who is peter", "gremlin": "g.V().has('name', 'peter')"}]
        raw_prompt = self.gremlin_prompt.format(
            query=query,
            schema=self.schema,
            example=self._format_examples(examples=raw_example),
            vertices=self._format_vertices(vertices=self.vertices),
            properties=self._format_properties(properties=None),
        )
        raw_response = self.llm.generate(prompt=raw_prompt)

        examples = context.get("match_result")
        init_prompt = self.gremlin_prompt.format(
            query=query,
            schema=self.schema,
            example=self._format_examples(examples=examples),
            vertices=self._format_vertices(vertices=self.vertices),
            properties=self._format_properties(properties=None),
        )
        initialized_response = self.llm.generate(prompt=init_prompt)

        log.debug(
            "Text2Gremlin with tmpl prompt:\n %s,\n LLM Response: %s",
            init_prompt,
            initialized_response,
        )

        context["result"] = self._extract_response(response=initialized_response)
        context["raw_result"] = self._extract_response(response=raw_response)
        context["call_count"] = context.get("call_count", 0) + 2

        return context

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        query = context.get("query", "")
        if not query:
            raise ValueError("query is required")

        # TODO: Update to async_generate again
        #       The best method may be changing all `operator.run(*arg)` to be async function
        context = self.sync_generate(context)
        return context
