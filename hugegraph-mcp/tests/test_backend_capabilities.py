# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

from dataclasses import FrozenInstanceError

import pytest
from hugegraph_mcp.backend_capabilities import (
    BackendFeature,
    SupportStatus,
    profile_for,
)


def test_hugegraph_1_7_rocksdb_profile_is_complete():
    profile = profile_for("1.7.0", "rocksdb")

    assert {feature for feature, _evidence in profile.capabilities} == set(BackendFeature)


@pytest.mark.parametrize(
    "feature",
    [
        BackendFeature.EDGE_ID_STABLE_ADDRESSING,
        BackendFeature.GREMLIN_EVALUATION_TIMEOUT,
        BackendFeature.REST_GREMLIN_WAIT_TIMEOUT,
        BackendFeature.TASK_RESULT_SIZE_LIMIT,
        BackendFeature.READONLY_PRINCIPAL,
    ],
)
def test_hugegraph_1_7_verified_supported_capabilities(feature):
    profile = profile_for("1.7.0", "rocksdb")

    assert profile.status_for(feature) is SupportStatus.VERIFIED_SUPPORTED
    assert profile.supports(feature) is True


@pytest.mark.parametrize(
    "feature",
    [
        BackendFeature.VERTEX_CREATE_IF_ABSENT,
        BackendFeature.EDGE_CREATE_IF_ABSENT,
        BackendFeature.PROPERTY_COMPARE_AND_SET,
        BackendFeature.HTTP_STREAMING_RESPONSE_LIMIT,
    ],
)
def test_hugegraph_1_7_verified_unsupported_capabilities(feature):
    profile = profile_for("1.7.0", "rocksdb")

    assert profile.status_for(feature) is SupportStatus.VERIFIED_UNSUPPORTED
    assert profile.supports(feature) is False


@pytest.mark.parametrize(
    "feature",
    [
        BackendFeature.EDGE_IDEMPOTENT_IDENTITY,
        BackendFeature.ISOLATED_VERTEX_DELETE,
        BackendFeature.QUERY_MEMORY_LIMIT,
        BackendFeature.GREMLIN_RESULT_ITEM_LIMIT,
    ],
)
def test_unverified_capabilities_fail_closed(feature):
    profile = profile_for("1.7.0", "rocksdb")

    assert profile.status_for(feature) is SupportStatus.UNKNOWN
    assert profile.supports(feature) is False


def test_unknown_server_or_backend_fails_closed():
    for profile in (
        profile_for("1.7.1", "rocksdb"),
        profile_for("1.7.0", "hstore"),
        profile_for("", ""),
    ):
        assert all(profile.status_for(feature) is SupportStatus.UNKNOWN for feature in BackendFeature)
        assert not any(profile.supports(feature) for feature in BackendFeature)


def test_isolated_vertex_delete_adapter_fails_closed_for_observed_and_unknown_profiles():
    observed_profile = profile_for("1.7.0", "rocksdb")
    unknown_profile = profile_for("1.7.0", "unknown-backend")

    for profile in (observed_profile, unknown_profile):
        assert profile.status_for(BackendFeature.ISOLATED_VERTEX_DELETE) is SupportStatus.UNKNOWN
        assert profile.supports(BackendFeature.ISOLATED_VERTEX_DELETE) is False

    evidence = observed_profile.evidence_for(BackendFeature.ISOLATED_VERTEX_DELETE)
    assert evidence.source == "hugegraph-mcp/tests/integration/test_real_write_path.py"
    assert "barrier-synchronized Docker stress probe" in evidence.reason


def test_profile_and_evidence_are_immutable():
    profile = profile_for("1.7.0", "rocksdb")
    evidence = profile.evidence_for(BackendFeature.PROPERTY_COMPARE_AND_SET)

    with pytest.raises(FrozenInstanceError):
        profile.backend = "hstore"
    with pytest.raises(FrozenInstanceError):
        evidence.status = SupportStatus.VERIFIED_SUPPORTED


def test_each_verified_capability_records_evidence_source():
    profile = profile_for("1.7.0", "rocksdb")

    for feature in BackendFeature:
        evidence = profile.evidence_for(feature)
        if evidence.status is not SupportStatus.UNKNOWN:
            assert evidence.source
            assert evidence.reason
