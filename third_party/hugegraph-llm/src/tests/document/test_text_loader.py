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

import os
import tempfile
import unittest

import pytest

pytestmark = pytest.mark.unit


class TextLoader:
    """Simple text file loader for testing."""

    def __init__(self, file_path):
        self.file_path = file_path

    def load(self):
        """Load and return the contents of the text file."""
        with open(self.file_path, "r", encoding="utf-8") as file:
            content = file.read()
        return content


class TestTextLoader(unittest.TestCase):
    def setUp(self):
        # Create a temporary file for testing
        # pylint: disable=consider-using-with
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_file_path = os.path.join(self.temp_dir.name, "test_file.txt")
        self.test_content = "This is a test file.\nIt has multiple lines.\nThis is for testing the TextLoader."

        # Write test content to the file
        with open(self.temp_file_path, "w", encoding="utf-8") as f:
            f.write(self.test_content)

    def tearDown(self):
        # Clean up the temporary directory
        self.temp_dir.cleanup()

    def test_load_text_file(self):
        """Test loading a text file."""
        loader = TextLoader(self.temp_file_path)
        content = loader.load()

        # Check that the content matches what we wrote
        self.assertEqual(content, self.test_content)

    def test_load_nonexistent_file(self):
        """Test loading a file that doesn't exist."""
        nonexistent_path = os.path.join(self.temp_dir.name, "nonexistent.txt")
        loader = TextLoader(nonexistent_path)

        # Should raise FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            loader.load()

    def test_load_empty_file(self):
        """Test loading an empty file."""
        empty_file_path = os.path.join(self.temp_dir.name, "empty.txt")
        # Create an empty file
        with open(empty_file_path, "w", encoding="utf-8"):
            pass

        loader = TextLoader(empty_file_path)
        content = loader.load()

        # Content should be an empty string
        self.assertEqual(content, "")

    def test_load_unicode_file(self):
        """Test loading a file with Unicode characters."""
        unicode_file_path = os.path.join(self.temp_dir.name, "unicode.txt")
        unicode_content = "这是中文文本。\nこれは日本語です。\nЭто русский текст."

        with open(unicode_file_path, "w", encoding="utf-8") as f:
            f.write(unicode_content)

        loader = TextLoader(unicode_file_path)
        content = loader.load()

        # Content should match the Unicode text
        self.assertEqual(content, unicode_content)
