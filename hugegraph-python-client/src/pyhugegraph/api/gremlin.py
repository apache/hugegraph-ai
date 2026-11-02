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
from pyhugegraph.utils.compat import ServerAdapter
from pyhugegraph.utils.exceptions import ResponseParseError
from pyhugegraph.utils.log import log

_REQUIRED_RESPONSE_FIELDS = {"requestId", "status", "result"}


class GremlinManager(HugeParamsBase):
    def exec(self, gremlin):
        gremlin_data = GremlinData(gremlin)

        gremlin_data.aliases = ServerAdapter(self.session.cfg).aliases()

        response = self.request("gremlin.post", data=gremlin_data.to_json())
        if response is not None:
            if not isinstance(response, dict) or not _REQUIRED_RESPONSE_FIELDS.issubset(response):
                raise ResponseParseError(f"Invalid Gremlin response payload: {response}")
            return ResponseData(response).result
        log.error("Gremlin can't get results: %s", str(response))
        return None

    def submit(self, gremlin: str, *, bindings=None, language="gremlin-groovy") -> dict:
        """Submit an asynchronous Gremlin job; inspect it with client.task()."""
        return self.request(
            "gremlin_job.post",
            body={
                "gremlin": gremlin,
                "bindings": bindings or {},
                "language": language,
            },
        )

    def query(self, gremlin: str, *, bindings=None, language="gremlin-groovy") -> dict:
        """Return the complete synchronous Gremlin response envelope."""
        return self.request(
            "gremlin.post",
            body={
                "gremlin": gremlin,
                "bindings": bindings or {},
                "language": language,
                "aliases": ServerAdapter(self.session.cfg).aliases(),
            },
        )
