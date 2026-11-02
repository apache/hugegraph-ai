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


class VariableManager(HugeParamsBase):
    def set(self, key, value):
        return self.request("variables.update", data=json.dumps({"data": value}), path_params={"key": key})

    def get(self, key):
        return self.request("variables.get", path_params={"key": key})

    def all(self):
        return self.request("variables.list")

    def remove(self, key):
        return self.request("variables.delete", path_params={"key": key})
