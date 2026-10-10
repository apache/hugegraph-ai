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


class Worker:
    """worker data"""

    def __init__(self, dic):
        """init"""
        self.__id = dic.get("id", 0)
        self.__name = dic.get("name", "")
        self.__grpc_addr = dic.get("grpc_addr", "")
        self.__ip_addr = dic.get("ip_addr", "")
        self.__state = dic.get("state", "")
        self.__version = dic.get("version", "")
        self.__group = dic.get("group", "")
        self.__init_time = parse_vermeer_time(dic.get("init_time", ""))
        self.__launch_time = parse_vermeer_time(dic.get("launch_time", ""))

    @property
    def id(self) -> int:
        """worker id"""
        return self.__id

    @property
    def name(self) -> str:
        """worker name"""
        return self.__name

    @property
    def grpc_addr(self) -> str:
        """gRPC address"""
        return self.__grpc_addr

    @property
    def ip_addr(self) -> str:
        """IP address"""
        return self.__ip_addr

    @property
    def state(self) -> int:
        """worker status"""
        return self.__state

    @property
    def version(self) -> str:
        """worker version"""
        return self.__version

    @property
    def group(self) -> str:
        """worker group"""
        return self.__group

    @property
    def init_time(self) -> datetime:
        """worker initialization time"""
        return self.__init_time

    @property
    def launch_time(self) -> datetime:
        """worker launch time"""
        return self.__launch_time

    def to_dict(self):
        """convert object to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "grpc_addr": self.grpc_addr,
            "ip_addr": self.ip_addr,
            "state": self.state,
            "version": self.version,
            "group": self.group,
            "init_time": self.init_time,
            "launch_time": self.launch_time,
        }


class WorkersResponse(BaseResponse):
    """response of workers"""

    def __init__(self, dic):
        """init"""
        super().__init__(dic)
        self.__workers = [Worker(worker) for worker in dic["workers"]]

    @property
    def workers(self) -> list[Worker]:
        """list of workers"""
        return self.__workers

    def to_dict(self):
        """convert object to dictionary"""
        return {
            "errcode": self.errcode,
            "message": self.message,
            "workers": [worker.to_dict() for worker in self.workers],
        }
