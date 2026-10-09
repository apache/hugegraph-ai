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

import json

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.utils.huge_decorator import decorator_create, decorator_params
from pyhugegraph.utils.log import log
from pyhugegraph.utils.util import ResponseValidation


class VertexLabel(HugeParamsBase):
    @decorator_params
    def useAutomaticId(self) -> "VertexLabel":
        self._parameter_holder.set("id_strategy", "AUTOMATIC")
        return self

    @decorator_params
    def useCustomizeStringId(self) -> "VertexLabel":
        self._parameter_holder.set("id_strategy", "CUSTOMIZE_STRING")
        return self

    @decorator_params
    def useCustomizeNumberId(self) -> "VertexLabel":
        self._parameter_holder.set("id_strategy", "CUSTOMIZE_NUMBER")
        return self

    @decorator_params
    def usePrimaryKeyId(self) -> "VertexLabel":
        self._parameter_holder.set("id_strategy", "PRIMARY_KEY")
        return self

    @decorator_params
    def properties(self, *args) -> "VertexLabel":
        self._parameter_holder.set("properties", list(args))
        return self

    @decorator_params
    def primaryKeys(self, *args) -> "VertexLabel":
        self._parameter_holder.set("primary_keys", list(args))
        return self

    @decorator_params
    def nullableKeys(self, *args) -> "VertexLabel":
        self._parameter_holder.set("nullable_keys", list(args))
        return self

    @decorator_params
    def enableLabelIndex(self, flag) -> "VertexLabel":
        self._parameter_holder.set("enable_label_index", flag)
        return self

    @decorator_params
    def userdata(self, *args) -> "VertexLabel":
        if "user_data" not in self._parameter_holder.get_keys():
            self._parameter_holder.set("user_data", {})
        user_data = self._parameter_holder.get_value("user_data")
        i = 0
        while i < len(args):
            user_data[args[i]] = args[i + 1]
            i += 2
        return self

    def ifNotExist(self) -> "VertexLabel":
        path = f"schema/vertexlabels/{self._parameter_holder.get_value('name')}"
        if _ := self._sess.request(path, validator=ResponseValidation(strict=False)):
            self._parameter_holder.set("not_exist", False)
        return self

    @decorator_create
    def create(self):
        dic = self._parameter_holder.get_dic()
        key_list = [
            "name",
            "id_strategy",
            "primary_keys",
            "nullable_keys",
            "index_labels",
            "properties",
            "enable_label_index",
            "user_data",
        ]
        data = {}
        for key in key_list:
            if key in dic:
                data[key] = dic[key]
        path = "schema/vertexlabels"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "POST", data=json.dumps(data)):
            return f'create VertexLabel success, Detail: "{response!s}"'
        log.error("create VertexLabel failed, Detail: %s", str(response))
        return ""

    @decorator_params
    def append(self) -> None:
        dic = self._parameter_holder.get_dic()
        properties = dic.get("properties", [])
        nullable_keys = dic.get("nullable_keys", [])
        user_data = dic.get("user_data", {})
        path = f"schema/vertexlabels/{dic['name']}?action=append"
        data = {
            "name": dic["name"],
            "properties": properties,
            "nullable_keys": nullable_keys,
            "user_data": user_data,
        }
        self.clean_parameter_holder()
        if response := self._sess.request(path, "PUT", data=json.dumps(data)):
            return f'append VertexLabel success, Detail: "{response!s}"'
        log.error("append VertexLabel failed, Detail: %s", str(response))
        return ""

    @decorator_params
    def remove(self) -> None:
        name = self._parameter_holder.get_value("name")
        path = f"schema/vertexlabels/{name}"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "DELETE"):
            return f'remove VertexLabel success, Detail: "{response!s}"'
        log.error("remove VertexLabel failed, Detail: %s", str(response))
        return ""

    @decorator_params
    def eliminate(self) -> None:
        name = self._parameter_holder.get_value("name")
        path = f"schema/vertexlabels/{name}/?action=eliminate"

        dic = self._parameter_holder.get_dic()
        user_data = dic.get("user_data", {})
        data = {
            "name": self._parameter_holder.get_value("name"),
            "user_data": user_data,
        }
        if response := self._sess.request(path, "PUT", data=json.dumps(data)):
            return f'eliminate VertexLabel success, Detail: "{response!s}"'
        log.error("eliminate VertexLabel failed, Detail: %s", str(response))
        return ""
