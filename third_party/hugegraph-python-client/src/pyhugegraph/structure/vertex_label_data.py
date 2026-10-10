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


class VertexLabelData:
    def __init__(self, dic):
        self.__id = dic["id"]
        self.__name = dic["name"]
        self.__id_strategy = dic["id_strategy"]
        self.__primary_keys = dic["primary_keys"]
        self.__nullable_keys = dic["nullable_keys"]
        self.__index_labels = dic["index_labels"]
        self.__properties = dic["properties"]
        self.__enable_label_index = dic["enable_label_index"]
        self.__user_data = dic["user_data"]

    @property
    def id(self):
        return self.__id

    @property
    def name(self):
        return self.__name

    @property
    def primaryKeys(self):
        return self.__primary_keys

    @property
    def idStrategy(self):
        return self.__id_strategy

    @property
    def properties(self):
        return self.__properties

    @property
    def nullableKeys(self):
        return self.__nullable_keys

    @property
    def userdata(self):
        return self.__user_data

    @property
    def indexLabels(self):
        return self.__index_labels

    @property
    def enableLabelIndex(self):
        return self.__enable_label_index

    def __repr__(self):
        res = f"name: {self.__name}, primary_keys: {self.__primary_keys}, properties: {self.__properties}"
        return res
