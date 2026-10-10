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


from typing import Optional

from pyhugegraph.client import PyHugeClient

from hugegraph_llm.config import huge_settings


class GraphIndex:
    def __init__(
        self,
        graph_url: Optional[str] = huge_settings.graph_url,
        graph_name: Optional[str] = huge_settings.graph_name,
        graph_user: Optional[str] = huge_settings.graph_user,
        graph_pwd: Optional[str] = huge_settings.graph_pwd,
        graph_space: Optional[str] = huge_settings.graph_space,
    ):
        self.client = PyHugeClient(
            url=graph_url, graph=graph_name, user=graph_user, pwd=graph_pwd, graphspace=graph_space
        )

    def clear_graph(self):
        self.client.gremlin().exec("g.V().drop()")

    # TODO: replace triples with a more specific graph element type & implement it
    def add_triples(self, triples: list):
        pass

    # TODO: replace triples with a more specific graph element type & implement it
    def search_triples(self, max_deep: int = 2):
        pass

    def execute_gremlin_query(self, query: str):
        return self.client.gremlin().exec(query)
