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

import pytest


@pytest.mark.parametrize("has_projection", [False, True])
async def test_algorithm_is_unavailable_with_or_without_projection(client, has_projection):
    http, sc = client
    # The endpoint does not use the client until algorithms are implemented;
    # a sentinel exercises the configured branch without an external service.
    sc.projection_client = object() if has_projection else None
    response = await http.post("/api/v1/graph/algorithm", json={})
    assert response.status_code == 501
    assert response.json()["detail"]
