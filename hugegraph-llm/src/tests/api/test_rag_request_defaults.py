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

"""API request models must defer the vector distance threshold to configuration."""

import pytest

from hugegraph_llm.api.models.rag_requests import GraphRAGRequest, RAGRequest

pytestmark = pytest.mark.contract


def test_rag_request_vector_threshold_defaults_to_unset():
    """Omitting vector_dis_threshold keeps it unset so CHUNK_DIS_THRESHOLD applies to chunk retrieval."""
    assert RAGRequest(query="q").vector_dis_threshold is None


def test_graph_rag_request_vector_threshold_defaults_to_unset():
    """Omitting vector_dis_threshold keeps it unset so each consumer resolves its own configured default."""
    assert GraphRAGRequest(query="q").vector_dis_threshold is None


def test_requests_accept_explicit_vector_threshold():
    """An explicit threshold (including 0) overrides the configured defaults for the call."""
    assert RAGRequest(query="q", vector_dis_threshold=0).vector_dis_threshold == 0
    assert GraphRAGRequest(query="q", vector_dis_threshold=1.5).vector_dis_threshold == 1.5
