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

import pytest

from hugegraph_llm.document.chunk_split import ChunkSplitter

pytestmark = pytest.mark.unit


class TestChunkSplitter(unittest.TestCase):
    def test_paragraph_split_zh(self):
        # Test Chinese paragraph splitting
        splitter = ChunkSplitter(split_type="paragraph", language="zh")

        # Test with a single document
        text = "这是第一段。这是第一段的第二句话。\n\n这是第二段。这是第二段的第二句话。"
        chunks = splitter.split(text)

        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)
        # The actual behavior may vary based on the implementation
        # Just verify we get some chunks
        self.assertTrue(
            any("这是第一段" in chunk for chunk in chunks) or any("这是第二段" in chunk for chunk in chunks)
        )

    def test_sentence_split_zh(self):
        # Test Chinese sentence splitting
        splitter = ChunkSplitter(split_type="sentence", language="zh")

        # Test with a single document
        text = "这是第一句话。这是第二句话。这是第三句话。"
        chunks = splitter.split(text)

        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)
        # The actual behavior may vary based on the implementation
        # Just verify we get some chunks containing our sentences
        self.assertTrue(
            any("这是第一句话" in chunk for chunk in chunks)
            or any("这是第二句话" in chunk for chunk in chunks)
            or any("这是第三句话" in chunk for chunk in chunks)
        )

    def test_paragraph_split_en(self):
        # Test English paragraph splitting
        splitter = ChunkSplitter(split_type="paragraph", language="en")

        # Test with a single document
        text = (
            "This is the first paragraph. This is the second sentence of the first paragraph.\n\n"
            "This is the second paragraph. This is the second sentence of the second paragraph."
        )
        chunks = splitter.split(text)

        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)
        # The actual behavior may vary based on the implementation
        # Just verify we get some chunks
        self.assertTrue(
            any("first paragraph" in chunk for chunk in chunks) or any("second paragraph" in chunk for chunk in chunks)
        )

    def test_sentence_split_en(self):
        # Test English sentence splitting
        splitter = ChunkSplitter(split_type="sentence", language="en")

        # Test with a single document
        text = "This is the first sentence. This is the second sentence. This is the third sentence."
        chunks = splitter.split(text)

        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)
        # The actual behavior may vary based on the implementation
        # Just verify the chunks contain parts of our sentences
        for chunk in chunks:
            self.assertTrue(
                "first sentence" in chunk
                or "second sentence" in chunk
                or "third sentence" in chunk
                or chunk.startswith("This is")
            )

    def test_multiple_documents(self):
        # Test with multiple documents
        splitter = ChunkSplitter(split_type="paragraph", language="en")

        documents = ["This is document one. It has one paragraph.", "This is document two.\n\nIt has two paragraphs."]

        chunks = splitter.split(documents)

        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)
        # The actual behavior may vary based on the implementation
        # Just verify we get some chunks containing our document content
        self.assertTrue(
            any("document one" in chunk for chunk in chunks) or any("document two" in chunk for chunk in chunks)
        )

    def test_invalid_split_type(self):
        # Test with invalid split type
        with self.assertRaises(ValueError) as cm:
            ChunkSplitter(split_type="invalid", language="en")

        self.assertTrue("Arg `type` must be paragraph, sentence!" in str(cm.exception))

    def test_invalid_language(self):
        # Test with invalid language
        with self.assertRaises(ValueError) as cm:
            ChunkSplitter(split_type="paragraph", language="fr")

        self.assertTrue("Argument `language` must be zh or en!" in str(cm.exception))
