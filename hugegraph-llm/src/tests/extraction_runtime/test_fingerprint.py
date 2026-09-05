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

import pytest

from hugegraph_llm.extraction_runtime.v1 import (
    DomainSemanticManifestV1,
    JsonObject,
    NormalizedChunkV1,
    SemanticResourceV1,
    compose_run_fingerprint,
)

pytestmark = pytest.mark.unit


def _manifest(prompt: str = "extract inventory") -> DomainSemanticManifestV1:
    return DomainSemanticManifestV1(
        bundle_id="inventory",
        bundle_version="1",
        resources=(SemanticResourceV1.from_text("prompt", prompt),),
        semantics={"identity": "sku", "review": "counts-positive"},
    )


def _chunk(text: str = "two bolts") -> NormalizedChunkV1:
    return NormalizedChunkV1(
        document_id="inventory",
        chunk_id="inventory-0",
        ordinal=0,
        text=text,
        visible_metadata={"source": "fixture"},
    )


def test_fingerprint_layers_change_only_for_their_defined_inputs() -> None:
    baseline = compose_run_fingerprint(
        manifest=_manifest(),
        provider_execution={"adapter": "test/v1", "model": "replay"},
        chunk=_chunk(),
        host_plan={"chunker": "fixture/v1"},
    )
    provider_changed = compose_run_fingerprint(
        manifest=_manifest(),
        provider_execution={"adapter": "test/v1", "model": "replay-2"},
        chunk=_chunk(),
        host_plan={"chunker": "fixture/v1"},
    )
    domain_changed = compose_run_fingerprint(
        manifest=_manifest("extract stock"),
        provider_execution={"adapter": "test/v1", "model": "replay"},
        chunk=_chunk(),
        host_plan={"chunker": "fixture/v1"},
    )
    host_changed = compose_run_fingerprint(
        manifest=_manifest(),
        provider_execution={"adapter": "test/v1", "model": "replay"},
        chunk=_chunk(),
        host_plan={"chunker": "fixture/v2"},
    )

    assert baseline.domain_semantic_digest == provider_changed.domain_semantic_digest
    assert baseline.input_digest == provider_changed.input_digest
    assert baseline.provider_execution_digest != provider_changed.provider_execution_digest
    assert baseline.run_fingerprint != provider_changed.run_fingerprint

    assert baseline.provider_execution_digest == domain_changed.provider_execution_digest
    assert baseline.domain_semantic_digest != domain_changed.domain_semantic_digest
    assert baseline.run_fingerprint != domain_changed.run_fingerprint

    assert baseline.domain_semantic_digest == host_changed.domain_semantic_digest
    assert baseline.host_plan_digest != host_changed.host_plan_digest
    assert baseline.run_fingerprint != host_changed.run_fingerprint


def test_supplied_input_digest_must_bind_the_normalized_chunk() -> None:
    chunk = NormalizedChunkV1(
        document_id="inventory",
        chunk_id="inventory-0",
        ordinal=0,
        text="two bolts",
        input_digest="sha256:not-the-chunk",
    )
    with pytest.raises(ValueError, match="input_digest"):
        compose_run_fingerprint(
            manifest=_manifest(),
            provider_execution={"model": "replay"},
            chunk=chunk,
        )


@pytest.mark.parametrize(
    "provider_execution",
    [
        {"model": "replay", "api_key": "secret"},  # pragma: allowlist secret
        {"model": "replay", "headers": {"Authorization": "secret"}},
        {"model": "replay", "run_id": "run-1"},
        {"model": "replay", "timing": {"duration": 1.5}},
    ],
)
def test_fingerprint_rejects_credentials_and_volatile_execution_fields(
    provider_execution: JsonObject,
) -> None:
    with pytest.raises(ValueError, match="credential|volatile"):
        compose_run_fingerprint(
            manifest=_manifest(),
            provider_execution=provider_execution,
            chunk=_chunk(),
        )


def test_normalized_chunk_rejects_credential_metadata() -> None:
    with pytest.raises(ValueError, match="credential"):
        NormalizedChunkV1(
            document_id="inventory",
            chunk_id="inventory-0",
            ordinal=0,
            text="two bolts",
            visible_metadata={"authorization": "secret"},
        )
