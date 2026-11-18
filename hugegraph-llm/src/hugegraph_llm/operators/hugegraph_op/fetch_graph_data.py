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


from typing import Any, Dict, Optional

from pyhugegraph.client import PyHugeClient
from pyhugegraph.utils.id_format import JAVA_LONG_MAX, JAVA_LONG_MIN


class FetchGraphData:
    def __init__(self, graph: PyHugeClient):
        self.graph = graph

    def fetch_all_vertex_ids_with_status(self, page_size: int = 1000) -> tuple[list[Any], bool, str | None]:
        """Paginate through all vertex IDs and report whether the scan completed."""
        graph_api = self.graph.graph()
        vids: list[Any] = []
        page: Optional[str] = ""
        seen_pages: set[str] = set()
        while True:
            envelope = graph_api.list_vertices(limit=page_size, page=page)
            if not isinstance(envelope, dict):
                return vids, False, "invalid_page_envelope"
            vertices_page = envelope.get("vertices")
            if not isinstance(vertices_page, list):
                return vids, False, "invalid_vertices_page"
            for vertex in vertices_page:
                if not isinstance(vertex, dict) or "id" not in vertex:
                    return vids, False, "invalid_vertex_id"
                vid = vertex["id"]
                if not (
                    (type(vid) is int and JAVA_LONG_MIN <= vid <= JAVA_LONG_MAX)
                    or (isinstance(vid, str) and vid.strip())
                ):
                    return vids, False, "invalid_vertex_id"
                vids.append(vid)
            next_page = envelope.get("page")
            if next_page is None or next_page == "":
                return vids, True, None
            if not isinstance(next_page, str):
                return vids, False, "invalid_page_token"
            if next_page in seen_pages:
                return vids, False, "duplicate_page_token"
            seen_pages.add(next_page)
            page = next_page

    def fetch_all_vertex_ids(self, page_size: int = 1000) -> list[Any]:
        """Paginate through all vertex IDs without a fixed vertex cap."""
        vids, _complete, _reason = self.fetch_all_vertex_ids_with_status(page_size=page_size)
        return vids

    def run(self, graph_summary: Optional[Dict[str, Any]], *, fetch_all_vids: bool = False) -> Dict[str, Any]:
        if graph_summary is None:
            graph_summary = {}

        # TODO: v_limit will influence the vid embedding logic in build_semantic_index.py
        v_limit = 10000
        e_limit = 200
        keys = ["vertex_num", "edge_num", "vertices", "edges", "note"]

        if fetch_all_vids:
            vids, scan_complete, incomplete_reason = self.fetch_all_vertex_ids_with_status()
            graph_summary.update(
                {
                    "vertex_num": len(vids),
                    "vertices": vids,
                    "vid_scan_complete": scan_complete,
                    "vid_scan_incomplete_reason": incomplete_reason,
                    "note": f"Full paginated VID scan ({len(vids)} VIDs).",
                }
            )
            return graph_summary

        groovy_code = f"""
        def res = [:];
        res.{keys[0]} = g.V().count().next();
        res.{keys[1]} = g.E().count().next();
        res.{keys[2]} = g.V().id().limit({v_limit}).toList();
        res.{keys[3]} = g.E().id().limit({e_limit}).toList();
        res.{keys[4]} = "Only ≤{v_limit} VIDs and ≤ {e_limit} EIDs for brief overview .";
        return res;
        """

        response = self.graph.gremlin().exec(groovy_code)
        result = response.get("data") if isinstance(response, dict) else None
        if isinstance(result, list) and len(result) > 0:
            if len(result) == 1 and isinstance(result[0], dict):
                graph_summary.update({key: result[0].get(key) for key in keys})
            else:
                graph_summary.update(
                    {
                        key: result[i].get(key) if i < len(result) and isinstance(result[i], dict) else None
                        for i, key in enumerate(keys)
                    }
                )
            graph_summary["vid_scan_complete"] = False
            graph_summary["vid_scan_incomplete_reason"] = "overview_limit_applied"
        return graph_summary
