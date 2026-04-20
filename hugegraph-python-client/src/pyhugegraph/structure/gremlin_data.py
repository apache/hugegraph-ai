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


class GremlinData:
    def __init__(self, gremlin):
        self.__gremlin = gremlin
        self.__bindings = {}
        self.__language = "gremlin-groovy"
        self.__aliases = {}

    @property
    def gremlin(self):
        return self.__gremlin

    @gremlin.setter
    def gremlin(self, _gremlin):
        self.__gremlin = _gremlin

    @property
    def bindings(self):
        return self.__bindings

    @bindings.setter
    def bindings(self, _bindings):
        self.__bindings = _bindings

    @property
    def language(self):
        return self.__language

    @language.setter
    def language(self, _language):
        self.__language = _language

    @property
    def aliases(self):
        return self.__aliases

    @aliases.setter
    def aliases(self, _aliases):
        self.__aliases = _aliases

    def __repr__(self):
        res = (
            f"gremlin: {self.__gremlin}, bindings: {self.__bindings},"
            f"language: {self.__language}, aliases: {self.__aliases}"
        )
        return res

    def to_json(self):
        return json.dumps(self, cls=GremlinDataEncoder)


class GremlinDataEncoder(json.JSONEncoder):
    def default(self, o):
        return {k.split("__")[1]: v for k, v in vars(o).items()}
