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

import unittest
from unittest.mock import patch

from hugegraph_llm.models.rerankers.cohere import CohereReranker
from hugegraph_llm.models.rerankers.init_reranker import Rerankers
from hugegraph_llm.models.rerankers.siliconflow import SiliconReranker


class TestRerankers(unittest.TestCase):
    @patch("hugegraph_llm.models.rerankers.init_reranker.llm_settings")
    def test_get_cohere_reranker(self, mock_settings):
        # Configure mock settings for Cohere
        mock_settings.reranker_type = "cohere"
        mock_settings.reranker_api_key = "test_api_key"
        mock_settings.cohere_base_url = "https://api.cohere.ai/v1/rerank"
        mock_settings.reranker_model = "rerank-english-v2.0"

        # Initialize reranker
        rerankers = Rerankers()
        reranker = rerankers.get_reranker()

        # Assertions
        self.assertIsInstance(reranker, CohereReranker)
        self.assertEqual(reranker.api_key, "test_api_key")
        self.assertEqual(reranker.base_url, "https://api.cohere.ai/v1/rerank")
        self.assertEqual(reranker.model, "rerank-english-v2.0")

    @patch("hugegraph_llm.models.rerankers.init_reranker.llm_settings")
    def test_get_siliconflow_reranker(self, mock_settings):
        # Configure mock settings for SiliconFlow
        mock_settings.reranker_type = "siliconflow"
        mock_settings.reranker_api_key = "test_api_key"
        mock_settings.reranker_model = "bge-reranker-large"

        # Initialize reranker
        rerankers = Rerankers()
        reranker = rerankers.get_reranker()

        # Assertions
        self.assertIsInstance(reranker, SiliconReranker)
        self.assertEqual(reranker.api_key, "test_api_key")
        self.assertEqual(reranker.model, "bge-reranker-large")

    @patch("hugegraph_llm.models.rerankers.init_reranker.llm_settings")
    def test_unsupported_reranker_type(self, mock_settings):
        # Configure mock settings with unsupported reranker type
        mock_settings.reranker_type = "unsupported_type"

        # Initialize reranker
        rerankers = Rerankers()

        # Assertions
        with self.assertRaises(Exception) as cm:
            rerankers.get_reranker()

        self.assertTrue("Reranker type is not supported!" in str(cm.exception))
