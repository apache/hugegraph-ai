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
from pyhugegraph.utils import huge_router as router


class AuthManager(HugeParamsBase):
    def _get_auth_path(self, endpoint: str) -> str:
        """
        Get the correct auth API path based on HugeGraph version.
        For 1.7.0+: /graphspaces/DEFAULT/auth/{endpoint}
        For 1.5.x and earlier: auth/{endpoint} (relative path)
        """
        # Check server version to determine path format
        version = self._sess.cfg.version
        if version and len(version) >= 2:
            major, minor = version[0], version[1]
            # Version 1.7.0+ uses graphspace-scoped auth paths
            if major > 1 or (major == 1 and minor >= 7):
                return f"/graphspaces/DEFAULT/auth/{endpoint}"
        
        # Default to relative path for versions < 1.7.0
        return f"auth/{endpoint}"

    @router.http("GET", "auth/users")
    def list_users(self, limit=None):
        params = {"limit": limit} if limit is not None else {}
        path = self._get_auth_path("users")
        return self.session.request(path, "GET", params=params)

    @router.http("POST", "auth/users")
    def create_user(self, user_name, user_password, user_phone=None, user_email=None) -> dict | None:
        path = self._get_auth_path("users")
        return self.session.request(
            path,
            "POST",
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
        return self.session.request(path, "DELETE")

    def modify_user(
        self,
        user_id,
        user_name=None,
        user_password=None,
        user_phone=None,
        user_email=None,
    ) -> dict | None:
        path = self._get_auth_path(f"users/{user_id}")
        return self.session.request(
            path,
            "PUT",
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
        return self.session.request(path, "GET")

    def list_groups(self, limit=None) -> dict | None:
        params = {"limit": limit} if limit is not None else {}
        path = self._get_auth_path("groups")
        return self.session.request(path, "GET", params=params)

    def create_group(self, group_name, group_description=None) -> dict | None:
        path = self._get_auth_path("groups")
        data = {"group_name": group_name, "group_description": group_description}
        return self.session.request(path, "POST", data=json.dumps(data))

    def delete_group(self, group_id) -> dict | None:
        path = self._get_auth_path(f"groups/{group_id}")
        return self.session.request(path, "DELETE")

    def modify_group(
        self,
        group_id,
        group_name=None,
        group_description=None,
    ) -> dict | None:
        path = self._get_auth_path(f"groups/{group_id}")
        data = {"group_name": group_name, "group_description": group_description}
        return self.session.request(path, "PUT", data=json.dumps(data))

    def get_group(self, group_id) -> dict | None:
        path = self._get_auth_path(f"groups/{group_id}")
        return self.session.request(path, "GET")

    def grant_accesses(self, group_id, target_id, access_permission) -> dict | None:
        path = self._get_auth_path("accesses")
        return self.session.request(
            path,
            "POST",
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
        return self.session.request(path, "DELETE")

    def modify_accesses(self, access_id, access_description) -> dict | None:
        path = self._get_auth_path(f"accesses/{access_id}")
        data = {"access_description": access_description}
        return self.session.request(path, "PUT", data=json.dumps(data))

    def get_accesses(self, access_id) -> dict | None:
        path = self._get_auth_path(f"accesses/{access_id}")
        return self.session.request(path, "GET")

    def list_accesses(self) -> dict | None:
        path = self._get_auth_path("accesses")
        return self.session.request(path, "GET")

    def create_target(self, target_name, target_graph, target_url, target_resources) -> dict | None:
        path = self._get_auth_path("targets")
        return self.session.request(
            path,
            "POST",
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
        return self.session.request(path, "DELETE")

    def update_target(
        self,
        target_id,
        target_name,
        target_graph,
        target_url,
        target_resources,
    ) -> dict | None:
        path = self._get_auth_path(f"targets/{target_id}")
        return self.session.request(
            path,
            "PUT",
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
        return self.session.request(path, "GET")

    def list_targets(self) -> dict | None:
        path = self._get_auth_path("targets")
        return self.session.request(path, "GET")

    def create_belong(self, user_id, group_id) -> dict | None:
        path = self._get_auth_path("belongs")
        data = {"user": user_id, "group": group_id}
        return self.session.request(path, "POST", data=json.dumps(data))

    def delete_belong(self, belong_id) -> None:
        path = self._get_auth_path(f"belongs/{belong_id}")
        return self.session.request(path, "DELETE")

    def update_belong(self, belong_id, description) -> dict | None:
        path = self._get_auth_path(f"belongs/{belong_id}")
        data = {"belong_description": description}
        return self.session.request(path, "PUT", data=json.dumps(data))

    def get_belong(self, belong_id) -> dict | None:
        path = self._get_auth_path(f"belongs/{belong_id}")
        return self.session.request(path, "GET")

    def list_belongs(self) -> dict | None:
        path = self._get_auth_path("belongs")
        return self.session.request(path, "GET")
