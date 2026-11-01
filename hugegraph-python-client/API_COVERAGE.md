# REST coverage

Server: `8e327b8f3d3ffcf61547be7fea1a15d3af2de8b4`

| Python REST entry | Method | Path | Query parameters |
| --- | --- | --- | --- |
| `rest.access.create()` | POST | `/graphspaces/{graphspace}/auth/accesses` | — |
| `rest.access.delete()` | DELETE | `/graphspaces/{graphspace}/auth/accesses/{id}` | — |
| `rest.access.get()` | GET | `/graphspaces/{graphspace}/auth/accesses/{id}` | — |
| `rest.access.list()` | GET | `/graphspaces/{graphspace}/auth/accesses` | group, target, limit |
| `rest.access.update()` | PUT | `/graphspaces/{graphspace}/auth/accesses/{id}` | — |
| `rest.adamic_adar.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/adamicadar` | vertex, other, direction, label, max_degree, limit |
| `rest.algorithm.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/jobs/algorithm/{name}` | — |
| `rest.all_shortest_paths.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/allshortestpaths` | source, target, direction, label, max_depth, max_degree, skip_degree, with_vertex, with_edge, capacity |
| `rest.arthas.start_arthas()` | PUT | `/arthas` | — |
| `rest.belong.create()` | POST | `/graphspaces/{graphspace}/auth/belongs` | — |
| `rest.belong.delete()` | DELETE | `/graphspaces/{graphspace}/auth/belongs/{id}` | — |
| `rest.belong.get()` | GET | `/graphspaces/{graphspace}/auth/belongs/{id}` | — |
| `rest.belong.list()` | GET | `/graphspaces/{graphspace}/auth/belongs` | user, group, limit |
| `rest.belong.update()` | PUT | `/graphspaces/{graphspace}/auth/belongs/{id}` | — |
| `rest.computer.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/jobs/computer/{name}` | — |
| `rest.count.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/count` | — |
| `rest.crosspoints.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/crosspoints` | source, target, direction, label, max_depth, max_degree, capacity, limit |
| `rest.customized_crosspoints.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/customizedcrosspoints` | — |
| `rest.customized_paths.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/customizedpaths` | — |
| `rest.cypher.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/cypher` | — |
| `rest.cypher.query()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/cypher` | cypher |
| `rest.edge.create()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/graph/edges` | — |
| `rest.edge.create_batch()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/graph/edges/batch` | check_vertex |
| `rest.edge.delete()` | DELETE | `/graphspaces/{graphspace}/graphs/{graph}/graph/edges/{id}` | label |
| `rest.edge.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/graph/edges/{id}` | — |
| `rest.edge.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/graph/edges` | vertex_id, direction, label, properties, keep_start_p, offset, page, limit |
| `rest.edge.update_batch()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/graph/edges/batch` | — |
| `rest.edge.update_by_id()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/graph/edges/{id}` | action |
| `rest.edge_existence.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/edgeexist` | source, target, label, sort_values, limit |
| `rest.edge_label.create()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels` | — |
| `rest.edge_label.delete()` | DELETE | `/graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels/{name}` | — |
| `rest.edge_label.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels/{name}` | — |
| `rest.edge_label.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels` | names |
| `rest.edge_label.update()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/schema/edgelabels/{name}` | action |
| `rest.edges.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/edges` | ids |
| `rest.edges.scan()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/edges/scan` | start, end, page, page_limit |
| `rest.edges.shards()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/edges/shards` | split_size |
| `rest.exception_trace.get()` | GET | `/exception/trace` | — |
| `rest.exception_trace.trace()` | PUT | `/exception/trace` | — |
| `rest.fusiform_similarity.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/fusiformsimilarity` | — |
| `rest.graph_space.check_default_role()` | GET | `/graphspaces/{graphspace}/role` | user, role, graph |
| `rest.graph_space.create()` | POST | `/graphspaces` | — |
| `rest.graph_space.delete()` | DELETE | `/graphspaces/{name}` | — |
| `rest.graph_space.delete_default_role()` | DELETE | `/graphspaces/{graphspace}/role` | user, role, graph |
| `rest.graph_space.get()` | GET | `/graphspaces/{graphspace}` | — |
| `rest.graph_space.list()` | GET | `/graphspaces` | — |
| `rest.graph_space.list_profile()` | GET | `/graphspaces/profile` | prefix |
| `rest.graph_space.manage()` | PUT | `/graphspaces/{name}` | — |
| `rest.graph_space.set_default_role()` | POST | `/graphspaces/{graphspace}/role` | — |
| `rest.graph_space_group.create()` | POST | `/graphspaces/{graphspace}/auth/groups` | — |
| `rest.graph_space_group.delete()` | DELETE | `/graphspaces/{graphspace}/auth/groups/{id}` | — |
| `rest.graph_space_group.get()` | GET | `/graphspaces/{graphspace}/auth/groups/{id}` | — |
| `rest.graph_space_group.list()` | GET | `/graphspaces/{graphspace}/auth/groups` | limit |
| `rest.graph_space_group.update()` | PUT | `/graphspaces/{graphspace}/auth/groups/{id}` | — |
| `rest.graphs.clear()` | DELETE | `/graphspaces/{graphspace}/graphs/{name}/clear` | confirm_message |
| `rest.graphs.clone_schema()` | POST | `/graphspaces/{graphspace}/graphs/{name}/schema-clone` | source |
| `rest.graphs.compact()` | PUT | `/graphspaces/{graphspace}/graphs/{name}/compact` | — |
| `rest.graphs.create()` | POST | `/graphspaces/{graphspace}/graphs/{name}` | clone_graph_name |
| `rest.graphs.create_by_text()` | POST | `/graphspaces/{graphspace}/graphs/{name}` | clone_graph_name |
| `rest.graphs.create_snapshot()` | PUT | `/graphspaces/{graphspace}/graphs/{name}/snapshot_create` | — |
| `rest.graphs.drop()` | DELETE | `/graphspaces/{graphspace}/graphs/{name}` | confirm_message |
| `rest.graphs.get()` | GET | `/graphspaces/{graphspace}/graphs/{name}` | — |
| `rest.graphs.get_conf()` | GET | `/graphspaces/{graphspace}/graphs/{name}/conf` | — |
| `rest.graphs.get_default()` | GET | `/graphspaces/{graphspace}/graphs/default` | — |
| `rest.graphs.graph_read_mode_get()` | GET | `/graphspaces/{graphspace}/graphs/{name}/graph_read_mode` | — |
| `rest.graphs.graph_read_mode_set()` | PUT | `/graphspaces/{graphspace}/graphs/{name}/graph_read_mode` | — |
| `rest.graphs.list()` | GET | `/graphspaces/{graphspace}/graphs` | — |
| `rest.graphs.list_profile()` | GET | `/graphspaces/{graphspace}/graphs/profile` | prefix |
| `rest.graphs.loading_mode_get()` | GET | `/graphspaces/{graphspace}/graphs/{name}/mode/owners` | — |
| `rest.graphs.loading_mode_set()` | PUT | `/graphspaces/{graphspace}/graphs/{name}/mode/owners` | — |
| `rest.graphs.manage()` | PUT | `/graphspaces/{graphspace}/graphs/{name}` | — |
| `rest.graphs.mode_get()` | GET | `/graphspaces/{graphspace}/graphs/{name}/mode` | — |
| `rest.graphs.mode_set()` | PUT | `/graphspaces/{graphspace}/graphs/{name}/mode` | — |
| `rest.graphs.reload()` | PUT | `/graphspaces/{graphspace}/graphs/manage` | — |
| `rest.graphs.resume_snapshot()` | PUT | `/graphspaces/{graphspace}/graphs/{name}/snapshot_resume` | — |
| `rest.graphs.set_default()` | POST | `/graphspaces/{graphspace}/graphs/{name}/default` | — |
| `rest.graphs.unset_default()` | DELETE | `/graphspaces/{graphspace}/graphs/{name}/default` | — |
| `rest.gremlin.get()` | GET | `/gremlin` | — |
| `rest.gremlin.post()` | POST | `/gremlin` | — |
| `rest.gremlin_job.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/jobs/gremlin` | — |
| `rest.group.create()` | POST | `/auth/groups` | — |
| `rest.group.delete()` | DELETE | `/auth/groups/{id}` | — |
| `rest.group.get()` | GET | `/auth/groups/{id}` | — |
| `rest.group.list()` | GET | `/auth/groups` | limit |
| `rest.group.update()` | PUT | `/auth/groups/{id}` | — |
| `rest.index_label.create()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels` | — |
| `rest.index_label.delete()` | DELETE | `/graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels/{name}` | — |
| `rest.index_label.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels/{name}` | — |
| `rest.index_label.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels` | names |
| `rest.index_label.update()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/schema/indexlabels/{name}` | action |
| `rest.jaccard_similarity.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/jaccardsimilarity` | vertex, other, direction, label, max_degree |
| `rest.jaccard_similarity.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/jaccardsimilarity` | — |
| `rest.kneighbor.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/kneighbor` | source, direction, label, max_depth, count_only, max_degree, limit |
| `rest.kneighbor.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/kneighbor` | — |
| `rest.kout.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/kout` | source, direction, label, max_depth, nearest, count_only, max_degree, capacity, limit |
| `rest.kout.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/kout` | — |
| `rest.login.login()` | POST | `/auth/login` | — |
| `rest.login.logout()` | DELETE | `/auth/logout` | — |
| `rest.login.verify_token()` | GET | `/auth/verify` | — |
| `rest.manager.check_default_role()` | GET | `/graphspaces/{graphspace}/auth/managers/default` | role, graph |
| `rest.manager.check_role()` | GET | `/graphspaces/{graphspace}/auth/managers/check` | type |
| `rest.manager.create_manager()` | POST | `/graphspaces/{graphspace}/auth/managers` | — |
| `rest.manager.delete()` | DELETE | `/graphspaces/{graphspace}/auth/managers` | user, type |
| `rest.manager.get_roles_in_gs()` | GET | `/graphspaces/{graphspace}/auth/managers/role` | user |
| `rest.manager.list()` | GET | `/graphspaces/{graphspace}/auth/managers` | type |
| `rest.metrics.all()` | GET | `/metrics` | type |
| `rest.metrics.backend()` | GET | `/metrics/backend` | — |
| `rest.metrics.counters()` | GET | `/metrics/counters` | — |
| `rest.metrics.gauges()` | GET | `/metrics/gauges` | — |
| `rest.metrics.histograms()` | GET | `/metrics/histograms` | — |
| `rest.metrics.meters()` | GET | `/metrics/meters` | — |
| `rest.metrics.statistics()` | GET | `/metrics/statistics` | type |
| `rest.metrics.system()` | GET | `/metrics/system` | — |
| `rest.metrics.timers()` | GET | `/metrics/timers` | — |
| `rest.multi_node_shortest_path.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/multinodeshortestpath` | — |
| `rest.neighbor_rank.neighbor_rank()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/neighborrank` | — |
| `rest.paths.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/paths` | source, target, direction, label, max_depth, max_degree, capacity, limit |
| `rest.paths.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/paths` | — |
| `rest.personal_rank.personal_rank()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/personalrank` | — |
| `rest.profile.get_profile()` | GET | `/` | — |
| `rest.profile.show_all_ap_is()` | GET | `/apis` | — |
| `rest.project.create()` | POST | `/graphspaces/{graphspace}/auth/projects` | — |
| `rest.project.delete()` | DELETE | `/graphspaces/{graphspace}/auth/projects/{id}` | — |
| `rest.project.get()` | GET | `/graphspaces/{graphspace}/auth/projects/{id}` | — |
| `rest.project.list()` | GET | `/graphspaces/{graphspace}/auth/projects` | limit |
| `rest.project.update()` | PUT | `/graphspaces/{graphspace}/auth/projects/{id}` | action |
| `rest.property_key.create()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys` | — |
| `rest.property_key.delete()` | DELETE | `/graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys/{name}` | — |
| `rest.property_key.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys/{name}` | — |
| `rest.property_key.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys` | names |
| `rest.property_key.update()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/schema/propertykeys/{name}` | action |
| `rest.raft.add_peer()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/raft/add_peer` | group, endpoint |
| `rest.raft.get_leader()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/raft/get_leader` | group |
| `rest.raft.list_peers()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/raft/list_peers` | group |
| `rest.raft.remove_peer()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/raft/remove_peer` | group, endpoint |
| `rest.raft.set_leader()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/raft/set_leader` | group, endpoint |
| `rest.raft.transfer_leader()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/raft/transfer_leader` | group, endpoint |
| `rest.rays.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/rays` | source, direction, label, max_depth, max_degree, capacity, limit, with_vertex, with_edge |
| `rest.rebuild.edge_label_rebuild()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/jobs/rebuild/edgelabels/{name}` | — |
| `rest.rebuild.index_label_rebuild()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/jobs/rebuild/indexlabels/{name}` | — |
| `rest.rebuild.vertex_label_rebuild()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/jobs/rebuild/vertexlabels/{name}` | — |
| `rest.resource_allocation.create()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/resourceallocation` | vertex, other, direction, label, max_degree, limit |
| `rest.rings.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/rings` | source, direction, label, max_depth, source_in_ring, max_degree, capacity, limit, with_vertex, with_edge |
| `rest.same_neighbors.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/sameneighbors` | vertex, other, direction, label, max_degree, limit |
| `rest.same_neighbors.same_neighbors()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/sameneighbors` | — |
| `rest.same_neighbors_batch.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/sameneighborsbatch` | — |
| `rest.schema.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema` | — |
| `rest.schema_template.create()` | POST | `/graphspaces/{graphspace}/schematemplates` | — |
| `rest.schema_template.delete()` | DELETE | `/graphspaces/{graphspace}/schematemplates/{name}` | — |
| `rest.schema_template.get()` | GET | `/graphspaces/{graphspace}/schematemplates/{name}` | — |
| `rest.schema_template.list()` | GET | `/graphspaces/{graphspace}/schematemplates` | — |
| `rest.schema_template.update()` | PUT | `/graphspaces/{graphspace}/schematemplates/{name}` | — |
| `rest.shortest_path.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/shortestpath` | source, target, direction, label, max_depth, max_degree, skip_degree, with_vertex, with_edge, capacity |
| `rest.single_source_shortest_path.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/singlesourceshortestpath` | source, direction, label, weight, max_degree, skip_degree, with_vertex, with_edge, capacity, limit |
| `rest.target.create()` | POST | `/graphspaces/{graphspace}/auth/targets` | — |
| `rest.target.delete()` | DELETE | `/graphspaces/{graphspace}/auth/targets/{id}` | — |
| `rest.target.get()` | GET | `/graphspaces/{graphspace}/auth/targets/{id}` | — |
| `rest.target.list()` | GET | `/graphspaces/{graphspace}/auth/targets` | limit |
| `rest.target.update()` | PUT | `/graphspaces/{graphspace}/auth/targets/{id}` | — |
| `rest.task.delete()` | DELETE | `/graphspaces/{graphspace}/graphs/{graph}/tasks/{id}` | force |
| `rest.task.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/tasks/{id}` | with_result |
| `rest.task.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/tasks` | status, ids, limit, page |
| `rest.task.update()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/tasks/{id}` | action |
| `rest.template_paths.post()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/traversers/templatepaths` | — |
| `rest.user.create()` | POST | `/graphspaces/{graphspace}/auth/users` | — |
| `rest.user.delete()` | DELETE | `/graphspaces/{graphspace}/auth/users/{id}` | — |
| `rest.user.get()` | GET | `/graphspaces/{graphspace}/auth/users/{id}` | — |
| `rest.user.list()` | GET | `/graphspaces/{graphspace}/auth/users` | name, limit |
| `rest.user.role()` | GET | `/graphspaces/{graphspace}/auth/users/{id}/role` | — |
| `rest.user.update()` | PUT | `/graphspaces/{graphspace}/auth/users/{id}` | — |
| `rest.variables.delete()` | DELETE | `/graphspaces/{graphspace}/graphs/{graph}/variables/{key}` | — |
| `rest.variables.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/variables/{key}` | — |
| `rest.variables.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/variables` | — |
| `rest.variables.update()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/variables/{key}` | — |
| `rest.version.list()` | GET | `/versions` | — |
| `rest.vertex.create()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/graph/vertices` | — |
| `rest.vertex.create_batch()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/graph/vertices/batch` | — |
| `rest.vertex.delete()` | DELETE | `/graphspaces/{graphspace}/graphs/{graph}/graph/vertices/{id}` | label |
| `rest.vertex.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/graph/vertices/{id}` | — |
| `rest.vertex.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/graph/vertices` | label, properties, keep_start_p, offset, page, limit |
| `rest.vertex.update_batch()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/graph/vertices/batch` | — |
| `rest.vertex.update_by_id()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/graph/vertices/{id}` | action |
| `rest.vertex_label.create()` | POST | `/graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels` | — |
| `rest.vertex_label.delete()` | DELETE | `/graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels/{name}` | — |
| `rest.vertex_label.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels/{name}` | — |
| `rest.vertex_label.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels` | names |
| `rest.vertex_label.update()` | PUT | `/graphspaces/{graphspace}/graphs/{graph}/schema/vertexlabels/{name}` | action |
| `rest.vertices.list()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/vertices` | ids |
| `rest.vertices.scan()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/vertices/scan` | start, end, page, page_limit |
| `rest.vertices.shards()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/vertices/shards` | split_size |
| `rest.weighted_shortest_path.get()` | GET | `/graphspaces/{graphspace}/graphs/{graph}/traversers/weightedshortestpath` | source, target, direction, label, weight, max_degree, skip_degree, with_vertex, with_edge, capacity |
| `rest.white_ip_list.list()` | GET | `/whiteiplist` | — |
| `rest.white_ip_list.update_status()` | PUT | `/whiteiplist` | status |
| `rest.white_ip_list.update_white_i_ps()` | POST | `/whiteiplist` | — |
