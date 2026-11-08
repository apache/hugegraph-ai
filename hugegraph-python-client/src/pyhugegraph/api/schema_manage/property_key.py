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


# TODO: support UpdateStrategy for PropertyKey (refer java-client/rest-api)
class PropertyKey(HugeParamsBase):
    # Data Type: [OBJECT, BOOLEAN, BYTE, INT, LONG, FLOAT, DOUBLE, TEXT, BLOB, DATE]
    @decorator_params
    def as_object(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "OBJECT")
        return self

    @decorator_params
    def as_bool(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "BOOLEAN")
        return self

    @decorator_params
    def as_byte(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "BYTE")
        return self

    @decorator_params
    def as_int(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "INT")
        return self

    @decorator_params
    def as_long(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "LONG")
        return self

    @decorator_params
    def as_float(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "FLOAT")
        return self

    @decorator_params
    def as_double(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "DOUBLE")
        return self

    @decorator_params
    def as_text(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "TEXT")
        return self

    @decorator_params
    def as_blob(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "BLOB")
        return self

    @decorator_params
    def as_date(self) -> "PropertyKey":
        self._parameter_holder.set("data_type", "DATE")
        return self

    #  Cardinality Type [SINGLE, LIST, SET]
    @decorator_params
    def value_single(self) -> "PropertyKey":
        self._parameter_holder.set("cardinality", "SINGLE")
        return self

    @decorator_params
    def value_list(self) -> "PropertyKey":
        self._parameter_holder.set("cardinality", "LIST")
        return self

    @decorator_params
    def value_set(self) -> "PropertyKey":
        self._parameter_holder.set("cardinality", "SET")
        return self

    #  Aggregate Type [NONE, MAX, MIN, SUM, OLD]
    @decorator_params
    def calc_max(self) -> "PropertyKey":
        self._parameter_holder.set("aggregate_type", "MAX")
        return self

    @decorator_params
    def calc_min(self) -> "PropertyKey":
        self._parameter_holder.set("aggregate_type", "MIN")
        return self

    @decorator_params
    def calc_sum(self) -> "PropertyKey":
        self._parameter_holder.set("aggregate_type", "SUM")
        return self

    @decorator_params
    def calc_old(self) -> "PropertyKey":
        self._parameter_holder.set("aggregate_type", "OLD")
        return self

    @decorator_params
    def userdata(self, *args) -> "PropertyKey":
        user_data = self._parameter_holder.get_value("user_data")
        if not user_data:
            self._parameter_holder.set("user_data", {})
            user_data = self._parameter_holder.get_value("user_data")
        i = 0
        while i < len(args):
            user_data[args[i]] = args[i + 1]
            i += 2
        return self

    def if_not_exist(self) -> "PropertyKey":
        path = f"schema/propertykeys/{self._parameter_holder.get_value('name')}"
        if _ := self._sess.request(path, validator=ResponseValidation(strict=False)):
            self._parameter_holder.set("not_exist", False)
        return self

    @decorator_create
    def create(self):
        dic = self._parameter_holder.get_dic()
        property_keys = {"name": dic["name"]}
        if "data_type" in dic:
            property_keys["data_type"] = dic["data_type"]
        if "cardinality" in dic:
            property_keys["cardinality"] = dic["cardinality"]
        if "aggregate_type" in dic:
            property_keys["aggregate_type"] = dic["aggregate_type"]
        if dic.get("user_data"):
            property_keys["user_data"] = dic["user_data"]
        path = "schema/propertykeys"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "POST", data=json.dumps(property_keys)):
            return f"create PropertyKey success, Detail: {response!s}"
        log.error("create PropertyKey failed, Detail: %s", str(response))
        return ""

    @decorator_params
    def append(self):
        property_name = self._parameter_holder.get_value("name")
        user_data = self._parameter_holder.get_value("user_data")
        if not user_data:
            user_data = {}
        data = {"name": property_name, "user_data": user_data}

        path = f"schema/propertykeys/{property_name}/?action=append"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "PUT", data=json.dumps(data)):
            return f"append PropertyKey success, Detail: {response!s}"
        log.error("append PropertyKey failed, Detail: %s", str(response))
        return ""

    @decorator_params
    def eliminate(self):
        property_name = self._parameter_holder.get_value("name")
        user_data = self._parameter_holder.get_value("user_data")
        if not user_data:
            user_data = {}
        data = {"name": property_name, "user_data": user_data}

        path = f"schema/propertykeys/{property_name}/?action=eliminate"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "PUT", data=json.dumps(data)):
            return f"eliminate PropertyKey success, Detail: {response!s}"
        log.error("eliminate PropertyKey failed, Detail: %s", str(response))
        return ""

    @decorator_params
    def remove(self):
        dic = self._parameter_holder.get_dic()
        path = f"schema/propertykeys/{dic['name']}"
        self.clean_parameter_holder()
        if response := self._sess.request(path, "DELETE"):
            return f"delete PropertyKey success, Detail: {response!s}"
        log.error("delete PropertyKey failed, Detail: %s", str(response))
        return ""

    # Legacy public names share the canonical implementations.
    asBlob = as_blob  # noqa: N815
    asBool = as_bool  # noqa: N815
    asByte = as_byte  # noqa: N815
    asDate = as_date  # noqa: N815
    asDouble = as_double  # noqa: N815
    asFloat = as_float  # noqa: N815
    asInt = as_int  # noqa: N815
    asLong = as_long  # noqa: N815
    asObject = as_object  # noqa: N815
    asText = as_text  # noqa: N815
    calcMax = calc_max  # noqa: N815
    calcMin = calc_min  # noqa: N815
    calcOld = calc_old  # noqa: N815
    calcSum = calc_sum  # noqa: N815
    ifNotExist = if_not_exist  # noqa: N815
    valueList = value_list  # noqa: N815
    valueSet = value_set  # noqa: N815
    valueSingle = value_single  # noqa: N815
