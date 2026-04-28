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


# NOTE: Auth endpoints currently use absolute paths (/auth/...) which rely on a
# temporary PathFilter compatibility layer in HugeGraph 1.7.0. This layer will be
# removed in future versions. When it is removed, these paths should be converted
# to relative paths (auth/...) with proper graphspace-scoped routing for non-group
# endpoints, similar to the Java Client's dual-path strategy.
# See: apache/hugegraph-ai#322 (HugeGraph 1.7.0 auth API migration)
class AuthManager(HugeParamsBase):
    @router.http("GET", "/auth/users")
    def list_users(self, limit=None):
        params = {"limit": limit} if limit is not None else {}
        return self._invoke_request(params=params)

    @router.http("POST", "/auth/users")
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

    @router.http("DELETE", "/auth/users/{user_id}")
    def delete_user(self, user_id) -> dict | None:
        return self._invoke_request()

    @router.http("PUT", "/auth/users/{user_id}")
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

    @router.http("GET", "/auth/users/{user_id}")
    def get_user(self, user_id) -> dict | None:
        return self._invoke_request()

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

    @router.http("POST", "/auth/accesses")
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

    @router.http("DELETE", "/auth/accesses/{access_id}")
    def revoke_accesses(self, access_id) -> dict | None:
        return self._invoke_request()

    @router.http("PUT", "/auth/accesses/{access_id}")
    def modify_accesses(self, access_id, access_description) -> dict | None:
        data = {"access_description": access_description}
        return self._invoke_request(data=json.dumps(data))

    @router.http("GET", "/auth/accesses/{access_id}")
    def get_accesses(self, access_id) -> dict | None:
        return self._invoke_request()

    @router.http("GET", "/auth/accesses")
    def list_accesses(self) -> dict | None:
        return self._invoke_request()

    @router.http("POST", "/auth/targets")
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

    @router.http("DELETE", "/auth/targets/{target_id}")
    def delete_target(self, target_id) -> None:
        return self._invoke_request()

    @router.http("PUT", "/auth/targets/{target_id}")
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

    @router.http("GET", "/auth/targets/{target_id}")
    def get_target(self, target_id, response=None) -> dict | None:
        return self._invoke_request()

    @router.http("GET", "/auth/targets")
    def list_targets(self) -> dict | None:
        return self._invoke_request()

    @router.http("POST", "/auth/belongs")
    def create_belong(self, user_id, group_id) -> dict | None:
        data = {"user": user_id, "group": group_id}
        return self._invoke_request(data=json.dumps(data))

    @router.http("DELETE", "/auth/belongs/{belong_id}")
    def delete_belong(self, belong_id) -> None:
        return self._invoke_request()

    @router.http("PUT", "/auth/belongs/{belong_id}")
    def update_belong(self, belong_id, description) -> dict | None:
        data = {"belong_description": description}
        return self._invoke_request(data=json.dumps(data))

    @router.http("GET", "/auth/belongs/{belong_id}")
    def get_belong(self, belong_id) -> dict | None:
        return self._invoke_request()

    @router.http("GET", "/auth/belongs")
    def list_belongs(self) -> dict | None:
        return self._invoke_request()
