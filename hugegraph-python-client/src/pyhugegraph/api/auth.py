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


import json

from pyhugegraph.api.common import HugeParamsBase


class AuthManager(HugeParamsBase):
    """Manage HugeGraph authentication and authorization.

    The previous absolute /auth/... paths return 404 on HugeGraph 1.7.0+
    because the server's JAX-RS @Path annotations only mount these endpoints
    under /graphspaces/{graphspace}/auth/.... This change aligns the client
    with the server's actual @Path annotations:
    - users, accesses, belongs, targets -> graphspace-scoped
    - groups -> server-level /auth/groups (matches GroupAPI @Path)
    """

    # User endpoints - graphspace-scoped
    def list_users(self, limit=None, *, name=None):
        params = {"limit": limit, "name": name} if limit is not None else {}
        return self.request("user.list", params=params)

    def create_user(self, user_name, user_password, user_phone=None, user_email=None) -> dict | None:
        return self.request(
            "user.create",
            data=json.dumps(
                {
                    "user_name": user_name,
                    "user_password": user_password,
                    "user_phone": user_phone,
                    "user_email": user_email,
                }
            ),
        )

    def delete_user(self, user_id) -> dict | None:
        return self.request("user.delete", path_params={"id": user_id})

    def modify_user(self, user_id, user_name=None, user_password=None, user_phone=None, user_email=None) -> dict | None:
        return self.request(
            "user.update",
            data=json.dumps(
                {
                    "user_name": user_name,
                    "user_password": user_password,
                    "user_phone": user_phone,
                    "user_email": user_email,
                }
            ),
            path_params={"id": user_id},
        )

    def get_user(self, user_id) -> dict | None:
        return self.request("user.get", path_params={"id": user_id})

    # Group endpoints - server-level (not graphspace-scoped per Java client pattern)
    def list_groups(self, limit=None) -> dict | None:
        params = {"limit": limit} if limit is not None else {}
        return self.request("group.list", params=params)

    def create_group(self, group_name, group_description=None) -> dict | None:
        data = {"group_name": group_name, "group_description": group_description}
        return self.request("group.create", data=json.dumps(data))

    def delete_group(self, group_id) -> dict | None:
        return self.request("group.delete", path_params={"id": group_id})

    def modify_group(self, group_id, group_name=None, group_description=None) -> dict | None:
        data = {"group_name": group_name, "group_description": group_description}
        return self.request("group.update", data=json.dumps(data), path_params={"id": group_id})

    def get_group(self, group_id) -> dict | None:
        return self.request("group.get", path_params={"id": group_id})

    # Access endpoints - graphspace-scoped
    def grant_accesses(self, group_id, target_id, access_permission) -> dict | None:
        return self.request(
            "access.create",
            data=json.dumps({"group": group_id, "target": target_id, "access_permission": access_permission}),
        )

    def revoke_accesses(self, access_id) -> dict | None:
        return self.request("access.delete", path_params={"id": access_id})

    def modify_accesses(self, access_id, access_description) -> dict | None:
        data = {"access_description": access_description}
        return self.request("access.update", data=json.dumps(data), path_params={"id": access_id})

    def get_accesses(self, access_id) -> dict | None:
        return self.request("access.get", path_params={"id": access_id})

    def list_accesses(self, *, group=None, target=None, limit=None) -> dict | None:
        return self.request("access.list", params={"group": group, "target": target, "limit": limit})

    # Target endpoints - graphspace-scoped
    def create_target(self, target_name, target_graph, target_url, target_resources) -> dict | None:
        return self.request(
            "target.create",
            data=json.dumps(
                {
                    "target_name": target_name,
                    "target_graph": target_graph,
                    "target_url": target_url,
                    "target_resources": target_resources,
                }
            ),
        )

    def delete_target(self, target_id) -> None:
        return self.request("target.delete", path_params={"id": target_id})

    def update_target(self, target_id, target_name, target_graph, target_url, target_resources) -> dict | None:
        return self.request(
            "target.update",
            data=json.dumps(
                {
                    "target_name": target_name,
                    "target_graph": target_graph,
                    "target_url": target_url,
                    "target_resources": target_resources,
                }
            ),
            path_params={"id": target_id},
        )

    def get_target(self, target_id, response=None) -> dict | None:
        return self.request("target.get", path_params={"id": target_id})

    def list_targets(self, *, limit=None) -> dict | None:
        return self.request("target.list", params={"limit": limit})

    # Belong endpoints - graphspace-scoped
    def create_belong(self, user_id, group_id) -> dict | None:
        data = {"user": user_id, "group": group_id}
        return self.request("belong.create", data=json.dumps(data))

    def delete_belong(self, belong_id) -> None:
        return self.request("belong.delete", path_params={"id": belong_id})

    def update_belong(self, belong_id, description) -> dict | None:
        data = {"belong_description": description}
        return self.request("belong.update", data=json.dumps(data), path_params={"id": belong_id})

    def get_belong(self, belong_id) -> dict | None:
        return self.request("belong.get", path_params={"id": belong_id})

    def list_belongs(self, *, user=None, group=None, limit=None) -> dict | None:
        return self.request("belong.list", params={"user": user, "group": group, "limit": limit})

    def login(self, user_name: str, password: str, *, token_expire=None) -> dict:
        body = {"user_name": user_name, "user_password": password}
        if token_expire is not None:
            body["token_expire"] = token_expire
        return self.request("login.login", body=body)

    def verify_token(self, token: str) -> dict:
        return self.request("login.verify_token", headers={"Authorization": f"Bearer {token}"})

    def logout(self, token: str):
        return self.request("login.logout", headers={"Authorization": f"Bearer {token}"})

    def get_user_role(self, user_id):
        return self.request("user.role", path_params={"id": user_id})
