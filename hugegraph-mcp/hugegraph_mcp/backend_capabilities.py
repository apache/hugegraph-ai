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

"""Evidence-backed HugeGraph backend capability profiles.

This module describes backend behavior; it is deliberately separate from
``guard.Capability``, which describes caller permissions. Unknown profiles and
unverified features always fail closed.
"""

from dataclasses import dataclass
from enum import Enum


class BackendFeature(str, Enum):
    VERTEX_CREATE_IF_ABSENT = "vertex_create_if_absent"
    EDGE_CREATE_IF_ABSENT = "edge_create_if_absent"
    EDGE_ID_STABLE_ADDRESSING = "edge_id_stable_addressing"
    EDGE_IDEMPOTENT_IDENTITY = "edge_idempotent_identity"
    ISOLATED_VERTEX_DELETE = "isolated_vertex_delete"
    PROPERTY_COMPARE_AND_SET = "property_compare_and_set"
    GREMLIN_EVALUATION_TIMEOUT = "gremlin_evaluation_timeout"
    REST_GREMLIN_WAIT_TIMEOUT = "rest_gremlin_wait_timeout"
    TASK_RESULT_SIZE_LIMIT = "task_result_size_limit"
    QUERY_MEMORY_LIMIT = "query_memory_limit"
    GREMLIN_RESULT_ITEM_LIMIT = "gremlin_result_item_limit"
    HTTP_STREAMING_RESPONSE_LIMIT = "http_streaming_response_limit"
    READONLY_PRINCIPAL = "readonly_principal"


class SupportStatus(str, Enum):
    VERIFIED_SUPPORTED = "verified_supported"
    VERIFIED_UNSUPPORTED = "verified_unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CapabilityEvidence:
    status: SupportStatus
    source: str
    reason: str


@dataclass(frozen=True)
class BackendProfile:
    server_version: str
    backend: str
    capabilities: tuple[tuple[BackendFeature, CapabilityEvidence], ...]

    def __post_init__(self) -> None:
        features = [feature for feature, _evidence in self.capabilities]
        if len(features) != len(set(features)):
            raise ValueError("Backend profile contains duplicate features")
        if set(features) != set(BackendFeature):
            raise ValueError("Backend profile must declare every backend feature")

    def evidence_for(self, feature: BackendFeature) -> CapabilityEvidence:
        for candidate, evidence in self.capabilities:
            if candidate is feature:
                return evidence
        return _unknown_evidence("Feature is absent from the profile")

    def status_for(self, feature: BackendFeature) -> SupportStatus:
        return self.evidence_for(feature).status

    def supports(self, feature: BackendFeature) -> bool:
        return self.status_for(feature) is SupportStatus.VERIFIED_SUPPORTED


def _supported(source: str, reason: str) -> CapabilityEvidence:
    return CapabilityEvidence(SupportStatus.VERIFIED_SUPPORTED, source, reason)


def _unsupported(source: str, reason: str) -> CapabilityEvidence:
    return CapabilityEvidence(SupportStatus.VERIFIED_UNSUPPORTED, source, reason)


def _unknown_evidence(reason: str, *, source: str = "") -> CapabilityEvidence:
    return CapabilityEvidence(SupportStatus.UNKNOWN, source, reason)


_HG17_ROCKSDB = BackendProfile(
    server_version="1.7.0",
    backend="rocksdb",
    capabilities=(
        (
            BackendFeature.VERTEX_CREATE_IF_ABSENT,
            _unsupported(
                "hugegraph-python-client/src/pyhugegraph/api/graph.py",
                "The graph REST client exposes unconditional vertex POST only.",
            ),
        ),
        (
            BackendFeature.EDGE_CREATE_IF_ABSENT,
            _unsupported(
                "hugegraph-python-client/src/pyhugegraph/api/graph.py",
                "The graph REST client exposes unconditional edge POST only.",
            ),
        ),
        (
            BackendFeature.EDGE_ID_STABLE_ADDRESSING,
            _supported(
                "hugegraph-mcp/tests/integration/test_real_write_path.py",
                "HugeGraph 1.7 returns an edge ID that can be read and deleted by ID.",
            ),
        ),
        (
            BackendFeature.EDGE_IDEMPOTENT_IDENTITY,
            _unknown_evidence("Duplicate-edge uniqueness and idempotency are not proven."),
        ),
        (
            BackendFeature.ISOLATED_VERTEX_DELETE,
            _unknown_evidence(
                "A barrier-synchronized Docker stress probe observed edge creation "
                "reporting success while concurrent not(bothE()).drop() removed both "
                "the vertex and edge. The operation must fail closed because isolated "
                "conditional deletion is not supported by the observed behavior.",
                source="hugegraph-mcp/tests/integration/test_real_write_path.py",
            ),
        ),
        (
            BackendFeature.PROPERTY_COMPARE_AND_SET,
            _unsupported(
                "hugegraph-python-client/src/pyhugegraph/api/graph.py",
                "Property append/eliminate requests have no expected-state CAS field.",
            ),
        ),
        (
            BackendFeature.GREMLIN_EVALUATION_TIMEOUT,
            _supported(
                "hugegraph/hugegraph:1.7.0 conf/gremlin-server.yaml",
                "The Docker image configures evaluationTimeout=30000 milliseconds.",
            ),
        ),
        (
            BackendFeature.REST_GREMLIN_WAIT_TIMEOUT,
            _supported(
                "HugeGraph 1.7 configuration option gremlinserver.timeout",
                "The REST gateway has a bounded wait for Gremlin Server responses.",
            ),
        ),
        (
            BackendFeature.TASK_RESULT_SIZE_LIMIT,
            _supported(
                "HugeGraph 1.7 configuration option task.result_size_limit",
                "Task/job results have a configured byte limit; it does not cap /gremlin responses.",
            ),
        ),
        (
            BackendFeature.QUERY_MEMORY_LIMIT,
            _unknown_evidence(
                "memory.one_query_max_capacity is present but disabled in the default Docker graph config."
            ),
        ),
        (
            BackendFeature.GREMLIN_RESULT_ITEM_LIMIT,
            _unknown_evidence("No general server-side /gremlin result-item cap was verified."),
        ),
        (
            BackendFeature.HTTP_STREAMING_RESPONSE_LIMIT,
            _unsupported(
                "hugegraph-python-client/src/pyhugegraph/utils/huge_requests.py",
                "The client fully materializes responses and exposes no streaming byte budget.",
            ),
        ),
        (
            BackendFeature.READONLY_PRINCIPAL,
            _supported(
                "HugeGraph 1.7 StandardAuthenticator documentation",
                "HugeGraph supports users, groups, operations, and resource-scoped permissions; "
                "Docker defaults do not enable it.",
            ),
        ),
    ),
)

_PROFILES = {
    (_HG17_ROCKSDB.server_version, _HG17_ROCKSDB.backend): _HG17_ROCKSDB,
}


def profile_for(server_version: str, backend: str) -> BackendProfile:
    """Return an exact profile; unknown version/backend combinations fail closed."""

    key = (server_version.strip(), backend.strip().lower())
    profile = _PROFILES.get(key)
    if profile is not None:
        return profile
    return BackendProfile(
        server_version=key[0],
        backend=key[1],
        capabilities=tuple(
            (
                feature,
                _unknown_evidence("No evidence-backed profile exists for this exact server/backend combination."),
            )
            for feature in BackendFeature
        ),
    )
