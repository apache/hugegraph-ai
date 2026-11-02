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

"""Asynchronous server tasks shared by OLAP, Gremlin and rebuild jobs."""

import json
import math
import time
from typing import Any

import requests
from urllib3.util import Timeout

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.utils.exceptions import (
    ResponseParseError,
    TaskCancelledError,
    TaskFailedError,
    TaskTimeoutError,
)


class TaskManager(HugeParamsBase):
    def list_tasks(self, status=None, limit=None, *, ids=None, page=None) -> dict:
        if ids and (status is not None or page is not None):
            raise ValueError("ids cannot be combined with status or page")
        return self.request("task.list", params={"status": status, "limit": limit, "ids": ids, "page": page})

    def get_task(self, task_id, *, with_result: bool = True, **kwargs) -> dict:
        return self.request("task.get", path_params={"id": task_id}, params={"with_result": with_result}, **kwargs)

    def delete_task(self, task_id, *, force: bool = False):
        return self.request("task.delete", path_params={"id": task_id}, params={"force": force})

    def cancel_task(self, task_id) -> dict:
        return self.request("task.update", path_params={"id": task_id}, params={"action": "cancel"})

    def wait(self, task_id, timeout: float = 300, poll_interval: float = 1) -> dict:
        """Wait for success and load the result once. Timeout does not cancel the job."""
        self.validate_wait(timeout, poll_interval)
        deadline = time.monotonic() + timeout

        def load(with_result: bool) -> dict:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TaskTimeoutError(task_id, timeout)
            connect, read = self.session.timeout
            request_timeout = Timeout(total=remaining, connect=min(connect, remaining), read=min(read, remaining))
            try:
                task = self.get_task(
                    task_id, with_result=with_result, timeout=request_timeout, retries=False, allow_redirects=False
                )
            except requests.Timeout as exc:
                if time.monotonic() >= deadline:
                    raise TaskTimeoutError(task_id, timeout) from exc
                raise
            if time.monotonic() >= deadline:
                raise TaskTimeoutError(task_id, timeout)
            return task

        while True:
            task = load(False)
            status = str(task.get("task_status", "")).lower()
            if not status:
                raise ResponseParseError(f"Task {task_id} response has no task_status")
            if status in {"success", "failed", "cancelled"}:
                task = load(True)
                final_status = str(task.get("task_status", "")).lower()
                if final_status == "failed":
                    raise TaskFailedError(task)
                if final_status == "cancelled":
                    raise TaskCancelledError(task)
                if final_status == "success":
                    return task
                # A concurrent restore can move a task back out of a terminal state.
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))

    @staticmethod
    def validate_wait(timeout: float, poll_interval: float) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("poll_interval must be finite and positive")

    @staticmethod
    def result(task: dict) -> Any:
        """Decode a serialized server result once, preserving non-JSON text."""
        value = task.get("task_result")
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
