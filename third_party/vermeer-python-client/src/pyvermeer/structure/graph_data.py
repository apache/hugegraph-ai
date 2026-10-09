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


class BackendOpt:
    """BackendOpt class"""

    def __init__(self, dic: dict):
        """init"""
        self.__vertex_data_backend = dic.get("vertex_data_backend")

    @property
    def vertex_data_backend(self):
        """vertex data backend"""
        return self.__vertex_data_backend

    def to_dict(self):
        """to dict"""
        return {"vertex_data_backend": self.vertex_data_backend}


class GraphWorker:
    """GraphWorker"""

    def __init__(self, dic: dict):
        """init"""
        self.__name = dic.get("Name", "")
        self.__vertex_count = dic.get("VertexCount", -1)
        self.__vert_id_start = dic.get("VertIdStart", -1)
        self.__edge_count = dic.get("EdgeCount", -1)
        self.__is_self = dic.get("IsSelf", False)
        self.__scatter_offset = dic.get("ScatterOffset", -1)

    @property
    def name(self) -> str:
        """graph worker name"""
        return self.__name

    @property
    def vertex_count(self) -> int:
        """vertex count"""
        return self.__vertex_count

    @property
    def vert_id_start(self) -> int:
        """vertex id start"""
        return self.__vert_id_start

    @property
    def edge_count(self) -> int:
        """edge count"""
        return self.__edge_count

    @property
    def is_self(self) -> bool:
        """is self worker. Nonsense"""
        return self.__is_self

    @property
    def scatter_offset(self) -> int:
        """scatter offset"""
        return self.__scatter_offset

    def to_dict(self):
        """to dict"""
        return {
            "name": self.name,
            "vertex_count": self.vertex_count,
            "vert_id_start": self.vert_id_start,
            "edge_count": self.edge_count,
            "is_self": self.is_self,
            "scatter_offset": self.scatter_offset,
        }


class VermeerGraph:
    """VermeerGraph"""

    def __init__(self, dic: dict):
        """init"""
        self.__name = dic.get("name", "")
        self.__space_name = dic.get("space_name", "")
        self.__status = dic.get("status", "")
        self.__create_time = parse_vermeer_time(dic.get("create_time", ""))
        self.__update_time = parse_vermeer_time(dic.get("update_time", ""))
        self.__vertex_count = dic.get("vertex_count", 0)
        self.__edge_count = dic.get("edge_count", 0)
        self.__workers = [GraphWorker(w) for w in dic.get("workers", [])]
        self.__worker_group = dic.get("worker_group", "")
        self.__use_out_edges = dic.get("use_out_edges", False)
        self.__use_property = dic.get("use_property", False)
        self.__use_out_degree = dic.get("use_out_degree", False)
        self.__use_undirected = dic.get("use_undirected", False)
        self.__on_disk = dic.get("on_disk", False)
        self.__backend_option = BackendOpt(dic.get("backend_option", {}))

    @property
    def name(self) -> str:
        """graph name"""
        return self.__name

    @property
    def space_name(self) -> str:
        """space name"""
        return self.__space_name

    @property
    def status(self) -> str:
        """graph status"""
        return self.__status

    @property
    def create_time(self) -> datetime:
        """create time"""
        return self.__create_time

    @property
    def update_time(self) -> datetime:
        """update time"""
        return self.__update_time

    @property
    def vertex_count(self) -> int:
        """vertex count"""
        return self.__vertex_count

    @property
    def edge_count(self) -> int:
        """edge count"""
        return self.__edge_count

    @property
    def workers(self) -> list[GraphWorker]:
        """graph workers"""
        return self.__workers

    @property
    def worker_group(self) -> str:
        """worker group"""
        return self.__worker_group

    @property
    def use_out_edges(self) -> bool:
        """whether graph has out edges"""
        return self.__use_out_edges

    @property
    def use_property(self) -> bool:
        """whether graph has property"""
        return self.__use_property

    @property
    def use_out_degree(self) -> bool:
        """whether graph has out degree"""
        return self.__use_out_degree

    @property
    def use_undirected(self) -> bool:
        """whether graph is undirected"""
        return self.__use_undirected

    @property
    def on_disk(self) -> bool:
        """whether graph is on disk"""
        return self.__on_disk

    @property
    def backend_option(self) -> BackendOpt:
        """backend option"""
        return self.__backend_option

    def to_dict(self) -> dict:
        """to dict"""
        return {
            "name": self.__name,
            "space_name": self.__space_name,
            "status": self.__status,
            "create_time": self.__create_time.strftime("%Y-%m-%d %H:%M:%S") if self.__create_time else "",
            "update_time": self.__update_time.strftime("%Y-%m-%d %H:%M:%S") if self.__update_time else "",
            "vertex_count": self.__vertex_count,
            "edge_count": self.__edge_count,
            "workers": [w.to_dict() for w in self.__workers],
            "worker_group": self.__worker_group,
            "use_out_edges": self.__use_out_edges,
            "use_property": self.__use_property,
            "use_out_degree": self.__use_out_degree,
            "use_undirected": self.__use_undirected,
            "on_disk": self.__on_disk,
            "backend_option": self.__backend_option.to_dict(),
        }


class GraphsResponse(BaseResponse):
    """GraphsResponse"""

    def __init__(self, dic: dict):
        """init"""
        super().__init__(dic)
        self.__graphs = [VermeerGraph(g) for g in dic.get("graphs", [])]

    @property
    def graphs(self) -> list[VermeerGraph]:
        """graphs"""
        return self.__graphs

    def to_dict(self) -> dict:
        """to dict"""
        return {"errcode": self.errcode, "message": self.message, "graphs": [g.to_dict() for g in self.graphs]}


class GraphResponse(BaseResponse):
    """GraphResponse"""

    def __init__(self, dic: dict):
        """init"""
        super().__init__(dic)
        self.__graph = VermeerGraph(dic.get("graph", {}))

    @property
    def graph(self) -> VermeerGraph:
        """graph"""
        return self.__graph

    def to_dict(self) -> dict:
        """to dict"""
        return {"errcode": self.errcode, "message": self.message, "graph": self.graph.to_dict()}
