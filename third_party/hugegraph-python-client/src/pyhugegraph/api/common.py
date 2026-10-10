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


import re

from pyhugegraph.utils.huge_requests import HGraphSession
from pyhugegraph.utils.huge_router import RouterMixin
from pyhugegraph.utils.log import log


# todo: rename -> HGraphMetaData or delete
class ParameterHolder:
    def __init__(self):
        self._dic = {}

    def set(self, key, value):
        self._dic[key] = value

    def get_value(self, key):
        if key not in self._dic:
            return None
        return self._dic[key]

    def get_dic(self):
        return self._dic

    def get_keys(self):
        return self._dic.keys()


class HGraphContext:
    def __init__(self, sess: HGraphSession) -> None:
        self._sess = sess
        self._cache = {}  # todo: move parameter_holder to cache

    def close(self):
        self._sess.close()

    @property
    def session(self):
        """
        Get session.

        Returns:
        -------
            HGraphSession: session
        """
        return self._sess


# todo: rename -> HGraphModule | HGraphRouterable | HGraphModel
class HugeParamsBase(HGraphContext, RouterMixin):
    def __init__(self, sess: HGraphSession) -> None:
        super().__init__(sess)
        self._parameter_holder = None
        self.__camel_to_snake_case()

    def add_parameter(self, key, value):
        self._parameter_holder.set(key, value)

    def get_parameter_holder(self):
        return self._parameter_holder

    def create_parameter_holder(self):
        self._parameter_holder = ParameterHolder()

    def clean_parameter_holder(self):
        self._parameter_holder = None

    def __camel_to_snake_case(self):
        camel_case_pattern = re.compile(r"^[a-z]+([A-Z][a-z]*)+$")
        attributes = dir(self)
        for attr in attributes:
            if attr.startswith("__"):
                continue
            if not callable(getattr(self, attr)):
                continue
            if camel_case_pattern.match(attr):
                s = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", attr)
                snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s).lower()
                setattr(self, snake, getattr(self, attr))
                log.debug(  # pylint: disable=logging-fstring-interpolation
                    f"The method {self.__class__.__name__}.{attr} "
                    f"is deprecated and will be removed in future versions. "
                    f"Please update your code to use the new method name {self.__class__.__name__}.{snake} instead."
                )
