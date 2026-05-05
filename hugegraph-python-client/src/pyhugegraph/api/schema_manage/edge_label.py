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

# pylint: disable=logging-fstring-interpolation

import json

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.utils.huge_decorator import decorator_create, decorator_params
from pyhugegraph.utils.log import log
from pyhugegraph.utils.util import ResponseValidation


class EdgeLabel(HugeParamsBase):
    @decorator_params
    def link(self, source_label, target_label) -> "EdgeLabel":
        self._parameter_holder.set("source_label", source_label)
        self._parameter_holder.set("target_label", target_label)
        return self

    @decorator_params
    def sourceLabel(self, source_label) -> "EdgeLabel":
        self._parameter_holder.set("source_label", source_label)
        return self

    @decorator_params
    def targetLabel(self, target_label) -> "EdgeLabel":
        self._parameter_holder.set("target_label", target_label)
        return self

    @decorator_params
    def userdata(self, *args) -> "EdgeLabel":
        if not self._parameter_holder.get_value("user_data"):
            self._parameter_holder.set("user_data", {})
        user_data = self._parameter_holder.get_value("user_data")
        i = 0
        while i < len(args):
            user_data[args[i]] = args[i + 1]
            i += 2
        return self

    @decorator_params
    def properties(self, *args) -> "EdgeLabel":
        self._parameter_holder.set("properties", list(args))
        return self

    @decorator_params
    def singleTime(self) -> "EdgeLabel":
        self._parameter_holder.set("frequency", "SINGLE")
        return self

    @decorator_params
    def multiTimes(self) -> "EdgeLabel":
        self._parameter_holder.set("frequency", "MULTIPLE")
        return self

    @decorator_params
    def sortKeys(self, *args) -> "EdgeLabel":
        self._parameter_holder.set("sort_keys", list(args))
        return self

    @decorator_params
    def nullableKeys(self, *args) -> "EdgeLabel":
        nullable_keys = set(args)
        self._parameter_holder.set("nullable_keys", list(nullable_keys))
        return self

    @decorator_params
    def ifNotExist(self) -> "EdgeLabel":
        path = f"schema/edgelabels/{self._parameter_holder.get_value('name')}"
        if _ := self._sess.request(path, validator=ResponseValidation(strict=False)):
            self._parameter_holder.set("not_exist", False)
        return self

    @decorator_params
    def enableLabelIndex(self, flag) -> "EdgeLabel":
        """
        Set whether to enable label indexing. If enabled, you can use `edge_labels[label]` to access the edge's label.
        Default is False.
        """
        self._parameter_holder.set("enable_label_index", flag)
        return self

    @decorator_params
    def parent(self, parent_label) -> "EdgeLabel":
        """
        Set parent edge label for supporting parent & child edge label type (HugeGraph 1.7.0+).
        When an edge label has a parent, it becomes a child edge label with inherited properties.
        """
        self._parameter_holder.set("parent_label", parent_label)
        self._parameter_holder.set("edgelabel_type", "SUB")
        return self

    @decorator_create
    def create(self):
        dic = self._parameter_holder.get_dic()
        data = {}
        keys = [
            "name",
            "source_label",
            "target_label",
            "nullable_keys",
            "properties",
            "enable_label_index",
            "sort_keys",
            "user_data",
            "frequency",
            "parent_label",  # Support parent & child edge label type (HugeGraph 1.7.0+)
            "edgelabel_type",  # Required when parent_label is set (PARENT or SUB)
        ]
        for key in keys:
            if key in dic:
                data[key] = dic[key]
        path = "schema/edgelabels"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "POST", data=json.dumps(data)):
            return f'create EdgeLabel success, Detail: "{response!s}"'
        log.error(f'create EdgeLabel failed, Detail: "{response!s}"')
        return None

    @decorator_params
    def remove(self):
        path = f"schema/edgelabels/{self._parameter_holder.get_value('name')}"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "DELETE"):
            return f'remove EdgeLabel success, Detail: "{response!s}"'
        log.error(f'remove EdgeLabel failed, Detail: "{response!s}"')
        return None

    @decorator_params
    def append(self):
        dic = self._parameter_holder.get_dic()
        data = {}
        keys = ["name", "nullable_keys", "properties", "user_data"]
        for key in keys:
            if key in dic:
                data[key] = dic[key]

        path = f"schema/edgelabels/{data['name']}?action=append"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "PUT", data=json.dumps(data)):
            return f'append EdgeLabel success, Detail: "{response!s}"'
        log.error(f'append EdgeLabel failed, Detail: "{response!s}"')
        return None

    @decorator_params
    def eliminate(self):
        name = self._parameter_holder.get_value("name")
        user_data = (
            self._parameter_holder.get_value("user_data") if self._parameter_holder.get_value("user_data") else {}
        )
        path = f"schema/edgelabels/{name}?action=eliminate"
        data = {"name": name, "user_data": user_data}
        self.clean_parameter_holder()
        if response := self._sess.request(path, "PUT", data=json.dumps(data)):
            return f'eliminate EdgeLabel success, Detail: "{response!s}"'
        log.error(f'eliminate EdgeLabel failed, Detail: "{response!s}"')
        return None
