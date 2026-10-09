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
import os
from typing import Any, Dict

from hugegraph_llm.config import prompt as prompt_tpl
from hugegraph_llm.config import resource_path
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.utils.log import log


class PromptGenerate:
    def __init__(self, llm: BaseLLM):
        self.llm = llm

    def _load_few_shot_example(self, example_name: str) -> Dict[str, Any]:
        """Loads and finds the specified few-shot example from the unified JSON file."""
        examples_path = os.path.join(resource_path, "prompt_examples", "prompt_examples.json")
        if not os.path.exists(examples_path):
            raise FileNotFoundError(f"Examples file not found: {examples_path}")
        with open(examples_path, "r", encoding="utf-8") as f:
            all_examples = json.load(f)
        for example in all_examples:
            if example.get("name") == example_name:
                return example
        raise ValueError(f"Example with name '{example_name}' not found in prompt_examples.json")

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the core logic of prompt generation."""
        source_text = context.get("source_text")
        scenario = context.get("scenario")
        example_name = context.get("example_name")

        if not all([source_text, scenario, example_name]):
            raise ValueError("Missing required context: source_text, scenario, or example_name.")
        few_shot_example = self._load_few_shot_example(example_name)

        meta_prompt = prompt_tpl.generate_extract_prompt_template.format(
            few_shot_text=few_shot_example.get("text", ""),
            few_shot_prompt=few_shot_example.get("prompt", ""),
            user_text=source_text,
            user_scenario=scenario,
            language=prompt_tpl.llm_settings.language,
        )
        log.debug("Meta-prompt sent to LLM: %s", meta_prompt)
        generated_prompt = self.llm.generate(prompt=meta_prompt)
        log.debug("Generated prompt from LLM: %s", generated_prompt)

        context["generated_extract_prompt"] = generated_prompt
        return context
