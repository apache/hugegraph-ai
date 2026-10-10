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
import re
from typing import Any, Dict, List, Optional

from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.models.llms.init_llm import LLMs
from hugegraph_llm.utils.log import log


class SchemaBuilder:
    """Automated Schema Generator"""

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        schema_prompt: Optional[str] = None,
    ):
        self.llm = llm or LLMs().get_chat_llm()
        # TODO: use a basic format for it
        self.schema_prompt = (
            schema_prompt
            or """
            You are a Graph Schema Generator for Apache HugeGraph.
            Based on the following three parts of content, output a Schema JSON that complies with HugeGraph specifications:

            Inputs:
            1. Few‐Shot Schema Examples (already formatted as valid HugeGraph schema JSON):
            {few_shot_schema}

            2. Query Examples (each with a question description):
            {query_examples}

            3. Raw Data Samples (plain text records to model as vertices/edges):
            {raw_texts}

            Constraints:
            - Return only the JSON object
            - Ensure the schema follows HugeGraph specifications
            - Do not include comments or extra fields.
        """
        )

    def _format_raw_texts(self, raw_texts: List[str]) -> str:
        return "\n".join([f"- {text}" for text in raw_texts])

    def _format_query_examples(self, query_examples: List[str]) -> str:
        if not query_examples:
            return "None"
        examples = []
        for example in query_examples:
            examples.append(f"- {example}")
        return "\n".join(examples)

    def _format_few_shot_schema(self, few_shot_schema: Dict[str, Any]) -> str:
        if not few_shot_schema:
            return "None"
        return json.dumps(few_shot_schema, indent=2, ensure_ascii=False)

    def _extract_schema(self, response: str) -> Dict[str, Any]:
        # Try to extract JSON from Markdown code block
        match = re.search(r"```(?:json)?\s*(.*?)```", response, re.DOTALL)
        if match:
            response = match.group(1).strip()

        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            log.error("Failed to parse LLM response as JSON: %s", response)
            raise RuntimeError("Invalid JSON response from LLM") from e

    def build_prompt(
        self,
        raw_texts: List[str],
        query_examples: List[Dict[str, str]],
        few_shot_schema: Dict[str, Any],
    ) -> str:
        return self.schema_prompt.format(
            raw_texts=self._format_raw_texts(raw_texts),
            query_examples=self._format_query_examples(query_examples),
            few_shot_schema=self._format_few_shot_schema(few_shot_schema),
        )

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate schema from context containing raw_texts, query_examples and few_shot_schema.

        Args:
            context: Dictionary containing:
                - raw_texts: List of raw text samples
                - query_examples: List of query examples (description + Gremlin)
                - few_shot_schema: Example schema for few-shot learning

        Returns:
            Generated schema as dictionary
        """
        if not isinstance(context, dict):
            raise ValueError("Context must be a dictionary")
        if "raw_texts" not in context or not isinstance(context["raw_texts"], list):
            raise ValueError("'raw_texts' must be a list[str]")
        if "query_examples" not in context or not isinstance(context["query_examples"], list):
            raise ValueError("'query_examples' must be a list[str]")
        if "few_shot_schema" not in context or not isinstance(context["few_shot_schema"], dict):
            raise ValueError("'few_shot_schema' must be a dict")

        raw_texts = context["raw_texts"]
        query_examples = context["query_examples"]
        few_shot_schema = context["few_shot_schema"]

        prompt = self.build_prompt(raw_texts, query_examples, few_shot_schema)

        try:
            response = self.llm.generate(prompt=prompt)
            if not response or not response.strip():
                raise RuntimeError("LLM returned empty response")
        except Exception as e:
            log.error("LLM generation failed: %s", str(e))
            raise RuntimeError(f"Failed to generate schema: {str(e)}") from e

        schema = self._extract_schema(response)
        log.debug("Generated schema: %s", json.dumps(schema, indent=2))
        return schema
