#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from pyhugegraph.client import PyHugeClient

from hugegraph_llm.config import huge_settings, prompt
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.operator_list import OperatorList
from hugegraph_llm.utils.log import log

# TODO: remove 'as('subj)' step
VERTEX_QUERY_TPL = "g.V({keywords}).limit(8).as('subj').toList()"

# TODO: we could use a simpler query (like kneighbor-api to get the edges)
# TODO: test with profile()/explain() to speed up the query
VID_QUERY_NEIGHBOR_TPL = """\
g.V({keywords})
.repeat(
   bothE({edge_labels}).limit({edge_limit}).otherV().dedup()
).times({max_deep}).emit()
.simplePath()
.path()
.by(project('label', 'id', 'props')
   .by(label())
   .by(id())
   .by(valueMap().by(unfold()))
)
.by(project('label', 'inV', 'outV', 'props')
   .by(label())
   .by(inV().id())
   .by(outV().id())
   .by(valueMap().by(unfold()))
)
.limit({max_items})
.toList()
"""

PROPERTY_QUERY_NEIGHBOR_TPL = """\
g.V().has('{prop}', within({keywords}))
.repeat(
   bothE({edge_labels}).limit({edge_limit}).otherV().dedup()
).times({max_deep}).emit()
.simplePath()
.path()
.by(project('label', 'props')
   .by(label())
   .by(valueMap().by(unfold()))
)
.by(project('label', 'inV', 'outV', 'props')
   .by(label())
   .by(inV().values('{prop}'))
   .by(outV().values('{prop}'))
   .by(valueMap().by(unfold()))
)
.limit({max_items})
.toList()
"""


