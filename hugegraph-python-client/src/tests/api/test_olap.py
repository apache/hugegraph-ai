# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Live full-graph jobs; run against upstream latest and compatibility images."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]


def test_full_graph_count_and_page_rank_roundtrip(client_utils):
    client = client_utils.client
    graph = client.graph()
    # PageRank writes r_rank; declare it before vertices enter schema caches.
    client.schema().property_key("r_rank").as_double().if_not_exist().create()
    client.schema().vertex_label("person").properties("r_rank").nullable_keys("r_rank").append()
    alice = graph.add_vertex("person", {"name": "olap_alice", "age": 20})
    bob = graph.add_vertex("person", {"name": "olap_bob", "age": 25})
    graph.add_edge("knows", alice.id, bob.id, {"date": "2026-01-01"})

    assert client.olap().run("count_vertex", timeout=30, poll_interval=0.05)["*"] == 2
    assert client.olap().run("count_edge", timeout=30, poll_interval=0.05)["*"] == 1

    receipt = client.olap().page_rank({"times": 3, "direction": "OUT", "top": 2})
    task = client.task().wait(receipt["task_id"], timeout=30, poll_interval=0.05)
    assert task["task_status"] == "success"
    result = client.task().result(task)
    assert result["times"] == 3
    assert result["iteration_times"] >= 0
    assert "top" in result

    records = client.task().list_tasks(ids=[receipt["task_id"]])
    assert any(record["id"] == receipt["task_id"] for record in records["tasks"])
    assert client.task().get_task(receipt["task_id"], with_result=False)["task_status"] == "success"


def test_full_rest_body_and_metrics(client_utils):
    client = client_utils.client
    rest = client.rest()
    created = rest.vertex.create(body={"label": "person", "properties": {"name": "rest_alice", "age": 20}})
    assert rest.vertex.get(created["id"])["properties"]["name"] == "rest_alice"
    # Optional features are tested without creating external services.
    assert isinstance(client.metrics().histograms(), dict)
    assert isinstance(client.metrics().all(), str)
