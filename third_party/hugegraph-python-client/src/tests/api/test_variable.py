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
from pyhugegraph.utils.exceptions import NotFoundError

from ..client_utils import ClientUtils

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]


class TestVariable(unittest.TestCase):
    client = None
    variable = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.variable = cls.client.variable

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        self.client.clear_graph_all_data()

    def tearDown(self):
        pass

    def test_all(self):
        self.assertEqual(len(self.variable.all()), 0)
        self.variable.set("student", "mary")
        self.variable.set("price", 20.86)

        dic = self.variable.all()
        self.assertEqual(2, len(dic))
        self.assertEqual("mary", dic.get("student", None))
        self.assertEqual(20.86, dic.get("price", None))

    def test_remove(self):
        self.variable.set("lang", "java")
        dic = self.variable.all()
        self.assertEqual(1, len(dic))
        self.assertEqual("java", dic.get("lang", None))

        self.variable.remove("lang")
        dic = self.variable.all()
        self.assertEqual(0, len(dic))
        self.assertEqual(dic.get("lang", None), None)

    def test_set_and_get(self):
        self.variable.set("name", "tom")
        self.variable.set("age", 18)

        self.assertEqual(2, len(self.variable.all()))
        name = self.variable.get("name").get("name", None)
        self.assertEqual("tom", name)
        age = self.variable.get("age").get("age", None)
        self.assertEqual(18, age)

    def test_get_key_not_exist(self):
        with pytest.raises(NotFoundError):
            self.assertIsNone(self.variable.get("id").get("id"))

    def test_remove_key_not_exist(self):
        self.variable.remove("id")
