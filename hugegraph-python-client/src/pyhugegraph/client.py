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

from typing import Any, TypeVar

from pyhugegraph.api.auth import AuthManager
from pyhugegraph.api.common import HGraphContext
from pyhugegraph.api.graph import GraphManager
from pyhugegraph.api.graphs import GraphsManager
from pyhugegraph.api.gremlin import GremlinManager
from pyhugegraph.api.metric import MetricsManager
from pyhugegraph.api.olap import OlapManager
from pyhugegraph.api.rank import RankManager
from pyhugegraph.api.rebuild import RebuildManager
from pyhugegraph.api.rest import CypherAPI, GraphSpaceAPI, RestManager, SchemaTemplateAPI
from pyhugegraph.api.schema import SchemaManager
from pyhugegraph.api.task import TaskManager
from pyhugegraph.api.traverser import TraverserManager
from pyhugegraph.api.variable import VariableManager
from pyhugegraph.api.version import VersionManager
from pyhugegraph.utils.huge_config import HGraphConfig
from pyhugegraph.utils.huge_requests import HGraphSession

T = TypeVar("T", bound=HGraphContext)


class PyHugeClient:
    """HugeGraph client: OLTP traversals and asynchronous OLAP full-graph jobs."""

    def __init__(
        self,
        url: str,
        graph: str,
        user: str,
        pwd: str,
        graphspace: str | None = None,
        timeout: tuple[float, float] | None = None,
        *,
        token: str | None = None,
    ):
        self.cfg = HGraphConfig(url, user, pwd, graph, graphspace, timeout or (0.5, 15.0), token=token)
        self._session = HGraphSession(self.cfg)
        if token is not None:
            self.use_token(token)
        self._managers: dict[type, Any] = {}

    def _manager(self, manager_type: type[T]) -> T:
        if manager_type not in self._managers:
            self._managers[manager_type] = manager_type(self._session)
        return self._managers[manager_type]

    def use_token(self, token: str | None) -> None:
        """Explicitly select Bearer authentication, or restore Basic with None."""
        self._session.use_token(token)

    def schema(self) -> SchemaManager:
        return self._manager(SchemaManager)

    def gremlin(self) -> GremlinManager:
        return self._manager(GremlinManager)

    def graph(self) -> GraphManager:
        return self._manager(GraphManager)

    def graphs(self) -> GraphsManager:
        return self._manager(GraphsManager)

    def variable(self) -> VariableManager:
        return self._manager(VariableManager)

    def auth(self) -> AuthManager:
        return self._manager(AuthManager)

    def task(self) -> TaskManager:
        return self._manager(TaskManager)

    def metrics(self) -> MetricsManager:
        return self._manager(MetricsManager)

    def traverser(self) -> TraverserManager:
        return self._manager(TraverserManager)

    def version(self) -> VersionManager:
        return self._manager(VersionManager)

    def olap(self) -> OlapManager:
        return self._manager(OlapManager)

    def rank(self) -> RankManager:
        return self._manager(RankManager)

    def rebuild(self) -> RebuildManager:
        return self._manager(RebuildManager)

    def rest(self) -> RestManager:
        return self._manager(RestManager)

    def graphspaces(self) -> GraphSpaceAPI:
        return self._manager(GraphSpaceAPI)

    def schema_templates(self) -> SchemaTemplateAPI:
        return self._manager(SchemaTemplateAPI)

    def cypher(self) -> CypherAPI:
        return self._manager(CypherAPI)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "PyHugeClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"PyHugeClient(url={self.cfg.url!r}, graph={self.cfg.graph_name!r}, graphspace={self.cfg.graphspace!r})"
