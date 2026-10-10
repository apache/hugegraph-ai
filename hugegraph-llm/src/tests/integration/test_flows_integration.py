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

import pytest

from hugegraph_llm.config.prompt_config import PromptConfig
from hugegraph_llm.demo.rag_demo.rag_block import update_ui_configs
from hugegraph_llm.demo.rag_demo.text2gremlin_block import build_example_vector_index
from hugegraph_llm.demo.rag_demo.vector_graph_block import load_query_examples
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.utils.log import log


class TestFlowsIntegration:
    """Flow集成测试 - 验证各个Flow能正常执行不抛异常"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.index_text = """
        梁漱溟年轻时，一日，他与父亲梁济讨论当时一战欧洲的时局，梁济突然问道：“这个世界会好吗？”梁漱溟答：“我相信世界是一天一天往好里去的。”梁济叹道：“能好就好啊！”然后离家，三日后，梁济投湖自尽。晚年梁漱溟回忆自己的一生和跌宕起伏的近代社会，总结了一本书，书名就叫《这个世界会好吗？》。梁漱溟的回答与年轻时一致。但很多人特别是遗老遗少们总在回忆往日的时光，仿佛那是人类的黄金时代。如同鲁迅笔下的九斤老太，整日里念叨着“一代不如一代”。或者极端如梁济，对世界未来充满悲观，一死了之。在今天的时代，很多人认为“世界正变得越来越糟”，这其中不乏知名的知识分子。平克将这种情况称之为「进步恐惧症」，并总结为「认知偏差」。因为每天的新闻报道里总是充斥着战争、恐怖主义、犯罪、污染等坏消息，不是因为这些事情是主流，而是因为它们是热点，导致给人们的印象是世界越来越糟。所谓“好事不出门，坏事传千里”，而在互联网时代，发达的信息传播让坏事传播的更快更广。要纠正这种「可得性偏差」的方法是用数据说话。数字是最能反应趋势，看战争的比例、犯罪死亡人数在总人数的占比，就能看出犯罪是增加了，还是减少了。实际上，从各种数字显示，人类暴力事件在历史呈明显的下降趋势，这在平克之前发表的另一大部头著作《人性中的善良天使：暴力为什么会减少》中详细阐述过。世界变得更好了，说到底就是进步。
        """
        self.scheduler = SchedulerSingleton.get_instance()

    def test_build_knowledge_graph(self):
        try:
            res = self.scheduler.schedule_flow(FlowName.BUILD_VECTOR_INDEX, [self.index_text])
            assert "chunks" in res, "The result of BUILD_VECTOR_INDEX flow should contain 'chunks' field"
            log.info("✓ BUILD_VECTOR_INDEX flow executed successfully")

            schema = """
            {
                "vertexlabels": [
                    {
                    "id": 1,
                    "name": "Person",
                    "id_strategy": "PRIMARY_KEY",
                    "primary_keys": [
                        "name"
                    ],
                    "properties": [
                        "name",
                        "age",
                        "occupation"
                    ]
                    },
                    {
                    "id": 2,
                    "name": "Book",
                    "id_strategy": "PRIMARY_KEY",
                    "primary_keys": [
                        "title"
                    ],
                    "properties": [
                        "title",
                        "author",
                        "year"
                    ]
                    },
                    {
                    "id": 3,
                    "name": "Concept",
                    "id_strategy": "PRIMARY_KEY",
                    "primary_keys": [
                        "name"
                    ],
                    "properties": [
                        "name",
                        "description"
                    ]
                    }
                ],
                "edgelabels": [
                    {
                    "id": 1,
                    "name": "Wrote",
                    "source_label": "Person",
                    "target_label": "Book",
                    "properties": []
                    },
                    {
                    "id": 2,
                    "name": "Discussed",
                    "source_label": "Person",
                    "target_label": "Concept",
                    "properties": []
                    },
                    {
                    "id": 3,
                    "name": "Believes",
                    "source_label": "Person",
                    "target_label": "Concept",
                    "properties": []
                    }
                ]
            }
            """

            data = self.scheduler.schedule_flow(
                FlowName.GRAPH_EXTRACT,
                schema,
                [self.index_text],
                PromptConfig.extract_graph_prompt_EN,
                "property_graph",
            )
            assert "vertices" in data, "The result of GRAPH_EXTRACT flow should contain 'vertices' field"
            assert "edges" in data, "The result of GRAPH_EXTRACT flow should contain 'edges' field"
            log.info("✓ GRAPH_EXTRACT flow executed successfully")

            res = self.scheduler.schedule_flow(FlowName.IMPORT_GRAPH_DATA, data, schema)
            assert res is not None, "The result of IMPORT_GRAPH_DATA flow should not be None"
            log.info("✓ IMPORT_GRAPH_DATA flow executed successfully")

            self.scheduler.schedule_flow(FlowName.UPDATE_VID_EMBEDDINGS)
            log.info("✓ UPDATE_VID_EMBEDDING flow executed successfully")
        except Exception as e:
            pytest.fail(f"BUILD_VECTOR_INDEX flow failed: {e}")

    def test_schema_generator(self):
        try:
            query_examples = load_query_examples()

            few_shot = """
            {
            "vertexlabels": [
                {
                "id": 1,
                "name": "person",
                "id_strategy": "PRIMARY_KEY",
                "primary_keys": [
                    "name"
                ],
                "properties": [
                    "name",
                    "age",
                    "occupation"
                ]
                },
                {
                "id": 2,
                "name": "webpage",
                "id_strategy": "PRIMARY_KEY",
                "primary_keys": [
                    "name"
                ],
                "properties": [
                    "name",
                    "url"
                ]
                }
            ],
            "edgelabels": [
                {
                "id": 1,
                "name": "roommate",
                "source_label": "person",
                "target_label": "person",
                "properties": [
                    "date"
                ]
                },
                {
                "id": 2,
                "name": "link",
                "source_label": "webpage",
                "target_label": "person",
                "properties": []
                }
            ]
            }
            """

            self.scheduler.schedule_flow(FlowName.BUILD_SCHEMA, [self.index_text], query_examples, few_shot)
        except Exception as e:
            pytest.fail(f"BUILD_VECTOR_INDEX flow failed: {e}")

    def test_graph_extract_prompt(self):
        try:
            scenario = "social relationships"
            example_name = "Official Person-Relationship Extraction"

            res = self.scheduler.schedule_flow(FlowName.PROMPT_GENERATE, self.index_text, scenario, example_name)
            assert res is not None, "The result of PROMPT_GENERATE flow should not be None"
        except Exception as e:
            pytest.fail(f"BUILD_VECTOR_INDEX flow failed: {e}")

    def test_rag(self):
        query = "梁漱溟和梁济的关系是什么？"

        raw_answer = True
        vector_only_answer = False
        graph_only_answer = False
        graph_vector_answer = False
        graph_ratio = 0.6
        rerank_method = "bleu"
        near_neighbor_first = False
        custom_related_information = ""

        graph_search, gremlin_prompt, vector_search = update_ui_configs(
            PromptConfig.answer_prompt_EN,
            custom_related_information,
            graph_only_answer,
            graph_vector_answer,
            None,
            PromptConfig.keywords_extract_prompt_EN,
            query,
            vector_only_answer,
        )

        res = self.scheduler.schedule_flow(
            FlowName.RAG_RAW,
            query=query,
            vector_search=vector_search,
            graph_search=graph_search,
            raw_answer=raw_answer,
            vector_only_answer=vector_only_answer,
            graph_only_answer=graph_only_answer,
            graph_vector_answer=graph_vector_answer,
            graph_ratio=graph_ratio,
            rerank_method=rerank_method,
            near_neighbor_first=near_neighbor_first,
            custom_related_information=custom_related_information,
            answer_prompt=PromptConfig.answer_prompt_EN,
            keywords_extract_prompt=PromptConfig.keywords_extract_prompt_EN,
            gremlin_tmpl_num=-1,
            gremlin_prompt=gremlin_prompt,
        )
        assert res is not None, "The result of RAG flow should not be None"

        raw_answer = False
        vector_only_answer = True
        graph_only_answer = False
        graph_vector_answer = False
        res = self.scheduler.schedule_flow(
            FlowName.RAG_VECTOR_ONLY,
            query=query,
            vector_search=vector_search,
            graph_search=graph_search,
            raw_answer=raw_answer,
            vector_only_answer=vector_only_answer,
            graph_only_answer=graph_only_answer,
            graph_vector_answer=graph_vector_answer,
            graph_ratio=graph_ratio,
            rerank_method=rerank_method,
            near_neighbor_first=near_neighbor_first,
            custom_related_information=custom_related_information,
            answer_prompt=PromptConfig.answer_prompt_EN,
            keywords_extract_prompt=PromptConfig.keywords_extract_prompt_EN,
            gremlin_tmpl_num=-1,
            gremlin_prompt=gremlin_prompt,
        )
        assert res is not None, "The result of RAG flow should not be None"

        raw_answer = False
        vector_only_answer = False
        graph_only_answer = True
        graph_vector_answer = False
        res = self.scheduler.schedule_flow(
            FlowName.RAG_GRAPH_ONLY,
            query=query,
            vector_search=vector_search,
            graph_search=graph_search,
            raw_answer=raw_answer,
            vector_only_answer=vector_only_answer,
            graph_only_answer=graph_only_answer,
            graph_vector_answer=graph_vector_answer,
            graph_ratio=graph_ratio,
            rerank_method=rerank_method,
            near_neighbor_first=near_neighbor_first,
            custom_related_information=custom_related_information,
            answer_prompt=PromptConfig.answer_prompt_EN,
            keywords_extract_prompt=PromptConfig.keywords_extract_prompt_EN,
            gremlin_tmpl_num=-1,
            gremlin_prompt=gremlin_prompt,
        )
        assert res is not None, "The result of RAG flow should not be None"

        raw_answer = False
        vector_only_answer = False
        graph_only_answer = False
        graph_vector_answer = True
        res = self.scheduler.schedule_flow(
            FlowName.RAG_GRAPH_VECTOR,
            query=query,
            vector_search=vector_search,
            graph_search=graph_search,
            raw_answer=raw_answer,
            vector_only_answer=vector_only_answer,
            graph_only_answer=graph_only_answer,
            graph_vector_answer=graph_vector_answer,
            graph_ratio=graph_ratio,
            rerank_method=rerank_method,
            near_neighbor_first=near_neighbor_first,
            custom_related_information=custom_related_information,
            answer_prompt=PromptConfig.answer_prompt_EN,
            keywords_extract_prompt=PromptConfig.keywords_extract_prompt_EN,
            gremlin_tmpl_num=-1,
            gremlin_prompt=gremlin_prompt,
        )
        assert res is not None, "The result of RAG flow should not be None"

    def test_build_example_index(self):
        res = build_example_vector_index(None)
        assert "embed_dim" in res, "The result of build_example_vector_index should contain embed_dim"

    def test_text_2_gremlin(self):
        query = "梁漱溟和梁济的关系是什么？"
        schema = "hugegraph"
        example_num = 2

        res = self.scheduler.schedule_flow(
            FlowName.TEXT2GREMLIN, query, example_num, schema, PromptConfig.gremlin_generate_prompt_EN, None
        )

        assert res is not None, "The result of TEXT2GREMLIN flow should not be None"
