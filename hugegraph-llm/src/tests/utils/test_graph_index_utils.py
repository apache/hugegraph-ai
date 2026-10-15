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

from unittest.mock import Mock

from pyhugegraph.client import PyHugeClient

from hugegraph_llm.utils.graph_index_utils import get_vertex_details
from tests.utils.mock import FakeGremlinEndpoint


def test_get_vertex_details_escapes_apostrophes_in_vertex_ids():
    endpoint = FakeGremlinEndpoint({"1:O'Brien": {"name": "O'Brien"}})
    client = Mock(spec=PyHugeClient)
    client.gremlin.return_value = endpoint

    result = get_vertex_details(["1:O'Brien"], {"graph_client": client})

    assert [v["id"] for v in result] == ["1:O'Brien"]
    assert endpoint.scripts == ["g.V('1:O\\'Brien').limit(20)"]
