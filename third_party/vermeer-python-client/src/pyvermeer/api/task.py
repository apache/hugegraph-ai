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

from pyvermeer.api.base import BaseModule
from pyvermeer.structure.task_data import TaskCreateRequest, TaskCreateResponse, TaskResponse, TasksResponse


class TaskModule(BaseModule):
    """Task"""

    def get_tasks(self) -> TasksResponse:
        """Get task list"""
        response = self._send_request("GET", "/tasks")
        return TasksResponse(response)

    def get_task(self, task_id: int) -> TaskResponse:
        """Get single task information"""
        response = self._send_request("GET", f"/task/{task_id}")
        return TaskResponse(response)

    def create_task(self, create_task: TaskCreateRequest) -> TaskCreateResponse:
        """Create new task"""
        response = self._send_request(method="POST", endpoint="/tasks/create", params=create_task.to_dict())
        return TaskCreateResponse(response)
