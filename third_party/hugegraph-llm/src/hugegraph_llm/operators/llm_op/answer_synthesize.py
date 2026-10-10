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

"""
TODO: It is not clear whether there is any other dependence on the SCHEMA_EXAMPLE_PROMPT variable.
Because the SCHEMA_EXAMPLE_PROMPT variable will no longer change based on
prompt.extract_graph_prompt changes after the system loads, this does not seem to meet expectations.
"""

# pylint: disable=W0621

import asyncio
from typing import Any, AsyncGenerator, Dict, Optional

from hugegraph_llm.config import prompt
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.models.llms.init_llm import LLMs
from hugegraph_llm.utils.log import log

DEFAULT_ANSWER_TEMPLATE = prompt.answer_prompt


class AnswerSynthesize:
    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        prompt_template: Optional[str] = None,
        question: Optional[str] = None,
        context_body: Optional[str] = None,
        context_head: Optional[str] = None,
        context_tail: Optional[str] = None,
        raw_answer: bool = False,
        vector_only_answer: bool = True,
        graph_only_answer: bool = False,
        graph_vector_answer: bool = False,
    ):
        self._llm = llm
        self._prompt_template = prompt_template or DEFAULT_ANSWER_TEMPLATE
        self._question = question
        self._context_body = context_body
        self._context_head = context_head
        self._context_tail = context_tail
        self._raw_answer = raw_answer
        self._vector_only_answer = vector_only_answer
        self._graph_only_answer = graph_only_answer
        self._graph_vector_answer = graph_vector_answer

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        context_head_str, context_tail_str = self.init_llm(context)

        if self._context_body is not None:
            context_str = f"{context_head_str}\n{self._context_body}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            response = self._llm.generate(prompt=final_prompt)
            return {"answer": response}

        graph_result_context, vector_result_context = self.handle_vector_graph(context)
        context = asyncio.run(
            self.async_generate(
                context,
                context_head_str,
                context_tail_str,
                vector_result_context,
                graph_result_context,
            )
        )
        return context

    def init_llm(self, context):
        if self._llm is None:
            self._llm = LLMs().get_chat_llm()
        if self._question is None:
            self._question = context.get("query") or None
        assert self._question is not None, "No question for synthesizing."
        context_head_str = context.get("synthesize_context_head") or self._context_head or ""
        context_tail_str = context.get("synthesize_context_tail") or self._context_tail or ""
        return context_head_str, context_tail_str

    def handle_vector_graph(self, context):
        vector_result = context.get("vector_result")
        if vector_result:
            vector_result_context = "Phrases related to the query:\n" + "\n".join(
                f"{i + 1}. {res}" for i, res in enumerate(vector_result)
            )
        else:
            vector_result_context = "No (vector)phrase related to the query."
        graph_result = context.get("graph_result")
        if graph_result:
            graph_context_head = context.get("graph_context_head", "Knowledge from graphdb for the query:\n")
            graph_result_context = graph_context_head + "\n".join(
                f"{i + 1}. {res}" for i, res in enumerate(graph_result)
            )
        else:
            graph_result_context = "No related graph data found for current query."
            log.warning(graph_result_context)
        return graph_result_context, vector_result_context

    async def run_streaming(self, context: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        context_head_str, context_tail_str = self.init_llm(context)

        if self._context_body is not None:
            context_str = f"{context_head_str}\n{self._context_body}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            response = self._llm.generate(prompt=final_prompt)
            yield {"answer": response}
            return

        graph_result_context, vector_result_context = self.handle_vector_graph(context)

        async for context in self.async_streaming_generate(
            context, context_head_str, context_tail_str, vector_result_context, graph_result_context
        ):
            yield context

    async def async_generate(
        self,
        context: Dict[str, Any],
        context_head_str: str,
        context_tail_str: str,
        vector_result_context: str,
        graph_result_context: str,
    ):
        # async_tasks stores the async tasks for different answer types
        async_tasks = {}
        if self._raw_answer:
            final_prompt = self._question
            async_tasks["raw_task"] = asyncio.create_task(self._llm.agenerate(prompt=final_prompt))
        if self._vector_only_answer:
            context_str = f"{context_head_str}\n{vector_result_context}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_tasks["vector_only_task"] = asyncio.create_task(self._llm.agenerate(prompt=final_prompt))
        if self._graph_only_answer:
            context_str = f"{context_head_str}\n{graph_result_context}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_tasks["graph_only_task"] = asyncio.create_task(self._llm.agenerate(prompt=final_prompt))
        if self._graph_vector_answer:
            context_body_str = f"{vector_result_context}\n{graph_result_context}"
            if context.get("graph_ratio", 0.5) < 0.5:
                context_body_str = f"{graph_result_context}\n{vector_result_context}"
            context_str = f"{context_head_str}\n{context_body_str}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_tasks["graph_vector_task"] = asyncio.create_task(self._llm.agenerate(prompt=final_prompt))

        async_tasks_mapping = {
            "raw_task": "raw_answer",
            "vector_only_task": "vector_only_answer",
            "graph_only_task": "graph_only_answer",
            "graph_vector_task": "graph_vector_answer",
        }

        for task_key, context_key in async_tasks_mapping.items():
            if async_tasks.get(task_key):
                response = await async_tasks[task_key]
                context[context_key] = response
                log.debug("Query Answer: %s", response)

        ops = sum(
            [
                self._raw_answer,
                self._vector_only_answer,
                self._graph_only_answer,
                self._graph_vector_answer,
            ]
        )
        context["call_count"] = context.get("call_count", 0) + ops
        return context

    async def async_streaming_generate(
        self,
        context: Dict[str, Any],
        context_head_str: str,
        context_tail_str: str,
        vector_result_context: str,
        graph_result_context: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # async_tasks stores the async tasks for different answer types
        async_generators = []
        auto_id = 0
        if self._raw_answer:
            final_prompt = self._question
            async_generators.append(
                self.__llm_generate_with_meta_info(task_id=auto_id, target_key="raw_answer", prompt=final_prompt)
            )
            auto_id += 1
        if self._vector_only_answer:
            context_str = f"{context_head_str}\n{vector_result_context}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_generators.append(
                self.__llm_generate_with_meta_info(
                    task_id=auto_id, target_key="vector_only_answer", prompt=final_prompt
                )
            )
            auto_id += 1
        if self._graph_only_answer:
            context_str = f"{context_head_str}\n{graph_result_context}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_generators.append(
                self.__llm_generate_with_meta_info(task_id=auto_id, target_key="graph_only_answer", prompt=final_prompt)
            )
            auto_id += 1
        if self._graph_vector_answer:
            context_body_str = f"{vector_result_context}\n{graph_result_context}"
            if context.get("graph_ratio", 0.5) < 0.5:
                context_body_str = f"{graph_result_context}\n{vector_result_context}"
            context_str = f"{context_head_str}\n{context_body_str}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_generators.append(
                self.__llm_generate_with_meta_info(
                    task_id=auto_id, target_key="graph_vector_answer", prompt=final_prompt
                )
            )
            auto_id += 1

        ops = sum(
            [
                self._raw_answer,
                self._vector_only_answer,
                self._graph_only_answer,
                self._graph_vector_answer,
            ]
        )
        context["call_count"] = context.get("call_count", 0) + ops

        async_tasks = [asyncio.create_task(anext(gen)) for gen in async_generators]
        while True:
            done, _ = await asyncio.wait(async_tasks, return_when=asyncio.FIRST_COMPLETED)
            stop_task_num = 0
            for task in done:
                try:
                    task_id, target_key, token = task.result()
                    context[target_key] = context.get(target_key, "") + token
                    gen = async_generators[task_id]
                    async_tasks[task_id] = asyncio.create_task(anext(gen))
                except StopAsyncIteration:
                    stop_task_num += 1
            if stop_task_num == len(async_tasks):
                break
            yield context

    async def __llm_generate_with_meta_info(self, task_id: int, target_key: str, prompt: str):
        # FIXME: Expected type 'AsyncIterable', got 'Coroutine[Any, Any, AsyncGenerator[str, None]]' instead
        async for token in self._llm.agenerate_streaming(prompt=prompt):
            yield task_id, target_key, token
