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

from hugegraph_llm.operators.document_op.chunk_split import ChunkSplit


class TestChunkSplit(unittest.TestCase):
    def setUp(self):
        self.test_text_en = (
            "This is a test. It has multiple sentences. And some paragraphs.\n\nThis is another paragraph."
        )
        self.test_text_zh = "这是一个测试。它有多个句子。还有一些段落。\n\n这是另一个段落。"
        self.test_texts = [self.test_text_en, self.test_text_zh]

    def test_init_with_string(self):
        """Test initialization with a single string."""
        chunk_split = ChunkSplit(self.test_text_en)
        self.assertEqual(len(chunk_split.texts), 1)
        self.assertEqual(chunk_split.texts[0], self.test_text_en)

    def test_init_with_list(self):
        """Test initialization with a list of strings."""
        chunk_split = ChunkSplit(self.test_texts)
        self.assertEqual(len(chunk_split.texts), 2)
        self.assertEqual(chunk_split.texts, self.test_texts)

    def test_get_separators_zh(self):
        """Test getting Chinese separators."""
        chunk_split = ChunkSplit("", language="zh")
        separators = chunk_split.separators
        self.assertEqual(separators, ["\n\n", "\n", "。", "，", ""])

    def test_get_separators_en(self):
        """Test getting English separators."""
        chunk_split = ChunkSplit("", language="en")
        separators = chunk_split.separators
        self.assertEqual(separators, ["\n\n", "\n", ".", ",", " ", ""])

    def test_get_separators_invalid(self):
        """Test getting separators with invalid language."""
        with self.assertRaises(ValueError):
            ChunkSplit("", language="fr")

    def test_get_text_splitter_document(self):
        """Test getting document text splitter."""
        chunk_split = ChunkSplit("test", split_type="document")
        result = chunk_split.text_splitter("test")
        self.assertEqual(result, ["test"])

    def test_get_text_splitter_paragraph(self):
        """Test getting paragraph text splitter."""
        chunk_split = ChunkSplit("test", split_type="paragraph")
        self.assertIsNotNone(chunk_split.text_splitter)

    def test_get_text_splitter_sentence(self):
        """Test getting sentence text splitter."""
        chunk_split = ChunkSplit("test", split_type="sentence")
        self.assertIsNotNone(chunk_split.text_splitter)

    def test_get_text_splitter_invalid(self):
        """Test getting text splitter with invalid type."""
        with self.assertRaises(ValueError):
            ChunkSplit("test", split_type="invalid")

    def test_run_document_split(self):
        """Test running document split."""
        chunk_split = ChunkSplit(self.test_text_en, split_type="document")
        result = chunk_split.run(None)
        self.assertEqual(len(result["chunks"]), 1)
        self.assertEqual(result["chunks"][0], self.test_text_en)

    def test_run_paragraph_split(self):
        """Test running paragraph split."""
        # Use a text with more distinct paragraphs to ensure splitting
        text_with_paragraphs = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunk_split = ChunkSplit(text_with_paragraphs, split_type="paragraph")
        result = chunk_split.run(None)
        # Verify that chunks are created
        self.assertGreaterEqual(len(result["chunks"]), 1)
        # Verify that the chunks contain the expected content
        all_text = " ".join(result["chunks"])
        self.assertIn("First paragraph", all_text)
        self.assertIn("Second paragraph", all_text)
        self.assertIn("Third paragraph", all_text)

    def test_run_sentence_split(self):
        """Test running sentence split."""
        # Use a text with more distinct sentences to ensure splitting
        text_with_sentences = "This is the first sentence. This is the second sentence. This is the third sentence."
        chunk_split = ChunkSplit(text_with_sentences, split_type="sentence")
        result = chunk_split.run(None)
        # Verify that chunks are created
        self.assertGreaterEqual(len(result["chunks"]), 1)
        # Verify that the chunks contain the expected content
        all_text = " ".join(result["chunks"])
        # Check for partial content since the splitter might break words
        self.assertIn("first", all_text)
        self.assertIn("second", all_text)
        self.assertIn("third", all_text)

    def test_run_with_context(self):
        """Test running with context."""
        context = {"existing_key": "value"}
        chunk_split = ChunkSplit(self.test_text_en)
        result = chunk_split.run(context)
        self.assertEqual(result["existing_key"], "value")
        self.assertIn("chunks", result)

    def test_run_with_multiple_texts(self):
        """Test running with multiple texts."""
        chunk_split = ChunkSplit(self.test_texts)
        result = chunk_split.run(None)
        # Should have at least one chunk per text
        self.assertGreaterEqual(len(result["chunks"]), len(self.test_texts))


if __name__ == "__main__":
    unittest.main()
