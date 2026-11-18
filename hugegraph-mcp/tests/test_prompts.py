# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from hugegraph_mcp.prompts import render_optimize_gremlin_query_prompt


def test_optimize_gremlin_query_prompt_does_not_require_disabled_gremlin_read_tool(monkeypatch):
    for profile in ("compat", "lean"):
        monkeypatch.setenv("HUGEGRAPH_MCP_CORE_PROFILE", profile)
        rendered = render_optimize_gremlin_query_prompt("g.V().hasLabel('person')")

        assert "execute_gremlin_read_tool" not in rendered
        assert "query_graph_data_tool" in rendered
        assert "traverse_graph_tool" in rendered
        assert "separate client-side validation" in rendered
