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

import io
import sys
import unittest
from unittest.mock import patch

from hugegraph_llm.operators.common_op.print_result import PrintResult


class TestPrintResult(unittest.TestCase):
    def setUp(self):
        self.printer = PrintResult()

    def test_init(self):
        """Test initialization of PrintResult class."""
        self.assertIsNone(self.printer.result)

    def test_run_with_string(self):
        """Test run method with string input."""
        # Redirect stdout to capture print output
        captured_output = io.StringIO()
        sys.stdout = captured_output

        test_string = "Test string output"
        result = self.printer.run(test_string)

        # Reset redirect
        sys.stdout = sys.__stdout__

        # Verify that the input was printed
        self.assertEqual(captured_output.getvalue().strip(), test_string)
        # Verify that the method returns the input
        self.assertEqual(result, test_string)
        # Verify that the result attribute was updated
        self.assertEqual(self.printer.result, test_string)

    def test_run_with_dict(self):
        """Test run method with dictionary input."""
        # Redirect stdout to capture print output
        captured_output = io.StringIO()
        sys.stdout = captured_output

        test_dict = {"key1": "value1", "key2": "value2"}
        result = self.printer.run(test_dict)

        # Reset redirect
        sys.stdout = sys.__stdout__

        # Verify that the input was printed
        self.assertEqual(captured_output.getvalue().strip(), str(test_dict))
        # Verify that the method returns the input
        self.assertEqual(result, test_dict)
        # Verify that the result attribute was updated
        self.assertEqual(self.printer.result, test_dict)

    def test_run_with_list(self):
        """Test run method with list input."""
        # Redirect stdout to capture print output
        captured_output = io.StringIO()
        sys.stdout = captured_output

        test_list = ["item1", "item2", "item3"]
        result = self.printer.run(test_list)

        # Reset redirect
        sys.stdout = sys.__stdout__

        # Verify that the input was printed
        self.assertEqual(captured_output.getvalue().strip(), str(test_list))
        # Verify that the method returns the input
        self.assertEqual(result, test_list)
        # Verify that the result attribute was updated
        self.assertEqual(self.printer.result, test_list)

    def test_run_with_none(self):
        """Test run method with None input."""
        # Redirect stdout to capture print output
        captured_output = io.StringIO()
        sys.stdout = captured_output

        result = self.printer.run(None)

        # Reset redirect
        sys.stdout = sys.__stdout__

        # Verify that the input was printed
        self.assertEqual(captured_output.getvalue().strip(), "None")
        # Verify that the method returns the input
        self.assertIsNone(result)
        # Verify that the result attribute was updated
        self.assertIsNone(self.printer.result)

    @patch("builtins.print")
    def test_run_with_mock(self, mock_print):
        """Test run method using mock for print function."""
        test_data = "Test with mock"
        result = self.printer.run(test_data)

        # Verify that print was called with the correct argument
        mock_print.assert_called_once_with(test_data)
        # Verify that the method returns the input
        self.assertEqual(result, test_data)
        # Verify that the result attribute was updated
        self.assertEqual(self.printer.result, test_data)


if __name__ == "__main__":
    unittest.main()
