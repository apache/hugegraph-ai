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

from hugegraph_llm.document import Document, Metadata

pytestmark = pytest.mark.unit


class TestDocument(unittest.TestCase):
    def test_document_initialization(self):
        """Test document initialization with content and metadata."""
        content = "This is a test document."
        metadata = {"source": "test", "author": "tester"}
        doc = Document(content=content, metadata=metadata)

        self.assertEqual(doc.content, content)
        self.assertEqual(doc.metadata["source"], "test")
        self.assertEqual(doc.metadata["author"], "tester")

    def test_document_default_metadata(self):
        """Test document initialization with default empty metadata."""
        content = "This is a test document."
        doc = Document(content=content)

        self.assertEqual(doc.content, content)
        self.assertEqual(doc.metadata, {})

    def test_metadata_class(self):
        """Test Metadata class functionality."""
        metadata = Metadata(source="test_source", author="test_author", page=5)
        metadata_dict = metadata.as_dict()

        self.assertEqual(metadata_dict["source"], "test_source")
        self.assertEqual(metadata_dict["author"], "test_author")
        self.assertEqual(metadata_dict["page"], 5)

    def test_metadata_as_dict(self):
        """Test converting Metadata to dictionary."""
        metadata = Metadata(source="test_source", author="test_author", page=5)
        metadata_dict = metadata.as_dict()

        self.assertEqual(metadata_dict["source"], "test_source")
        self.assertEqual(metadata_dict["author"], "test_author")
        self.assertEqual(metadata_dict["page"], 5)

    def test_document_with_metadata_object(self):
        """Test document initialization with Metadata object."""
        content = "This is a test document."
        metadata = Metadata(source="test_source", author="test_author", page=5)
        doc = Document(content=content, metadata=metadata)

        self.assertEqual(doc.content, content)
        self.assertEqual(doc.metadata["source"], "test_source")
        self.assertEqual(doc.metadata["author"], "test_author")
        self.assertEqual(doc.metadata["page"], 5)
