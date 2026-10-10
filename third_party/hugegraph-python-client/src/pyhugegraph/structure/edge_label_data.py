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


class EdgeLabelData:
    def __init__(self, dic):
        self.__id = dic["id"]
        self.__name = dic["name"]
        self.__source_label = dic["source_label"]
        self.__target_label = dic["target_label"]
        self.__frequency = dic["frequency"]
        self.__sort_keys = dic["sort_keys"]
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
    def sourceLabel(self):
        return self.__source_label

    @property
    def targetLabel(self):
        return self.__target_label

    @property
    def frequency(self):
        return self.__frequency

    @property
    def sortKeys(self):
        return self.__sort_keys

    @property
    def properties(self):
        return self.__properties

    @property
    def nullableKeys(self):
        return self.__nullable_keys

    @property
    def userdata(self):
        return self.__user_data

    def relations(self):
        res = f"{self.__source_label}--{self.__name}-->{self.__target_label}"
        return res

    @property
    def indexLabels(self):
        return self.__index_labels

    @property
    def enableLabelIndex(self):
        return self.__enable_label_index

    def __repr__(self):
        res = f"name: {self.__name}, properties: {self.__properties}"
        return res
