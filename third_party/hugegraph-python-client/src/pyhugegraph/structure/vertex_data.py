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


class VertexData:
    def __init__(self, dic):
        self.__id = dic["id"]
        self.__label = dic.get("label", None)
        self.__type = dic.get("type", None)
        self.__properties = dic.get("properties", None)

    @property
    def id(self):
        return self.__id

    @property
    def label(self):
        return self.__label

    @property
    def type(self):
        return self.__type

    @property
    def properties(self):
        return self.__properties

    def __repr__(self):
        res = f"id: {self.__id}, label: {self.__label}, type: {self.__type}"
        return res