class GraphQueryNode(BaseNode):
    """
    Graph query node, responsible for retrieving relevant information from the graph database.
    """

    _client: Optional[PyHugeClient] = None
    _max_deep: Optional[int] = None
    _max_items: Optional[int] = None
    _prop_to_match: Optional[str] = None
    _num_gremlin_generate_example: int = -1
    gremlin_prompt: str = ""
    _limit_property: bool = False
    _max_v_prop_len: int = 2048
    _max_e_prop_len: int = 256
    _schema: str = ""
    operator_list: Optional[OperatorList] = None

    def node_init(self):
        """
        Initialize the graph query operator.
        """
        self._client: PyHugeClient = PyHugeClient(
            url=huge_settings.graph_url,
            graph=huge_settings.graph_name,
            user=huge_settings.graph_user,
            pwd=huge_settings.graph_pwd,
            graphspace=huge_settings.graph_space,
        )
        self._max_deep = self.wk_input.max_deep or 2
        self._max_items = self.wk_input.max_graph_items or huge_settings.max_graph_items
        self._prop_to_match = self.wk_input.prop_to_match
        self._num_gremlin_generate_example = (
            self.wk_input.gremlin_tmpl_num if self.wk_input.gremlin_tmpl_num is not None else -1
        )
        self.gremlin_prompt = self.wk_input.gremlin_prompt or prompt.gremlin_generate_prompt
        self._limit_property = huge_settings.limit_property.lower() == "true"
        self._max_v_prop_len = self.wk_input.max_v_prop_len or 2048
        self._max_e_prop_len = self.wk_input.max_e_prop_len or 256
        self._schema = ""
        self.operator_list = OperatorList(None, None)

        return super().node_init()

    # TODO: move this method to a util file for reuse (remove self param)
    def init_client(self, context):
        """Initialize the HugeGraph client from context or default settings."""
        # pylint: disable=R0915 (too-many-statements)
        if self._client is None:
            if isinstance(context.get("graph_client"), PyHugeClient):
                self._client = context["graph_client"]
            else:
                url = context.get("url") or "http://localhost:8080"
                graph = context.get("graph") or "hugegraph"
                user = context.get("user") or "admin"
                pwd = context.get("pwd") or "admin"
                gs = context.get("graphspace") or None
                self._client = PyHugeClient(url, graph, user, pwd, gs)
        assert self._client is not None, "No valid graph to search."

    def _gremlin_generate_query(self, context: Dict[str, Any]) -> Dict[str, Any]:
        query = context["query"]
        vertices = context.get("match_vids")
        query_embedding = context.get("query_embedding")

        self.operator_list.clear()
        self.operator_list.example_index_query(num_examples=self._num_gremlin_generate_example)
        gremlin_response = self.operator_list.gremlin_generate_synthesize(
            context["simple_schema"],
            vertices=vertices,
            gremlin_prompt=self.gremlin_prompt,
        ).run(query=query, query_embedding=query_embedding)
        if self._num_gremlin_generate_example > 0:
            gremlin = gremlin_response["result"]
        else:
            gremlin = gremlin_response["raw_result"]
        log.info("Generated gremlin: %s", gremlin)
        context["gremlin"] = gremlin
        try:
            result = self._client.gremlin().exec(gremlin=gremlin)["data"]
            if result == [None]:
                result = []
            context["graph_result"] = [json.dumps(item, ensure_ascii=False) for item in result]
            if context["graph_result"]:
                context["graph_result_flag"] = 1
                context["graph_context_head"] = (
                    f"The following are graph query result from gremlin query `{gremlin}`.\n"
                )
        except Exception as e:  # pylint: disable=broad-except,broad-exception-caught
            log.error(e)
            context["graph_result"] = []
        return context

    def _limit_property_query(self, value: Optional[str], item_type: str) -> Optional[str]:
        # NOTE: we skip the filter for list/set type (e.g., list of string, add it if needed)
        if not self._limit_property or not isinstance(value, str):
            return value

        max_len = self._max_v_prop_len if item_type == "v" else self._max_e_prop_len
        return value[:max_len] if value else value

    def _process_vertex(
        self,
        item: Any,
        flat_rel: str,
        node_cache: Set[str],
        prior_edge_str_len: int,
        depth: int,
        nodes_with_degree: List[str],
        use_id_to_match: bool,
        v_cache: Set[str],
    ) -> Tuple[str, int, int]:
        matched_str = item["id"] if use_id_to_match else item["props"][self._prop_to_match]
        if matched_str in node_cache:
            flat_rel = flat_rel[:-prior_edge_str_len]
            return flat_rel, prior_edge_str_len, depth

        node_cache.add(matched_str)
        props_str = ", ".join(f"{k}: {self._limit_property_query(v, 'v')}" for k, v in item["props"].items() if v)

        # TODO: we may remove label id or replace with label name
        if matched_str in v_cache:
            node_str = matched_str
        else:
            v_cache.add(matched_str)
            node_str = f"{item['id']}{{{props_str}}}"

        flat_rel += node_str
        nodes_with_degree.append(node_str)
        depth += 1
        return flat_rel, prior_edge_str_len, depth

    def _process_edge(
        self,
        item: Any,
        path_str: str,
        raw_flat_rel: List[Any],
        i: int,
        use_id_to_match: bool,
        e_cache: Set[Tuple[str, str, str]],
    ) -> Tuple[str, int]:
        props_str = ", ".join(f"{k}: {self._limit_property_query(v, 'e')}" for k, v in item["props"].items() if v)
        props_str = f"{{{props_str}}}" if props_str else ""
        prev_matched_str = (
            raw_flat_rel[i - 1]["id"] if use_id_to_match else (raw_flat_rel)[i - 1]["props"][self._prop_to_match]
        )

        edge_key = (item["inV"], item["label"], item["outV"])
        if edge_key not in e_cache:
            e_cache.add(edge_key)
            edge_label = f"{item['label']}{props_str}"
        else:
            edge_label = item["label"]

        edge_str = f"--[{edge_label}]-->" if item["outV"] == prev_matched_str else f"<--[{edge_label}]--"
        path_str += edge_str
        prior_edge_str_len = len(edge_str)
        return path_str, prior_edge_str_len

    def _process_path(
        self,
        path: Any,
        use_id_to_match: bool,
        v_cache: Set[str],
        e_cache: Set[Tuple[str, str, str]],
    ) -> Tuple[str, List[str]]:
        flat_rel = ""
        raw_flat_rel = path["objects"]
        assert len(raw_flat_rel) % 2 == 1, "The length of raw_flat_rel should be odd."

        node_cache = set()
        prior_edge_str_len = 0
        depth = 0
        nodes_with_degree = []

        for i, item in enumerate(raw_flat_rel):
            if i % 2 == 0:
                # Process each vertex
                flat_rel, prior_edge_str_len, depth = self._process_vertex(
                    item,
                    flat_rel,
                    node_cache,
                    prior_edge_str_len,
                    depth,
                    nodes_with_degree,
                    use_id_to_match,
                    v_cache,
                )
            else:
                # Process each edge
                flat_rel, prior_edge_str_len = self._process_edge(
                    item, flat_rel, raw_flat_rel, i, use_id_to_match, e_cache
                )

        return flat_rel, nodes_with_degree

    def _update_vertex_degree_list(self, vertex_degree_list: List[Set[str]], nodes_with_degree: List[str]) -> None:
        for depth, node_str in enumerate(nodes_with_degree):
            if depth >= len(vertex_degree_list):
                vertex_degree_list.append(set())
            vertex_degree_list[depth].add(node_str)

    def _format_graph_query_result(self, query_paths) -> Tuple[Set[str], List[Set[str]], Dict[str, List[str]]]:
        use_id_to_match = self._prop_to_match is None
        subgraph = set()
        subgraph_with_degree = {}
        vertex_degree_list: List[Set[str]] = []
        v_cache: Set[str] = set()
        e_cache: Set[Tuple[str, str, str]] = set()

        for path in query_paths:
            # 1. Process each path
            path_str, vertex_with_degree = self._process_path(path, use_id_to_match, v_cache, e_cache)
            subgraph.add(path_str)
            subgraph_with_degree[path_str] = vertex_with_degree
            # 2. Update vertex degree list
            self._update_vertex_degree_list(vertex_degree_list, vertex_with_degree)

        return subgraph, vertex_degree_list, subgraph_with_degree

    def _get_graph_schema(self, refresh: bool = False) -> str:
        if self._schema and not refresh:
            return self._schema

        schema = self._client.schema()
        vertex_schema = schema.getVertexLabels()
        edge_schema = schema.getEdgeLabels()
        relationships = schema.getRelations()

        self._schema = (
            f"Vertex properties: {vertex_schema}\nEdge properties: {edge_schema}\nRelationships: {relationships}\n"
        )
        log.debug("Link(Relation): %s", relationships)
        return self._schema

    @staticmethod
    def _extract_label_names(source: str, head: str = "name: ", tail: str = ", ") -> List[str]:
        result = []
        for s in source.split(head):
            end = s.find(tail)
            label = s[:end]
            if label:
                result.append(label)
        return result

    def _extract_labels_from_schema(self) -> Tuple[List[str], List[str]]:
        schema = self._get_graph_schema()
        vertex_props_str, edge_props_str = schema.split("\n")[:2]
        # TODO: rename to vertex (also need update in the schema)
        vertex_props_str = vertex_props_str[len("Vertex properties: ") :].strip("[").strip("]")
        edge_props_str = edge_props_str[len("Edge properties: ") :].strip("[").strip("]")
        vertex_labels = self._extract_label_names(vertex_props_str)
        edge_labels = self._extract_label_names(edge_props_str)
        return vertex_labels, edge_labels

    def _format_graph_from_vertex(self, query_result: List[Any]) -> Set[str]:
        knowledge = set()
        for item in query_result:
            props_str = ", ".join(f"{k}: {v}" for k, v in item["properties"].items())
            node_str = f"{item['id']}{{{props_str}}}"
            knowledge.add(node_str)
        return knowledge

    def _subgraph_query(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Extract params from context
        matched_vids = context.get("match_vids")
        if isinstance(context.get("max_deep"), int):
            self._max_deep = context["max_deep"]
        if isinstance(context.get("max_items"), int):
            self._max_items = context["max_items"]
        if isinstance(context.get("prop_to_match"), str):
            self._prop_to_match = context["prop_to_match"]

        # 2. Extract edge_labels from graph schema
        _, edge_labels = self._extract_labels_from_schema()
        edge_labels_str = ",".join("'" + label + "'" for label in edge_labels)
        # TODO: enhance the limit logic later
        edge_limit_amount = len(edge_labels) * huge_settings.edge_limit_pre_label

        use_id_to_match = self._prop_to_match is None
        if use_id_to_match:
            if not matched_vids:
                return context

            gremlin_query = VERTEX_QUERY_TPL.format(keywords=matched_vids)
            vertexes = self._client.gremlin().exec(gremlin=gremlin_query)["data"]
            log.debug("Vids gremlin query: %s", gremlin_query)

            vertex_knowledge = self._format_graph_from_vertex(query_result=vertexes)
            paths: List[Any] = []
            # TODO: use generator or asyncio to speed up the query logic
            for matched_vid in matched_vids:
                gremlin_query = VID_QUERY_NEIGHBOR_TPL.format(
                    keywords=f"'{matched_vid}'",
                    max_deep=self._max_deep,
                    edge_labels=edge_labels_str,
                    edge_limit=edge_limit_amount,
                    max_items=self._max_items,
                )
                log.debug("Kneighbor gremlin query: %s", gremlin_query)
                paths.extend(self._client.gremlin().exec(gremlin=gremlin_query)["data"])

            (
                graph_chain_knowledge,
                vertex_degree_list,
                knowledge_with_degree,
            ) = self._format_graph_query_result(query_paths=paths)

            # TODO: we may need to optimize the logic here with global deduplication (may lack some single vertex)
            if not graph_chain_knowledge:
                graph_chain_knowledge.update(vertex_knowledge)
            if vertex_degree_list:
                vertex_degree_list[0].update(vertex_knowledge)
            else:
                vertex_degree_list.append(vertex_knowledge)
        else:
            # WARN: When will the query enter here?
            keywords = context.get("keywords")
            assert keywords, "No related property(keywords) for graph query."
            keywords_str = ",".join("'" + kw + "'" for kw in keywords)
            gremlin_query = PROPERTY_QUERY_NEIGHBOR_TPL.format(
                prop=self._prop_to_match,
                keywords=keywords_str,
                edge_labels=edge_labels_str,
                edge_limit=edge_limit_amount,
                max_deep=self._max_deep,
                max_items=self._max_items,
            )
            log.warning("Unable to find vid, downgraded to property query, please confirm if it meets expectation.")

            paths: List[Any] = self._client.gremlin().exec(gremlin=gremlin_query)["data"]
            (
                graph_chain_knowledge,
                vertex_degree_list,
                knowledge_with_degree,
            ) = self._format_graph_query_result(query_paths=paths)

        context["graph_result"] = list(graph_chain_knowledge)
        if context["graph_result"]:
            context["graph_result_flag"] = 0
            context["vertex_degree_list"] = [list(vertex_degree) for vertex_degree in vertex_degree_list]
            context["knowledge_with_degree"] = knowledge_with_degree
            context["graph_context_head"] = (
                f"The following are graph knowledge in {self._max_deep} depth, e.g:\n"
                "`vertexA--[links]-->vertexB<--[links]--vertexC ...`"
                "extracted based on key entities as subject:\n"
            )
        return context

    def operator_schedule(self, data_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the graph query operation.
        """
        try:
            # Get the query text from input
            query = data_json.get("query", "")

            if not query:
                log.warning("No query text provided for graph query")
                return data_json

            # Execute the graph query (assuming schema and semantic query have been completed in previous nodes)
            self.init_client(data_json)

            # initial flag: -1 means no result, 0 means subgraph query, 1 means gremlin query
            data_json["graph_result_flag"] = -1
            # 1. Try to perform a query based on the generated gremlin
            if self._num_gremlin_generate_example >= 0:
                data_json = self._gremlin_generate_query(data_json)
            # 2. Try to perform a query based on subgraph-search if the previous query failed
            if not data_json.get("graph_result"):
                data_json = self._subgraph_query(data_json)

            if data_json.get("graph_result"):
                log.debug("Knowledge from Graph:\n%s", "\n".join(data_json["graph_result"]))
            else:
                log.debug("No Knowledge Extracted from Graph")

            log.info(
                "Graph query completed, found %d results",
                len(data_json.get("graph_result", [])),
            )

            return data_json

        except Exception as e:  # pylint: disable=broad-except,broad-exception-caught
            log.error("Graph query failed: %s", e)
            return data_json
