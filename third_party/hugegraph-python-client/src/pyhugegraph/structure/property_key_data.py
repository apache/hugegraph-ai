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

# from dataclasses import dataclass, field


# @dataclass
# class PropertyKeyData:
#     id: int
#     name: str
#     cardinality: str
#     data_type: str
#     properties: list = field(default_factory=list)
#     user_data: dict = field(default_factory=dict)

#     @classmethod
#     def from_dict(cls, data: dict):
#         filtered_data = {k: v for k, v in data.items() if k in cls.__annotations__}
#         return cls(**filtered_data)


class PropertyKeyData:
    def __init__(self, dic):
        self.__id = dic["id"]
        self.__name = dic["name"]
        self.__cardinality = dic["cardinality"]
        self.__data_type = dic["data_type"]
        self.__user_data = dic["user_data"]

    @property
    def id(self):
        return self.__id

    @property
    def cardinality(self):
        return self.__cardinality

    @property
    def name(self):
        return self.__name

    @property
    def dataType(self):
        return self.__data_type

    @property
    def userdata(self):
        return self.__user_data

    def __repr__(self):
        res = f"name: {self.__name}, cardinality: {self.__cardinality}, data_type: {self.__data_type}"
        return res
