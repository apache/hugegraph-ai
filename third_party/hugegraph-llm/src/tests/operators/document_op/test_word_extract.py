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
from unittest.mock import MagicMock, patch

from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.document_op.word_extract import WordExtract


class TestWordExtract(unittest.TestCase):
    def setUp(self):
        self.test_query_en = "This is a test query about artificial intelligence."
        self.test_query_zh = "这是一个关于人工智能的测试查询。"
        self.mock_llm = MagicMock(spec=BaseLLM)

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        word_extract = WordExtract()
        # pylint: disable=protected-access
        self.assertIsNone(word_extract._llm)
        self.assertIsNone(word_extract._query)
        # Language is set from llm_settings and will be "en" or "cn" initially
        self.assertIsNotNone(word_extract._language)

    def test_init_with_parameters(self):
        """Test initialization with provided parameters."""
        word_extract = WordExtract(text=self.test_query_en, llm=self.mock_llm)
        # pylint: disable=protected-access
        self.assertEqual(word_extract._llm, self.mock_llm)
        self.assertEqual(word_extract._query, self.test_query_en)
        # Language is now set from llm_settings
        self.assertIsNotNone(word_extract._language)

    @patch("hugegraph_llm.models.llms.init_llm.LLMs")
    def test_run_with_query_in_context(self, mock_llms_class):
        """Test running with query in context."""
        # Setup mock
        mock_llm_instance = MagicMock(spec=BaseLLM)
        mock_llms_instance = MagicMock()
        mock_llms_instance.get_extract_llm.return_value = mock_llm_instance
        mock_llms_class.return_value = mock_llms_instance

        # Create context with query
        context = {"query": self.test_query_en}

        # Create WordExtract instance without query
        word_extract = WordExtract()

        # Run the extraction
        result = word_extract.run(context)

        # Verify that the query was taken from context
        # pylint: disable=protected-access
        self.assertEqual(word_extract._query, self.test_query_en)
        self.assertIn("keywords", result)
        self.assertIsInstance(result["keywords"], list)
        self.assertGreater(len(result["keywords"]), 0)

    def test_run_with_provided_query(self):
        """Test running with query provided at initialization."""
        # Create context without query
        context = {}

        # Create WordExtract instance with query
        word_extract = WordExtract(text=self.test_query_en, llm=self.mock_llm)

        # Run the extraction
        result = word_extract.run(context)

        # Verify that the query was used
        self.assertEqual(result["query"], self.test_query_en)
        self.assertIn("keywords", result)
        self.assertIsInstance(result["keywords"], list)
        self.assertGreater(len(result["keywords"]), 0)

    def test_run_with_language_in_context(self):
        """Test running with language set from llm_settings."""
        # Create context
        context = {"query": self.test_query_en}

        # Create WordExtract instance
        word_extract = WordExtract(llm=self.mock_llm)

        # Run the extraction
        result = word_extract.run(context)

        # Verify that the language was converted after run()
        # pylint: disable=protected-access
        self.assertIn(word_extract._language, ["english", "chinese"])

        # Verify the result contains expected keys
        self.assertIn("keywords", result)
        self.assertIsInstance(result["keywords"], list)

    def test_filter_keywords_lowercase(self):
        """Test filtering keywords with lowercase option."""
        word_extract = WordExtract(llm=self.mock_llm)
        keywords = ["Test", "EXAMPLE", "Multi-Word Phrase"]

        # Filter with lowercase=True
        # pylint: disable=protected-access
        result = word_extract._filter_keywords(keywords, lowercase=True)

        # Check that words are lowercased
        self.assertIn("test", result)
        self.assertIn("example", result)

        # Check that multi-word phrases are split
        self.assertIn("multi", result)
        self.assertIn("word", result)
        self.assertIn("phrase", result)

    def test_filter_keywords_no_lowercase(self):
        """Test filtering keywords without lowercase option."""
        word_extract = WordExtract(llm=self.mock_llm)
        keywords = ["Test", "EXAMPLE", "Multi-Word Phrase"]

        # Filter with lowercase=False
        # pylint: disable=protected-access
        result = word_extract._filter_keywords(keywords, lowercase=False)

        # Check that original case is preserved
        self.assertIn("Test", result)
        self.assertIn("EXAMPLE", result)
        self.assertIn("Multi-Word Phrase", result)

        # Check that multi-word phrases are still split
        self.assertTrue(any(w in result for w in ["Multi", "Word", "Phrase"]))

    def test_run_with_chinese_text(self):
        """Test running with Chinese text."""
        # Create context
        context = {}

        # Create WordExtract instance with Chinese text (language set from llm_settings)
        word_extract = WordExtract(text=self.test_query_zh, llm=self.mock_llm)

        # Run the extraction
        result = word_extract.run(context)

        # Verify that keywords were extracted
        self.assertIn("keywords", result)
        self.assertIsInstance(result["keywords"], list)
        self.assertGreater(len(result["keywords"]), 0)
        # Check for expected Chinese keywords
        self.assertTrue(
            any("人工" in keyword for keyword in result["keywords"])
            or any("智能" in keyword for keyword in result["keywords"])
        )


if __name__ == "__main__":
    unittest.main()
