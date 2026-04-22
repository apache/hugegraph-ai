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
    """
    Auth endpoints require special path handling because they differ by version:
    - HugeGraph 1.x: Server-level at /auth/...
    - HugeGraph 1.7.0+ with graphspace: graphspace-scoped at graphspaces/{graphspace}/auth/...

    This class implements the dual-path strategy used by the Java Client to handle both cases.
    """
    def _get_auth_path(self, endpoint: str, is_server_level: bool = False) -> str:
        """
        Construct the correct auth endpoint path based on server version and graphspace support.

        Args:
            endpoint: Auth endpoint name (e.g., 'users', 'groups', 'accesses')
            is_server_level: True for server-level endpoints (e.g., GroupAPI), False for graphspace-scoped

        Returns:
            Properly formatted path for the current server version
        """
        if self._sess.cfg.gs_supported and not is_server_level:
            # HugeGraph 1.7.0+ graphspace mode: graphspace-scoped paths
            return f"graphspaces/{self._sess.cfg.graphspace}/auth/{endpoint}"
        else:
            # HugeGraph 1.x or server-level endpoints: absolute paths
            return f"auth/{endpoint}"

    def list_users(self, limit=None):
        path = self._get_auth_path("users")
        params = {"limit": limit} if limit is not None else {}
        return self._invoke_request(path=path, params=params)

    def create_user(self, user_name, user_password, user_phone=None, user_email=None) -> dict | None:
        path = self._get_auth_path("users")
        return self._invoke_request(
            path=path,
            method="POST",
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
        path = self._get_auth_path(f"users/{user_id}")
        return self._invoke_request(path=path, method="DELETE")

    def modify_user(
        self,
        user_id,
        user_name=None,
        user_password=None,
        user_phone=None,
        user_email=None,
    ) -> dict | None:
        path = self._get_auth_path(f"users/{user_id}")
        return self._invoke_request(
            path=path,
            method="PUT",
            data=json.dumps(
                {
                    "user_name": user_name,
                    "user_password": user_password,
                    "user_phone": user_phone,
                    "user_email": user_email,
                }
            ),
        )

    def get_user(self, user_id) -> dict | None:
        path = self._get_auth_path(f"users/{user_id}")
        return self._invoke_request(path=path, method="GET")

    def list_groups(self, limit=None) -> dict | None:
        # GroupAPI is always server-level, never graphspace-scoped
        path = self._get_auth_path("groups", is_server_level=True)
        params = {"limit": limit} if limit is not None else {}
        return self._invoke_request(path=path, params=params)

    def create_group(self, group_name, group_description=None) -> dict | None:
        path = self._get_auth_path("groups", is_server_level=True)
        data = {"group_name": group_name, "group_description": group_description}
        return self._invoke_request(path=path, method="POST", data=json.dumps(data))

    def delete_group(self, group_id) -> dict | None:
        path = self._get_auth_path(f"groups/{group_id}", is_server_level=True)
        return self._invoke_request(path=path, method="DELETE")

    def modify_group(
        self,
        group_id,
        group_name=None,
        group_description=None,
    ) -> dict | None:
        path = self._get_auth_path(f"groups/{group_id}", is_server_level=True)
        data = {"group_name": group_name, "group_description": group_description}
        return self._invoke_request(path=path, method="PUT", data=json.dumps(data))

    def get_group(self, group_id) -> dict | None:
        path = self._get_auth_path(f"groups/{group_id}", is_server_level=True)
        return self._invoke_request(path=path, method="GET")

    def grant_accesses(self, group_id, target_id, access_permission) -> dict | None:
        path = self._get_auth_path("accesses")
        return self._invoke_request(
            path=path,
            method="POST",
            data=json.dumps(
                {
                    "group": group_id,
                    "target": target_id,
                    "access_permission": access_permission,
                }
            ),
        )

    def revoke_accesses(self, access_id) -> dict | None:
        path = self._get_auth_path(f"accesses/{access_id}")
        return self._invoke_request(path=path, method="DELETE")

    def modify_accesses(self, access_id, access_description) -> dict | None:
        path = self._get_auth_path(f"accesses/{access_id}")
        data = {"access_description": access_description}
        return self._invoke_request(path=path, method="PUT", data=json.dumps(data))

    def get_accesses(self, access_id) -> dict | None:
        path = self._get_auth_path(f"accesses/{access_id}")
        return self._invoke_request(path=path, method="GET")

    def list_accesses(self) -> dict | None:
        path = self._get_auth_path("accesses")
        return self._invoke_request(path=path, method="GET")

    def create_target(self, target_name, target_graph, target_url, target_resources) -> dict | None:
        path = self._get_auth_path("targets")
        return self._invoke_request(
            path=path,
            method="POST",
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
        path = self._get_auth_path(f"targets/{target_id}")
        return self._invoke_request(path=path, method="DELETE")

    def update_target(
        self,
        target_id,
        target_name,
        target_graph,
        target_url,
        target_resources,
    ) -> dict | None:
        path = self._get_auth_path(f"targets/{target_id}")
        return self._invoke_request(
            path=path,
            method="PUT",
            data=json.dumps(
                {
                    "target_name": target_name,
                    "target_graph": target_graph,
                    "target_url": target_url,
                    "target_resources": target_resources,
                }
            ),
        )

    def get_target(self, target_id, response=None) -> dict | None:
        path = self._get_auth_path(f"targets/{target_id}")
        return self._invoke_request(path=path, method="GET")

    def list_targets(self) -> dict | None:
        path = self._get_auth_path("targets")
        return self._invoke_request(path=path, method="GET")

    def create_belong(self, user_id, group_id) -> dict | None:
        path = self._get_auth_path("belongs")
        data = {"user": user_id, "group": group_id}
        return self._invoke_request(path=path, method="POST", data=json.dumps(data))

    def delete_belong(self, belong_id) -> None:
        path = self._get_auth_path(f"belongs/{belong_id}")
        return self._invoke_request(path=path, method="DELETE")

    def update_belong(self, belong_id, description) -> dict | None:
        path = self._get_auth_path(f"belongs/{belong_id}")
        data = {"belong_description": description}
        return self._invoke_request(path=path, method="PUT", data=json.dumps(data))

    def get_belong(self, belong_id) -> dict | None:
        path = self._get_auth_path(f"belongs/{belong_id}")
        return self._invoke_request(path=path, method="GET")

    def list_belongs(self) -> dict | None:
        path = self._get_auth_path("belongs")
        return self._invoke_request(path=path, method="GET")
