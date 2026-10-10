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

from hugegraph_mcp.write_limits import (
    MAX_OPERATIONS,
    MAX_PAYLOAD_BYTES,
    collect_write_limit_errors,
    graph_data_operation_count,
    payload_byte_size,
)


def test_write_limit_constants_match_contract():
    assert MAX_OPERATIONS == 200
    assert MAX_PAYLOAD_BYTES == 1_048_576


def test_collect_write_limit_errors_accepts_boundary():
    operations = [{"op": "create_vertex"}] * MAX_OPERATIONS
    assert collect_write_limit_errors(len(operations), operations) == []


def test_collect_write_limit_errors_rejects_operation_overflow():
    operations = [{"op": "create_vertex"}] * (MAX_OPERATIONS + 1)
    errors = collect_write_limit_errors(len(operations), operations)
    assert errors
    assert "MAX_OPERATIONS" in errors[0]["reason"]


def test_payload_byte_size_rejects_over_one_mib():
    payload = {"blob": "x" * MAX_PAYLOAD_BYTES}
    assert payload_byte_size(payload) > MAX_PAYLOAD_BYTES
    errors = collect_write_limit_errors(1, payload)
    assert errors
    assert "MAX_PAYLOAD_BYTES" in errors[0]["reason"]


def test_graph_data_operation_count_sums_vertices_and_edges():
    graph_data = {
        "vertices": [{"label": "person"}] * 3,
        "edges": [{"label": "knows"}] * 2,
    }
    assert graph_data_operation_count(graph_data) == 5
