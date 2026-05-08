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

from pyhugegraph.utils.exceptions import NotFoundError

from ..client_utils import ClientUtils


class TestAuthManager(unittest.TestCase):
    client = None
    auth = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.auth = cls.client.auth

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        users = self.auth.list_users()
        for user in users["users"]:
            if user["user_creator"] != "system":
                self.auth.delete_user(user["id"])

        groups = self.auth.list_groups()
        for group in groups["groups"]:
            self.auth.delete_group(group["id"])

        belongs = self.auth.list_belongs()
        for belong in belongs["belongs"]:
            self.auth.delete_belong(belong["id"])

        targets = self.auth.list_targets()
        for target in targets["targets"]:
            self.auth.delete_target(target["id"])

        accesses = self.auth.list_accesses()
        for access in accesses["accesses"]:
            self.auth.revoke_accesses(access["id"])

    def tearDown(self):
        pass

    def test_user_operations(self):
        users = self.auth.list_users()
        self.assertTrue(users["users"][0]["user_creator"] == "system")

        # {'user_password': '',
        # 'user_update': '2024-01-26 02:45:57.317', 'user_name': 'test_user',
        # 'user_creator': 'admin', 'id': '-30:test_user', 'user_create': '2024-01-26 02:45:57.317'}
        user = self.auth.create_user("test_user", "password")
        self.assertEqual(user["user_name"], "test_user")

        user = self.auth.get_user(user["id"])
        self.assertEqual(user["user_name"], "test_user")

        # Modify the user
        user = self.auth.modify_user(user["id"], user_email="hugegraph@apache.org")
        self.assertEqual(user["user_email"], "hugegraph@apache.org")

        # Delete the user
        self.auth.delete_user(user["id"])
        # Verify the user was deleted
        try:
            user = self.auth.get_user(user["id"])
        except NotFoundError as e:
            self.assertTrue(f"Can\\'t find user with id \\'{user['id']}\\'" in str(e))

    def test_group_operations(self):
        # Create a group
        group = self.auth.create_group("test_group")
        self.assertEqual(group["group_name"], "test_group")

        groups = self.auth.list_groups()
        self.assertEqual(groups["groups"][0]["group_name"], "test_group")

        # Get the group
        group = self.auth.get_group(group["id"])
        self.assertEqual(group["group_name"], "test_group")

        # Modify the group
        group = self.auth.modify_group(group["id"], group_description="test_description")
        self.assertEqual(group["group_description"], "test_description")

        # Delete the group
        self.auth.delete_group(group["id"])
        # Verify the group was deleted
        try:
            group = self.auth.get_group(group["id"])
        except NotFoundError as e:
            self.assertTrue(f"Can\\'t find group with id \\'{group['id']}\\'" in str(e))

    def test_target_operations(self):
        # Create a target
        target = self.auth.create_target(
            "test_target",
            "graph1",
            "127.0.0.1:8080",
            [{"type": "VERTEX", "label": "person", "properties": {"city": "Beijing"}}],
        )
        # Verify the target was created
        self.assertEqual(target["target_name"], "test_target")

        # Get the target
        target = self.auth.get_target(target["id"])
        self.assertEqual(target["target_name"], "test_target")

        # Modify the target
        target = self.auth.update_target(
            target["id"],
            "test_target",
            "graph1",
            "127.0.0.1:8080",
            [{"type": "VERTEX", "label": "person", "properties": {"city": "Shanghai"}}],
        )
        # Verify the target was modified
        # HugeGraph 1.7.0+ returns target_resources as a keyed map such as
        # {"VERTEX#person": [{...}]}; older payloads used a list shape.
        target_resources = target["target_resources"]
        self.assertEqual(target_resources["VERTEX#person"][0]["properties"]["city"], "Shanghai")

        # Delete the target
        self.auth.delete_target(target["id"])
        # Verify the target was deleted
        with self.assertRaises(NotFoundError):
            self.auth.get_target(target["id"])

    def test_belong_operations(self):
        user = self.auth.create_user("all", "password")
        group = self.auth.create_group("all")

        # Create a belong
        # {'belong_create': '2024-01-29 02:04:41.161', 'belong_creator': 'admin',
        # 'belong_update': '2024-01-29 02:04:41.161', 'id': 'S-30:all>-49>>S-36:all',
        # 'user': '-30:all', 'group': '-36:all'}
        belong = self.auth.create_belong(user["id"], group["id"])
        # Verify the belong was created
        self.assertEqual(belong["user"], user["id"])
        self.assertEqual(belong["group"], group["id"])

        belongs = self.auth.list_belongs()
        self.assertEqual(belongs["belongs"][0]["user"], user["id"])

        # Get the belong
        belong = self.auth.get_belong(belong["id"])
        self.assertEqual(belong["user"], user["id"])
        self.assertEqual(belong["group"], group["id"])

        # Modify the belong
        belong = self.auth.update_belong(belong["id"], "WRITE")
        # Verify the belong was modified
        self.assertEqual(belong["belong_description"], "WRITE")

        # Delete the belong
        self.auth.delete_belong(belong["id"])
        # Verify the belong was deleted
        with self.assertRaises(NotFoundError):
            self.auth.get_belong(belong["id"])

    def test_access_operations(self):
        # Create a permission
        group = self.auth.create_group("test_group")
        target = self.auth.create_target(
            "test_target",
            "graph1",
            "127.0.0.1:8080",
            [{"type": "VERTEX", "label": "person", "properties": {"city": "Beijing"}}],
        )
        access = self.auth.grant_accesses(group["id"], target["id"], "READ")
        # Verify the permission was created
        self.assertEqual(access["group"], group["id"])
        self.assertEqual(access["target"], target["id"])
        self.assertEqual(access["access_permission"], "READ")

        accesses = self.auth.list_accesses()
        self.assertEqual(accesses["accesses"][0]["group"], group["id"])

        # Get the permission
        access = self.auth.get_accesses(access["id"])
        self.assertEqual(access["group"], group["id"])
        self.assertEqual(access["target"], target["id"])
        self.assertEqual(access["access_permission"], "READ")

        # Modify the permission
        access = self.auth.modify_accesses(access["id"], "test_description")
        # Verify the permission was modified
        self.assertEqual(access["access_description"], "test_description")

        # Delete the permission
        self.auth.revoke_accesses(access["id"])
        # Verify the permission was deleted
        with self.assertRaises(NotFoundError):
            self.auth.get_accesses(access["id"])
