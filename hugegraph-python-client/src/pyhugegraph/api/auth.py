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
    """Manage HugeGraph authentication and authorization.

    The previous absolute /auth/... paths return 404 on HugeGraph 1.7.0+
    because the server's JAX-RS @Path annotations only mount these endpoints
    under /graphspaces/{graphspace}/auth/.... This change aligns the client
    with the server's actual @Path annotations:
    - users, accesses, belongs, targets -> graphspace-scoped
    - groups -> server-level /auth/groups (matches GroupAPI @Path)
    """

    # User endpoints - graphspace-scoped
    @router.http("GET", "/graphspaces/{graphspace}/auth/users")
    def list_users(self, limit=None):
        params = {"limit": limit} if limit is not None else {}
        return self._invoke_request(params=params)

    @router.http("POST", "/graphspaces/{graphspace}/auth/users")
    def create_user(self, user_name, user_password, user_phone=None, user_email=None) -> dict | None:
        return self._invoke_request(
            data=json.dumps(
                {
                    "user_name": user_name,
                    "user_password": user_password,
                    "user_phone": user_phone,
                    "user_email": user_email,
                }
            )
        )

    @router.http("DELETE", "/graphspaces/{graphspace}/auth/users/{user_id}")
    def delete_user(self, user_id) -> dict | None:
        return self._invoke_request()

    @router.http("PUT", "/graphspaces/{graphspace}/auth/users/{user_id}")
    def modify_user(
        self,
        user_id,
        user_name=None,
        user_password=None,
        user_phone=None,
        user_email=None,
    ) -> dict | None:
        return self._invoke_request(
            data=json.dumps(
                {
                    "user_name": user_name,
                    "user_password": user_password,
                    "user_phone": user_phone,
                    "user_email": user_email,
                }
            )
        )

    @router.http("GET", "/graphspaces/{graphspace}/auth/users/{user_id}")
    def get_user(self, user_id) -> dict | None:
        return self._invoke_request()

    # Group endpoints - server-level (not graphspace-scoped per Java client pattern)
    @router.http("GET", "/auth/groups")
    def list_groups(self, limit=None) -> dict | None:
        params = {"limit": limit} if limit is not None else {}
        return self._invoke_request(params=params)

    @router.http("POST", "/auth/groups")
    def create_group(self, group_name, group_description=None) -> dict | None:
        data = {"group_name": group_name, "group_description": group_description}
        return self._invoke_request(data=json.dumps(data))

    @router.http("DELETE", "/auth/groups/{group_id}")
    def delete_group(self, group_id) -> dict | None:
        return self._invoke_request()

    @router.http("PUT", "/auth/groups/{group_id}")
    def modify_group(
        self,
        group_id,
        group_name=None,
        group_description=None,
    ) -> dict | None:
        data = {"group_name": group_name, "group_description": group_description}
        return self._invoke_request(data=json.dumps(data))

    @router.http("GET", "/auth/groups/{group_id}")
    def get_group(self, group_id) -> dict | None:
        return self._invoke_request()

    # Access endpoints - graphspace-scoped
    @router.http("POST", "/graphspaces/{graphspace}/auth/accesses")
    def grant_accesses(self, group_id, target_id, access_permission) -> dict | None:
        return self._invoke_request(
            data=json.dumps(
                {
                    "group": group_id,
                    "target": target_id,
                    "access_permission": access_permission,
                }
            )
        )

    @router.http("DELETE", "/graphspaces/{graphspace}/auth/accesses/{access_id}")
    def revoke_accesses(self, access_id) -> dict | None:
        return self._invoke_request()

    @router.http("PUT", "/graphspaces/{graphspace}/auth/accesses/{access_id}")
    def modify_accesses(self, access_id, access_description) -> dict | None:
        data = {"access_description": access_description}
        return self._invoke_request(data=json.dumps(data))

    @router.http("GET", "/graphspaces/{graphspace}/auth/accesses/{access_id}")
    def get_accesses(self, access_id) -> dict | None:
        return self._invoke_request()

    @router.http("GET", "/graphspaces/{graphspace}/auth/accesses")
    def list_accesses(self) -> dict | None:
        return self._invoke_request()

    # Target endpoints - graphspace-scoped
    @router.http("POST", "/graphspaces/{graphspace}/auth/targets")
    def create_target(self, target_name, target_graph, target_url, target_resources) -> dict | None:
        return self._invoke_request(
            data=json.dumps(
                {
                    "target_name": target_name,
                    "target_graph": target_graph,
                    "target_url": target_url,
                    "target_resources": target_resources,
                }
            )
        )

    @router.http("DELETE", "/graphspaces/{graphspace}/auth/targets/{target_id}")
    def delete_target(self, target_id) -> None:
        return self._invoke_request()

    @router.http("PUT", "/graphspaces/{graphspace}/auth/targets/{target_id}")
    def update_target(
        self,
        target_id,
        target_name,
        target_graph,
        target_url,
        target_resources,
    ) -> dict | None:
        return self._invoke_request(
            data=json.dumps(
                {
                    "target_name": target_name,
                    "target_graph": target_graph,
                    "target_url": target_url,
                    "target_resources": target_resources,
                }
            )
        )

    @router.http("GET", "/graphspaces/{graphspace}/auth/targets/{target_id}")
    def get_target(self, target_id, response=None) -> dict | None:
        return self._invoke_request()

    @router.http("GET", "/graphspaces/{graphspace}/auth/targets")
    def list_targets(self) -> dict | None:
        return self._invoke_request()

    # Belong endpoints - graphspace-scoped
    @router.http("POST", "/graphspaces/{graphspace}/auth/belongs")
    def create_belong(self, user_id, group_id) -> dict | None:
        data = {"user": user_id, "group": group_id}
        return self._invoke_request(data=json.dumps(data))

    @router.http("DELETE", "/graphspaces/{graphspace}/auth/belongs/{belong_id}")
    def delete_belong(self, belong_id) -> None:
        return self._invoke_request()

    @router.http("PUT", "/graphspaces/{graphspace}/auth/belongs/{belong_id}")
    def update_belong(self, belong_id, description) -> dict | None:
        data = {"belong_description": description}
        return self._invoke_request(data=json.dumps(data))

    @router.http("GET", "/graphspaces/{graphspace}/auth/belongs/{belong_id}")
    def get_belong(self, belong_id) -> dict | None:
        return self._invoke_request()

    @router.http("GET", "/graphspaces/{graphspace}/auth/belongs")
    def list_belongs(self) -> dict | None:
        return self._invoke_request()
