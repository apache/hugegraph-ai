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


class TestTaskManager(unittest.TestCase):
    client = None
    task = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.task = cls.client.task

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_list_tasks(self):
        tasks = self.task.list_tasks()
        self.assertIsInstance(tasks, dict)
        self.assertTrue("tasks" in tasks)

    def test_get_task(self):
        try:
            self.task.get_task(1)
        except NotFoundError as e:
            self.assertTrue("Can\\'t find task with id \\'1\\'" in str(e))

    def test_delete_task(self):
        try:
            self.task.delete_task(2)
        except NotFoundError as e:
            self.assertTrue("Can\\'t find task with id \\'2\\'" in str(e))

    def test_cancel_task(self):
        try:
            self.task.cancel_task(3)
        except NotFoundError as e:
            self.assertTrue("Can\\'t find task with id \\'3\\'" in str(e))
