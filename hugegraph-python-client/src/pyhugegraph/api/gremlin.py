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


from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.structure.gremlin_data import GremlinData
from pyhugegraph.structure.response_data import ResponseData
from pyhugegraph.utils import huge_router as router
from pyhugegraph.utils.exceptions import NotFoundError
from pyhugegraph.utils.log import log


class GremlinManager(HugeParamsBase):
    @router.http("POST", "/gremlin")
    def exec(self, gremlin):
        gremlin_data = GremlinData(gremlin)

        # Version-specific gremlin request handling
        if self._sess.cfg.gs_supported:
            # For graphspace-supported versions, use graphspace-scoped aliases.
            # This includes HugeGraph 1.7.0+ when graphspace support is enabled.
            gremlin_data.aliases = {
                "graph": f"{self._sess.cfg.graphspace}-{self._sess.cfg.graph_name}",
                "g": f"__g_{self._sess.cfg.graphspace}-{self._sess.cfg.graph_name}",
            }
        else:
            # For HugeGraph versions without graphspace support, always include aliases
            # so `g` is bound.
            gremlin_data.aliases = {
                "graph": f"{self._sess.cfg.graph_name}",
                "g": f"__g_{self._sess.cfg.graph_name}",
            }

        try:
            if response := self._invoke_request(data=gremlin_data.to_json()):
                return ResponseData(response).result
            log.error("Gremlin can't get results: %s", str(response))
            return None
        except Exception as e:
            raise NotFoundError(f"Gremlin can't get results: {e}") from e
