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

from hugegraph_llm.operators.common_op.check_schema import CheckSchema


class TestCheckSchema(unittest.TestCase):
    def setUp(self):
        pass

    def test_schema_check_with_valid_input(self):
        data = {
            "vertexlabels": [{"name": "person", "properties": ["name", "age", "occupation"]}],
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                }
            ],
        }
        check_schema = CheckSchema(data)
        self.assertEqual(check_schema.run(), {"schema": data})

    def test_schema_check_with_invalid_input(self):
        data = "invalid input"
        check_schema = CheckSchema(data)
        with self.assertRaises(ValueError):
            check_schema.run()

    def test_schema_check_with_missing_vertices(self):
        data = {
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                }
            ]
        }
        check_schema = CheckSchema(data)
        with self.assertRaises(ValueError):
            check_schema.run()

    def test_schema_check_with_missing_edges(self):
        data = {"vertexlabels": [{"name": "person"}]}
        check_schema = CheckSchema(data)
        with self.assertRaises(ValueError):
            check_schema.run()

    def test_schema_check_with_invalid_vertices(self):
        data = {
            "vertexlabels": "invalid vertices",
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                }
            ],
        }
        check_schema = CheckSchema(data)
        with self.assertRaises(ValueError):
            check_schema.run()

    def test_schema_check_with_invalid_edges(self):
        data = {"vertexlabels": [{"name": "person"}], "edgelabels": "invalid edges"}
        check_schema = CheckSchema(data)
        with self.assertRaises(ValueError):
            check_schema.run()
