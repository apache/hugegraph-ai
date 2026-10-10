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

import datetime

from pyvermeer.structure.base_data import BaseResponse
from pyvermeer.utils.vermeer_datetime import parse_vermeer_time


class TaskWorker:
    """task worker info"""

    def __init__(self, dic):
        """init"""
        self.__name = dic.get("name", None)
        self.__status = dic.get("status", None)

    @property
    def name(self) -> str:
        """worker name"""
        return self.__name

    @property
    def status(self) -> str:
        """worker status"""
        return self.__status

    def to_dict(self):
        """to dict"""
        return {"name": self.name, "status": self.status}


class TaskInfo:
    """task info"""

    def __init__(self, dic):
        """init"""
        self.__id = dic.get("id", 0)
        self.__status = dic.get("status", "")
        self.__state = dic.get("state", "")
        self.__create_user = dic.get("create_user", "")
        self.__create_type = dic.get("create_type", "")
        self.__create_time = parse_vermeer_time(dic.get("create_time", ""))
        self.__start_time = parse_vermeer_time(dic.get("start_time", ""))
        self.__update_time = parse_vermeer_time(dic.get("update_time", ""))
        self.__graph_name = dic.get("graph_name", "")
        self.__space_name = dic.get("space_name", "")
        self.__type = dic.get("type", "")
        self.__params = dic.get("params", {})
        self.__workers = [TaskWorker(w) for w in dic.get("workers", [])]
        self.__error_message = dic.get("error_message", "")

    @property
    def id(self) -> int:
        """task id"""
        return self.__id

    @property
    def state(self) -> str:
        """task state"""
        return self.__state

    @property
    def create_user(self) -> str:
        """task creator"""
        return self.__create_user

    @property
    def create_type(self) -> str:
        """task create type"""
        return self.__create_type

    @property
    def create_time(self) -> datetime:
        """task create time"""
        return self.__create_time

    @property
    def start_time(self) -> datetime:
        """task start time"""
        return self.__start_time

    @property
    def update_time(self) -> datetime:
        """task update time"""
        return self.__update_time

    @property
    def graph_name(self) -> str:
        """task graph"""
        return self.__graph_name

    @property
    def space_name(self) -> str:
        """task space"""
        return self.__space_name

    @property
    def type(self) -> str:
        """task type"""
        return self.__type

    @property
    def params(self) -> dict:
        """task params"""
        return self.__params

    @property
    def workers(self) -> list[TaskWorker]:
        """task workers"""
        return self.__workers

    @property
    def error_message(self) -> str:
        """task error message"""
        return self.__error_message

    def to_dict(self) -> dict:
        """to dict"""
        return {
            "id": self.__id,
            "status": self.__status,
            "state": self.__state,
            "create_user": self.__create_user,
            "create_type": self.__create_type,
            "create_time": self.__create_time.strftime("%Y-%m-%d %H:%M:%S") if self.__start_time else "",
            "start_time": self.__start_time.strftime("%Y-%m-%d %H:%M:%S") if self.__start_time else "",
            "update_time": self.__update_time.strftime("%Y-%m-%d %H:%M:%S") if self.__update_time else "",
            "graph_name": self.__graph_name,
            "space_name": self.__space_name,
            "type": self.__type,
            "params": self.__params,
            "workers": [w.to_dict() for w in self.__workers],
            "error_message": self.__error_message,
        }


class TaskCreateRequest:
    """task create request"""

    def __init__(self, task_type, graph_name, params):
        """init"""
        self.task_type = task_type
        self.graph_name = graph_name
        self.params = params

    def to_dict(self) -> dict:
        """to dict"""
        return {"task_type": self.task_type, "graph": self.graph_name, "params": self.params}


class TaskCreateResponse(BaseResponse):
    """task create response"""

    def __init__(self, dic):
        """init"""
        super().__init__(dic)
        self.__task = TaskInfo(dic.get("task", {}))

    @property
    def task(self) -> TaskInfo:
        """task info"""
        return self.__task

    def to_dict(self) -> dict:
        """to dict"""
        return {
            "errcode": self.errcode,
            "message": self.message,
            "task": self.task.to_dict(),
        }


class TasksResponse(BaseResponse):
    """tasks response"""

    def __init__(self, dic):
        """init"""
        super().__init__(dic)
        self.__tasks = [TaskInfo(t) for t in dic.get("tasks", [])]

    @property
    def tasks(self) -> list[TaskInfo]:
        """task infos"""
        return self.__tasks

    def to_dict(self) -> dict:
        """to dict"""
        return {"errcode": self.errcode, "message": self.message, "tasks": [t.to_dict() for t in self.tasks]}


class TaskResponse(BaseResponse):
    """task response"""

    def __init__(self, dic):
        """init"""
        super().__init__(dic)
        self.__task = TaskInfo(dic.get("task", {}))

    @property
    def task(self) -> TaskInfo:
        """task info"""
        return self.__task

    def to_dict(self) -> dict:
        """to dict"""
        return {
            "errcode": self.errcode,
            "message": self.message,
            "task": self.task.to_dict(),
        }
