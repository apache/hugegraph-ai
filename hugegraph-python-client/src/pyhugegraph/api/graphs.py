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
from pyhugegraph.utils.util import ResponseValidation


class GraphsManager(HugeParamsBase):
    @router.http("GET", "/graphs")
    def get_all_graphs(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))

    @router.http("GET", "/versions")
    def get_version(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))

    @router.http("GET", "")
    def get_graph_info(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))

    def clear_graph_all_data(self) -> dict:
        # Use PUT with an action body for HugeGraph 3.x+ (graph clear API)
        # For HugeGraph 1.7.0 and other 1.x versions, the clear endpoint uses
        # DELETE .../clear?confirm_message=... even when graphspace prefixes
        # are enabled. Only use the PUT behavior when the server version is
        # >= 3.0.0.
        version_tuple = tuple(self._sess.cfg.version) if self._sess.cfg.version else (0, 0, 0)
        if self._sess.cfg.gs_supported and version_tuple >= (3, 0, 0):
            response = self._sess.request(
                "",
                "PUT",
                validator=ResponseValidation("text"),
                data=json.dumps({"action": "clear", "clear_schema": True}),
            )
        else:
            response = self._sess.request(
                "clear?confirm_message=I%27m+sure+to+delete+all+data",
                "DELETE",
                validator=ResponseValidation("text"),
            )
        return response

    @router.http("GET", "conf")
    def get_graph_config(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))
