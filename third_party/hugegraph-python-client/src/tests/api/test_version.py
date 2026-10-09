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

from ..client_utils import ClientUtils

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]


class TestVersion(unittest.TestCase):
    client = None
    version = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.version = cls.client.version

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        self.client.clear_graph_all_data()

    def tearDown(self):
        pass

    def test_version(self):
        version = self.version.version()
        self.assertIsInstance(version, dict)
        self.assertIn("version", version["versions"])
        self.assertIn("core", version["versions"])
        self.assertIn("gremlin", version["versions"])
        self.assertIn("api", version["versions"])
