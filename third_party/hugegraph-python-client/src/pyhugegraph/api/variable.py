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
from pyhugegraph.utils import huge_router as router


class VariableManager(HugeParamsBase):
    @router.http("PUT", "variables/{key}")
    def set(self, key, value):  # pylint: disable=unused-argument
        return self._invoke_request(data=json.dumps({"data": value}))

    @router.http("GET", "variables/{key}")
    def get(self, key):  # pylint: disable=unused-argument
        return self._invoke_request()

    @router.http("GET", "variables")
    def all(self):
        return self._invoke_request()

    @router.http("DELETE", "variables/{key}")
    def remove(self, key):  # pylint: disable=unused-argument
        return self._invoke_request()
