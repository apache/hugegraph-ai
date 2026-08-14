# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from hugegraph_mcp.tools.query_graph_data import _execute_vertex_query


class _PagedConditionManager:
    def getVertexByConditionWithPage(self, *, label, limit, page, properties):
        return [{"id": "v1"}], "next"


def test_vertex_condition_query_supports_paged_only_manager():
    items, next_page = _execute_vertex_query(
        manager=_PagedConditionManager(),
        operation="get_by_condition",
        id=None,
        ids=[],
        label="person",
        properties={"name": "Ada"},
        limit=10,
        page=None,
    )

    assert items == [{"id": "v1"}]
    assert next_page == "next"
