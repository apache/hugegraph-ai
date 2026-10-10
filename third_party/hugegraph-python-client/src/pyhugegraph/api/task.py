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

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.utils import huge_router as router


class TaskManager(HugeParamsBase):
    @router.http("GET", "tasks")
    def list_tasks(self, status=None, limit=None):
        params = {}
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = limit
        return self._invoke_request(params=params)

    @router.http("GET", "tasks/{task_id}")
    def get_task(self, task_id):  # pylint: disable=unused-argument
        return self._invoke_request()

    @router.http("DELETE", "tasks/{task_id}")
    def delete_task(self, task_id):  # pylint: disable=unused-argument
        return self._invoke_request()

    @router.http("PUT", "tasks/{task_id}?action=cancel")
    def cancel_task(self, task_id):  # pylint: disable=unused-argument
        return self._invoke_request()
