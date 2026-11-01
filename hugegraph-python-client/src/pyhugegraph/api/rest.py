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

"""Explicit low-level REST resources for the pinned server contract.

Common workflows are available on the client managers; these resources expose
every REST operation, including deployment-specific extensions.
"""

from typing import Any

from pyhugegraph.api.common import RestResource


class ArthasAPI(RestResource):
    def start_arthas(self) -> Any:
        """PUT /arthas."""
        return self.request("arthas.start_arthas")


class AccessAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/auth/accesses."""
        return self.request("access.create", body=body)

    def update(self, id: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/auth/accesses/{id}."""
        return self.request("access.update", path_params={"id": id}, body=body)

    def list(self, *, group: Any = None, target: Any = None, limit: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/accesses."""
        return self.request("access.list", params={"group": group, "target": target, "limit": limit})

    def get(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/auth/accesses/{id}."""
        return self.request("access.get", path_params={"id": id})

    def delete(self, id: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/auth/accesses/{id}."""
        return self.request("access.delete", path_params={"id": id})


class BelongAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/auth/belongs."""
        return self.request("belong.create", body=body)

    def update(self, id: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/auth/belongs/{id}."""
        return self.request("belong.update", path_params={"id": id}, body=body)

    def list(self, *, user: Any = None, group: Any = None, limit: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/belongs."""
        return self.request("belong.list", params={"user": user, "group": group, "limit": limit})

    def get(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/auth/belongs/{id}."""
        return self.request("belong.get", path_params={"id": id})

    def delete(self, id: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/auth/belongs/{id}."""
        return self.request("belong.delete", path_params={"id": id})


class GraphSpaceGroupAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/auth/groups."""
        return self.request("graph_space_group.create", body=body)

    def update(self, id: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/auth/groups/{id}."""
        return self.request("graph_space_group.update", path_params={"id": id}, body=body)

    def list(self, *, limit: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/groups."""
        return self.request("graph_space_group.list", params={"limit": limit})

    def get(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/auth/groups/{id}."""
        return self.request("graph_space_group.get", path_params={"id": id})

    def delete(self, id: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/auth/groups/{id}."""
        return self.request("graph_space_group.delete", path_params={"id": id})


class GroupAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /auth/groups."""
        return self.request("group.create", body=body)

    def update(self, id: Any, *, body: Any = None) -> Any:
        """PUT /auth/groups/{id}."""
        return self.request("group.update", path_params={"id": id}, body=body)

    def list(self, *, limit: Any = None) -> Any:
        """GET /auth/groups."""
        return self.request("group.list", params={"limit": limit})

    def get(self, id: Any) -> Any:
        """GET /auth/groups/{id}."""
        return self.request("group.get", path_params={"id": id})

    def delete(self, id: Any) -> Any:
        """DELETE /auth/groups/{id}."""
        return self.request("group.delete", path_params={"id": id})


class LoginAPI(RestResource):
    def login(self, *, body: Any = None) -> Any:
        """POST /auth/login."""
        return self.request("login.login", body=body)

    def logout(self, *, authorization: str | None = None) -> Any:
        """DELETE /auth/logout."""
        return self.request("login.logout", headers={"Authorization": authorization})

    def verify_token(self, *, authorization: str | None = None) -> Any:
        """GET /auth/verify."""
        return self.request("login.verify_token", headers={"Authorization": authorization})


class ManagerAPI(RestResource):
    def create_manager(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/auth/managers."""
        return self.request("manager.create_manager", body=body)

    def delete(self, *, user: Any = None, type: Any = None) -> Any:
        """DELETE /graphspaces/{graphspace}/auth/managers."""
        return self.request("manager.delete", params={"user": user, "type": type})

    def list(self, *, type: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/managers."""
        return self.request("manager.list", params={"type": type})

    def check_role(self, *, type: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/managers/check."""
        return self.request("manager.check_role", params={"type": type})

    def get_roles_in_gs(self, *, user: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/managers/role."""
        return self.request("manager.get_roles_in_gs", params={"user": user})

    def check_default_role(self, *, role: Any = None, graph: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/managers/default."""
        return self.request("manager.check_default_role", params={"role": role, "graph": graph})


class ProjectAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/auth/projects."""
        return self.request("project.create", body=body)

    def update(self, id: Any, *, body: Any = None, action: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/auth/projects/{id}."""
        return self.request("project.update", path_params={"id": id}, params={"action": action}, body=body)

    def list(self, *, limit: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/projects."""
        return self.request("project.list", params={"limit": limit})

    def get(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/auth/projects/{id}."""
        return self.request("project.get", path_params={"id": id})

    def delete(self, id: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/auth/projects/{id}."""
        return self.request("project.delete", path_params={"id": id})


class TargetAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/auth/targets."""
        return self.request("target.create", body=body)

    def update(self, id: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/auth/targets/{id}."""
        return self.request("target.update", path_params={"id": id}, body=body)

    def list(self, *, limit: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/targets."""
        return self.request("target.list", params={"limit": limit})

    def get(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/auth/targets/{id}."""
        return self.request("target.get", path_params={"id": id})

    def delete(self, id: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/auth/targets/{id}."""
        return self.request("target.delete", path_params={"id": id})


class UserAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/auth/users."""
        return self.request("user.create", body=body)

    def update(self, id: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/auth/users/{id}."""
        return self.request("user.update", path_params={"id": id}, body=body)

    def list(self, *, name: Any = None, limit: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/auth/users."""
        return self.request("user.list", params={"name": name, "limit": limit})

    def get(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/auth/users/{id}."""
        return self.request("user.get", path_params={"id": id})

    def role(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/auth/users/{id}/role."""
        return self.request("user.role", path_params={"id": id})

    def delete(self, id: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/auth/users/{id}."""
        return self.request("user.delete", path_params={"id": id})


class CypherAPI(RestResource):
    def query(self, *, cypher: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/cypher."""
        return self.request("cypher.query", params={"cypher": cypher})

    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/cypher."""
        return self.request("cypher.post", body=body)


class EdgeAPI(RestResource):
    def create_batch(self, *, body: Any = None, check_vertex: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/graph/edges/batch."""
        return self.request("edge.create_batch", params={"check_vertex": check_vertex}, body=body)

    def update_batch(self, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/graph/edges/batch."""
        return self.request("edge.update_batch", body=body)

    def update_by_id(self, id: Any, *, body: Any = None, action: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/graph/edges/{id}."""
        return self.request("edge.update_by_id", path_params={"id": id}, params={"action": action}, body=body)

    def list(
        self,
        *,
        vertex_id: Any = None,
        direction: Any = None,
        label: Any = None,
        properties: Any = None,
        keep_start_p: Any = None,
        offset: Any = None,
        page: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/graph/edges."""
        return self.request(
            "edge.list",
            params={
                "vertex_id": vertex_id,
                "direction": direction,
                "label": label,
                "properties": properties,
                "keep_start_p": keep_start_p,
                "offset": offset,
                "page": page,
                "limit": limit,
            },
        )

    def get(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/graph/edges/{id}."""
        return self.request("edge.get", path_params={"id": id})

    def delete(self, id: Any, *, label: Any = None) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{graph}/graph/edges/{id}."""
        return self.request("edge.delete", path_params={"id": id}, params={"label": label})

    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/graph/edges."""
        return self.request("edge.create", body=body)


class VertexAPI(RestResource):
    def create_batch(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/graph/vertices/batch."""
        return self.request("vertex.create_batch", body=body)

    def update_batch(self, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/graph/vertices/batch."""
        return self.request("vertex.update_batch", body=body)

    def update_by_id(self, id: Any, *, body: Any = None, action: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/graph/vertices/{id}."""
        return self.request("vertex.update_by_id", path_params={"id": id}, params={"action": action}, body=body)

    def list(
        self,
        *,
        label: Any = None,
        properties: Any = None,
        keep_start_p: Any = None,
        offset: Any = None,
        page: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/graph/vertices."""
        return self.request(
            "vertex.list",
            params={
                "label": label,
                "properties": properties,
                "keep_start_p": keep_start_p,
                "offset": offset,
                "page": page,
                "limit": limit,
            },
        )

    def get(self, id: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/graph/vertices/{id}."""
        return self.request("vertex.get", path_params={"id": id})

    def delete(self, id: Any, *, label: Any = None) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{graph}/graph/vertices/{id}."""
        return self.request("vertex.delete", path_params={"id": id}, params={"label": label})

    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/graph/vertices."""
        return self.request("vertex.create", body=body)


class GremlinAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /gremlin."""
        return self.request("gremlin.post", body=body)

    def get(self) -> Any:
        """GET /gremlin."""
        return self.request("gremlin.get")


class AlgorithmAPI(RestResource):
    def post(self, name: Any, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/jobs/algorithm/{name}."""
        return self.request("algorithm.post", path_params={"name": name}, body=body)


class ComputerAPI(RestResource):
    def post(self, name: Any, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/jobs/computer/{name}."""
        return self.request("computer.post", path_params={"name": name}, body=body)


class GremlinJobAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/jobs/gremlin."""
        return self.request("gremlin_job.post", body=body)


class RebuildAPI(RestResource):
    def vertex_label_rebuild(self, name: Any) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/jobs/rebuild/vertexlabels/{name}."""
        return self.request("rebuild.vertex_label_rebuild", path_params={"name": name})

    def edge_label_rebuild(self, name: Any) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/jobs/rebuild/edgelabels/{name}."""
        return self.request("rebuild.edge_label_rebuild", path_params={"name": name})

    def index_label_rebuild(self, name: Any) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/jobs/rebuild/indexlabels/{name}."""
        return self.request("rebuild.index_label_rebuild", path_params={"name": name})


class TaskAPI(RestResource):
    def list(self, *, status: Any = None, ids: Any = None, limit: Any = None, page: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/tasks."""
        return self.request("task.list", params={"status": status, "ids": ids, "limit": limit, "page": page})

    def get(self, id: Any, *, with_result: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/tasks/{id}."""
        return self.request("task.get", path_params={"id": id}, params={"with_result": with_result})

    def delete(self, id: Any, *, force: Any = None) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{graph}/tasks/{id}."""
        return self.request("task.delete", path_params={"id": id}, params={"force": force})

    def update(self, id: Any, *, action: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/tasks/{id}."""
        return self.request("task.update", path_params={"id": id}, params={"action": action})


class MetricsAPI(RestResource):
    def system(self) -> Any:
        """GET /metrics/system."""
        return self.request("metrics.system")

    def backend(self) -> Any:
        """GET /metrics/backend."""
        return self.request("metrics.backend")

    def gauges(self) -> Any:
        """GET /metrics/gauges."""
        return self.request("metrics.gauges")

    def counters(self) -> Any:
        """GET /metrics/counters."""
        return self.request("metrics.counters")

    def histograms(self) -> Any:
        """GET /metrics/histograms."""
        return self.request("metrics.histograms")

    def meters(self) -> Any:
        """GET /metrics/meters."""
        return self.request("metrics.meters")

    def timers(self) -> Any:
        """GET /metrics/timers."""
        return self.request("metrics.timers")

    def all(self, *, type: Any = None) -> Any:
        """GET /metrics."""
        return self.request("metrics.all", params={"type": type})

    def statistics(self, *, type: Any = None) -> Any:
        """GET /metrics/statistics."""
        return self.request("metrics.statistics", params={"type": type})


class GraphsAPI(RestResource):
    def list(self) -> Any:
        """GET /graphspaces/{graphspace}/graphs."""
        return self.request("graphs.list")

    def list_profile(self, *, prefix: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/profile."""
        return self.request("graphs.list_profile", params={"prefix": prefix})

    def get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{name}."""
        return self.request("graphs.get", path_params={"name": name})

    def set_default(self, name: Any) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{name}/default."""
        return self.request("graphs.set_default", path_params={"name": name})

    def unset_default(self, name: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{name}/default."""
        return self.request("graphs.unset_default", path_params={"name": name})

    def get_default(self) -> Any:
        """GET /graphspaces/{graphspace}/graphs/default."""
        return self.request("graphs.get_default")

    def drop(self, name: Any, *, confirm_message: Any = None) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{name}."""
        return self.request("graphs.drop", path_params={"name": name}, params={"confirm_message": confirm_message})

    def manage(self, name: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{name}."""
        return self.request("graphs.manage", path_params={"name": name}, body=body)

    def reload(self, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/manage."""
        return self.request("graphs.reload", body=body)

    def create(self, name: Any, *, body: Any = None, clone_graph_name: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{name}."""
        return self.request(
            "graphs.create", path_params={"name": name}, params={"clone_graph_name": clone_graph_name}, body=body
        )

    def clone_schema(self, name: Any, *, body: Any = None, source: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{name}/schema-clone."""
        return self.request("graphs.clone_schema", path_params={"name": name}, params={"source": source}, body=body)

    def create_by_text(self, name: Any, *, body: Any = None, clone_graph_name: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{name}."""
        return self.request(
            "graphs.create_by_text",
            path_params={"name": name},
            params={"clone_graph_name": clone_graph_name},
            body=body,
        )

    def get_conf(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{name}/conf."""
        return self.request("graphs.get_conf", path_params={"name": name})

    def clear(self, name: Any, *, confirm_message: Any = None) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{name}/clear."""
        return self.request("graphs.clear", path_params={"name": name}, params={"confirm_message": confirm_message})

    def create_snapshot(self, name: Any) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{name}/snapshot_create."""
        return self.request("graphs.create_snapshot", path_params={"name": name})

    def resume_snapshot(self, name: Any) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{name}/snapshot_resume."""
        return self.request("graphs.resume_snapshot", path_params={"name": name})

    def compact(self, name: Any) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{name}/compact."""
        return self.request("graphs.compact", path_params={"name": name})

    def mode_set(self, name: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{name}/mode."""
        return self.request("graphs.mode_set", path_params={"name": name}, body=body)

    def mode_get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{name}/mode."""
        return self.request("graphs.mode_get", path_params={"name": name})

    def loading_mode_get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{name}/mode/owners."""
        return self.request("graphs.loading_mode_get", path_params={"name": name})

    def loading_mode_set(self, name: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{name}/mode/owners."""
        return self.request("graphs.loading_mode_set", path_params={"name": name}, body=body)

    def graph_read_mode_set(self, name: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{name}/graph_read_mode."""
        return self.request("graphs.graph_read_mode_set", path_params={"name": name}, body=body)

    def graph_read_mode_get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{name}/graph_read_mode."""
        return self.request("graphs.graph_read_mode_get", path_params={"name": name})


class ProfileAPI(RestResource):
    def get_profile(self) -> Any:
        """GET /."""
        return self.request("profile.get_profile")

    def show_all_ap_is(self) -> Any:
        """GET /apis."""
        return self.request("profile.show_all_ap_is")


class VersionAPI(RestResource):
    def list(self) -> Any:
        """GET /versions."""
        return self.request("version.list")


class WhiteIpListAPI(RestResource):
    def list(self) -> Any:
        """GET /whiteiplist."""
        return self.request("white_ip_list.list")

    def update_white_i_ps(self, *, body: Any = None) -> Any:
        """POST /whiteiplist."""
        return self.request("white_ip_list.update_white_i_ps", body=body)

    def update_status(self, *, status: Any = None) -> Any:
        """PUT /whiteiplist."""
        return self.request("white_ip_list.update_status", params={"status": status})


class RaftAPI(RestResource):
    def list_peers(self, *, group: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/raft/list_peers."""
        return self.request("raft.list_peers", params={"group": group})

    def get_leader(self, *, group: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/raft/get_leader."""
        return self.request("raft.get_leader", params={"group": group})

    def transfer_leader(self, *, group: Any = None, endpoint: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/raft/transfer_leader."""
        return self.request("raft.transfer_leader", params={"group": group, "endpoint": endpoint})

    def set_leader(self, *, group: Any = None, endpoint: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/raft/set_leader."""
        return self.request("raft.set_leader", params={"group": group, "endpoint": endpoint})

    def add_peer(self, *, group: Any = None, endpoint: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/raft/add_peer."""
        return self.request("raft.add_peer", params={"group": group, "endpoint": endpoint})

    def remove_peer(self, *, group: Any = None, endpoint: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/raft/remove_peer."""
        return self.request("raft.remove_peer", params={"group": group, "endpoint": endpoint})


class EdgeLabelAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels."""
        return self.request("edge_label.create", body=body)

    def update(self, name: Any, *, body: Any = None, action: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels/{name}."""
        return self.request("edge_label.update", path_params={"name": name}, params={"action": action}, body=body)

    def list(self, *, names: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels."""
        return self.request("edge_label.list", params={"names": names})

    def get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels/{name}."""
        return self.request("edge_label.get", path_params={"name": name})

    def delete(self, name: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels/{name}."""
        return self.request("edge_label.delete", path_params={"name": name})


class IndexLabelAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels."""
        return self.request("index_label.create", body=body)

    def update(self, name: Any, *, body: Any = None, action: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels/{name}."""
        return self.request("index_label.update", path_params={"name": name}, params={"action": action}, body=body)

    def list(self, *, names: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels."""
        return self.request("index_label.list", params={"names": names})

    def get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels/{name}."""
        return self.request("index_label.get", path_params={"name": name})

    def delete(self, name: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels/{name}."""
        return self.request("index_label.delete", path_params={"name": name})


class PropertyKeyAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys."""
        return self.request("property_key.create", body=body)

    def update(self, name: Any, *, body: Any = None, action: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys/{name}."""
        return self.request("property_key.update", path_params={"name": name}, params={"action": action}, body=body)

    def list(self, *, names: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys."""
        return self.request("property_key.list", params={"names": names})

    def get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys/{name}."""
        return self.request("property_key.get", path_params={"name": name})

    def delete(self, name: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys/{name}."""
        return self.request("property_key.delete", path_params={"name": name})


class SchemaAPI(RestResource):
    def list(self) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema."""
        return self.request("schema.list")


class VertexLabelAPI(RestResource):
    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels."""
        return self.request("vertex_label.create", body=body)

    def update(self, name: Any, *, body: Any = None, action: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels/{name}."""
        return self.request("vertex_label.update", path_params={"name": name}, params={"action": action}, body=body)

    def list(self, *, names: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels."""
        return self.request("vertex_label.list", params={"names": names})

    def get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels/{name}."""
        return self.request("vertex_label.get", path_params={"name": name})

    def delete(self, name: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels/{name}."""
        return self.request("vertex_label.delete", path_params={"name": name})


class GraphSpaceAPI(RestResource):
    def list(self) -> Any:
        """GET /graphspaces."""
        return self.request("graph_space.list")

    def get(self) -> Any:
        """GET /graphspaces/{graphspace}."""
        return self.request("graph_space.get")

    def set_default_role(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/role."""
        return self.request("graph_space.set_default_role", body=body)

    def check_default_role(self, *, user: Any = None, role: Any = None, graph: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/role."""
        return self.request("graph_space.check_default_role", params={"user": user, "role": role, "graph": graph})

    def delete_default_role(self, *, user: Any = None, role: Any = None, graph: Any = None) -> Any:
        """DELETE /graphspaces/{graphspace}/role."""
        return self.request("graph_space.delete_default_role", params={"user": user, "role": role, "graph": graph})

    def list_profile(self, *, prefix: Any = None) -> Any:
        """GET /graphspaces/profile."""
        return self.request("graph_space.list_profile", params={"prefix": prefix})

    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces."""
        return self.request("graph_space.create", body=body)

    def manage(self, name: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{name}."""
        return self.request("graph_space.manage", path_params={"name": name}, body=body)

    def delete(self, name: Any) -> Any:
        """DELETE /graphspaces/{name}."""
        return self.request("graph_space.delete", path_params={"name": name})


class SchemaTemplateAPI(RestResource):
    def list(self) -> Any:
        """GET /graphspaces/{graphspace}/schematemplates."""
        return self.request("schema_template.list")

    def get(self, name: Any) -> Any:
        """GET /graphspaces/{graphspace}/schematemplates/{name}."""
        return self.request("schema_template.get", path_params={"name": name})

    def create(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/schematemplates."""
        return self.request("schema_template.create", body=body)

    def delete(self, name: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/schematemplates/{name}."""
        return self.request("schema_template.delete", path_params={"name": name})

    def update(self, name: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/schematemplates/{name}."""
        return self.request("schema_template.update", path_params={"name": name}, body=body)


class AdamicAdarAPI(RestResource):
    def get(
        self,
        *,
        vertex: Any = None,
        other: Any = None,
        direction: Any = None,
        label: Any = None,
        max_degree: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/adamicadar."""
        return self.request(
            "adamic_adar.get",
            params={
                "vertex": vertex,
                "other": other,
                "direction": direction,
                "label": label,
                "max_degree": max_degree,
                "limit": limit,
            },
        )


class AllShortestPathsAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        target: Any = None,
        direction: Any = None,
        label: Any = None,
        max_depth: Any = None,
        max_degree: Any = None,
        skip_degree: Any = None,
        with_vertex: Any = None,
        with_edge: Any = None,
        capacity: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/allshortestpaths."""
        return self.request(
            "all_shortest_paths.get",
            params={
                "source": source,
                "target": target,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "skip_degree": skip_degree,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
                "capacity": capacity,
            },
        )


class CountAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/count."""
        return self.request("count.post", body=body)


class CrosspointsAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        target: Any = None,
        direction: Any = None,
        label: Any = None,
        max_depth: Any = None,
        max_degree: Any = None,
        capacity: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/crosspoints."""
        return self.request(
            "crosspoints.get",
            params={
                "source": source,
                "target": target,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
            },
        )


class CustomizedCrosspointsAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/customizedcrosspoints."""
        return self.request("customized_crosspoints.post", body=body)


class CustomizedPathsAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/customizedpaths."""
        return self.request("customized_paths.post", body=body)


class EdgeExistenceAPI(RestResource):
    def get(
        self, *, source: Any = None, target: Any = None, label: Any = None, sort_values: Any = None, limit: Any = None
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/edgeexist."""
        return self.request(
            "edge_existence.get",
            params={"source": source, "target": target, "label": label, "sort_values": sort_values, "limit": limit},
        )


class EdgesAPI(RestResource):
    def list(self, *, ids: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/edges."""
        return self.request("edges.list", params={"ids": ids})

    def shards(self, *, split_size: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/edges/shards."""
        return self.request("edges.shards", params={"split_size": split_size})

    def scan(self, *, start: Any = None, end: Any = None, page: Any = None, page_limit: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/edges/scan."""
        return self.request("edges.scan", params={"start": start, "end": end, "page": page, "page_limit": page_limit})


class FusiformSimilarityAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/fusiformsimilarity."""
        return self.request("fusiform_similarity.post", body=body)


class JaccardSimilarityAPI(RestResource):
    def get(
        self, *, vertex: Any = None, other: Any = None, direction: Any = None, label: Any = None, max_degree: Any = None
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/jaccardsimilarity."""
        return self.request(
            "jaccard_similarity.get",
            params={"vertex": vertex, "other": other, "direction": direction, "label": label, "max_degree": max_degree},
        )

    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/jaccardsimilarity."""
        return self.request("jaccard_similarity.post", body=body)


class KneighborAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        direction: Any = None,
        label: Any = None,
        max_depth: Any = None,
        count_only: Any = None,
        max_degree: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/kneighbor."""
        return self.request(
            "kneighbor.get",
            params={
                "source": source,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "count_only": count_only,
                "max_degree": max_degree,
                "limit": limit,
            },
        )

    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/kneighbor."""
        return self.request("kneighbor.post", body=body)


class KoutAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        direction: Any = None,
        label: Any = None,
        max_depth: Any = None,
        nearest: Any = None,
        count_only: Any = None,
        max_degree: Any = None,
        capacity: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/kout."""
        return self.request(
            "kout.get",
            params={
                "source": source,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "nearest": nearest,
                "count_only": count_only,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
            },
        )

    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/kout."""
        return self.request("kout.post", body=body)


class MultiNodeShortestPathAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/multinodeshortestpath."""
        return self.request("multi_node_shortest_path.post", body=body)


class NeighborRankAPI(RestResource):
    def neighbor_rank(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/neighborrank."""
        return self.request("neighbor_rank.neighbor_rank", body=body)


class PathsAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        target: Any = None,
        direction: Any = None,
        label: Any = None,
        max_depth: Any = None,
        max_degree: Any = None,
        capacity: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/paths."""
        return self.request(
            "paths.get",
            params={
                "source": source,
                "target": target,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
            },
        )

    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/paths."""
        return self.request("paths.post", body=body)


class PersonalRankAPI(RestResource):
    def personal_rank(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/personalrank."""
        return self.request("personal_rank.personal_rank", body=body)


class RaysAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        direction: Any = None,
        label: Any = None,
        max_depth: Any = None,
        max_degree: Any = None,
        capacity: Any = None,
        limit: Any = None,
        with_vertex: Any = None,
        with_edge: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/rays."""
        return self.request(
            "rays.get",
            params={
                "source": source,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
            },
        )


class ResourceAllocationAPI(RestResource):
    def create(
        self,
        *,
        vertex: Any = None,
        other: Any = None,
        direction: Any = None,
        label: Any = None,
        max_degree: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/resourceallocation."""
        return self.request(
            "resource_allocation.create",
            params={
                "vertex": vertex,
                "other": other,
                "direction": direction,
                "label": label,
                "max_degree": max_degree,
                "limit": limit,
            },
        )


class RingsAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        direction: Any = None,
        label: Any = None,
        max_depth: Any = None,
        source_in_ring: Any = None,
        max_degree: Any = None,
        capacity: Any = None,
        limit: Any = None,
        with_vertex: Any = None,
        with_edge: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/rings."""
        return self.request(
            "rings.get",
            params={
                "source": source,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "source_in_ring": source_in_ring,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
            },
        )


class SameNeighborsAPI(RestResource):
    def get(
        self,
        *,
        vertex: Any = None,
        other: Any = None,
        direction: Any = None,
        label: Any = None,
        max_degree: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/sameneighbors."""
        return self.request(
            "same_neighbors.get",
            params={
                "vertex": vertex,
                "other": other,
                "direction": direction,
                "label": label,
                "max_degree": max_degree,
                "limit": limit,
            },
        )

    def same_neighbors(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/sameneighbors."""
        return self.request("same_neighbors.same_neighbors", body=body)


class SameNeighborsBatchAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/sameneighborsbatch."""
        return self.request("same_neighbors_batch.post", body=body)


class ShortestPathAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        target: Any = None,
        direction: Any = None,
        label: Any = None,
        max_depth: Any = None,
        max_degree: Any = None,
        skip_degree: Any = None,
        with_vertex: Any = None,
        with_edge: Any = None,
        capacity: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/shortestpath."""
        return self.request(
            "shortest_path.get",
            params={
                "source": source,
                "target": target,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "skip_degree": skip_degree,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
                "capacity": capacity,
            },
        )


class SingleSourceShortestPathAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        direction: Any = None,
        label: Any = None,
        weight: Any = None,
        max_degree: Any = None,
        skip_degree: Any = None,
        with_vertex: Any = None,
        with_edge: Any = None,
        capacity: Any = None,
        limit: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/singlesourceshortestpath."""
        return self.request(
            "single_source_shortest_path.get",
            params={
                "source": source,
                "direction": direction,
                "label": label,
                "weight": weight,
                "max_degree": max_degree,
                "skip_degree": skip_degree,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
                "capacity": capacity,
                "limit": limit,
            },
        )


class TemplatePathsAPI(RestResource):
    def post(self, *, body: Any = None) -> Any:
        """POST /graphspaces/{graphspace}/graphs/{graph}/traversers/templatepaths."""
        return self.request("template_paths.post", body=body)


class VerticesAPI(RestResource):
    def list(self, *, ids: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/vertices."""
        return self.request("vertices.list", params={"ids": ids})

    def shards(self, *, split_size: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/vertices/shards."""
        return self.request("vertices.shards", params={"split_size": split_size})

    def scan(self, *, start: Any = None, end: Any = None, page: Any = None, page_limit: Any = None) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/vertices/scan."""
        return self.request(
            "vertices.scan", params={"start": start, "end": end, "page": page, "page_limit": page_limit}
        )


class WeightedShortestPathAPI(RestResource):
    def get(
        self,
        *,
        source: Any = None,
        target: Any = None,
        direction: Any = None,
        label: Any = None,
        weight: Any = None,
        max_degree: Any = None,
        skip_degree: Any = None,
        with_vertex: Any = None,
        with_edge: Any = None,
        capacity: Any = None,
    ) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/traversers/weightedshortestpath."""
        return self.request(
            "weighted_shortest_path.get",
            params={
                "source": source,
                "target": target,
                "direction": direction,
                "label": label,
                "weight": weight,
                "max_degree": max_degree,
                "skip_degree": skip_degree,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
                "capacity": capacity,
            },
        )


class VariablesAPI(RestResource):
    def update(self, key: Any, *, body: Any = None) -> Any:
        """PUT /graphspaces/{graphspace}/graphs/{graph}/variables/{key}."""
        return self.request("variables.update", path_params={"key": key}, body=body)

    def list(self) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/variables."""
        return self.request("variables.list")

    def get(self, key: Any) -> Any:
        """GET /graphspaces/{graphspace}/graphs/{graph}/variables/{key}."""
        return self.request("variables.get", path_params={"key": key})

    def delete(self, key: Any) -> Any:
        """DELETE /graphspaces/{graphspace}/graphs/{graph}/variables/{key}."""
        return self.request("variables.delete", path_params={"key": key})


class ExceptionTraceAPI(RestResource):
    def get(self) -> Any:
        """GET /exception/trace."""
        return self.request("exception_trace.get")

    def trace(self, *, body: Any = None) -> Any:
        """PUT /exception/trace."""
        return self.request("exception_trace.trace", body=body)


class RestManager(RestResource):
    """Complete REST surface; all child resources share the client session."""

    def __init__(self, session):
        super().__init__(session)
        self.arthas = ArthasAPI(session)
        self.access = AccessAPI(session)
        self.belong = BelongAPI(session)
        self.graph_space_group = GraphSpaceGroupAPI(session)
        self.group = GroupAPI(session)
        self.login = LoginAPI(session)
        self.manager = ManagerAPI(session)
        self.project = ProjectAPI(session)
        self.target = TargetAPI(session)
        self.user = UserAPI(session)
        self.cypher = CypherAPI(session)
        self.edge = EdgeAPI(session)
        self.vertex = VertexAPI(session)
        self.gremlin = GremlinAPI(session)
        self.algorithm = AlgorithmAPI(session)
        self.computer = ComputerAPI(session)
        self.gremlin_job = GremlinJobAPI(session)
        self.rebuild = RebuildAPI(session)
        self.task = TaskAPI(session)
        self.metrics = MetricsAPI(session)
        self.graphs = GraphsAPI(session)
        self.profile = ProfileAPI(session)
        self.version = VersionAPI(session)
        self.white_ip_list = WhiteIpListAPI(session)
        self.raft = RaftAPI(session)
        self.edge_label = EdgeLabelAPI(session)
        self.index_label = IndexLabelAPI(session)
        self.property_key = PropertyKeyAPI(session)
        self.schema = SchemaAPI(session)
        self.vertex_label = VertexLabelAPI(session)
        self.graph_space = GraphSpaceAPI(session)
        self.schema_template = SchemaTemplateAPI(session)
        self.adamic_adar = AdamicAdarAPI(session)
        self.all_shortest_paths = AllShortestPathsAPI(session)
        self.count = CountAPI(session)
        self.crosspoints = CrosspointsAPI(session)
        self.customized_crosspoints = CustomizedCrosspointsAPI(session)
        self.customized_paths = CustomizedPathsAPI(session)
        self.edge_existence = EdgeExistenceAPI(session)
        self.edges = EdgesAPI(session)
        self.fusiform_similarity = FusiformSimilarityAPI(session)
        self.jaccard_similarity = JaccardSimilarityAPI(session)
        self.kneighbor = KneighborAPI(session)
        self.kout = KoutAPI(session)
        self.multi_node_shortest_path = MultiNodeShortestPathAPI(session)
        self.neighbor_rank = NeighborRankAPI(session)
        self.paths = PathsAPI(session)
        self.personal_rank = PersonalRankAPI(session)
        self.rays = RaysAPI(session)
        self.resource_allocation = ResourceAllocationAPI(session)
        self.rings = RingsAPI(session)
        self.same_neighbors = SameNeighborsAPI(session)
        self.same_neighbors_batch = SameNeighborsBatchAPI(session)
        self.shortest_path = ShortestPathAPI(session)
        self.single_source_shortest_path = SingleSourceShortestPathAPI(session)
        self.template_paths = TemplatePathsAPI(session)
        self.vertices = VerticesAPI(session)
        self.weighted_shortest_path = WeightedShortestPathAPI(session)
        self.variables = VariablesAPI(session)
        self.exception_trace = ExceptionTraceAPI(session)
