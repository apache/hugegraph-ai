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

"""Layered, explainable extraction run fingerprints."""

from __future__ import annotations

from dataclasses import dataclass

from hugegraph_llm.extraction_runtime.v1.contracts import NormalizedChunkV1
from hugegraph_llm.extraction_runtime.v1.json_value import JsonObject, digest_json, ensure_stable_provenance
from hugegraph_llm.extraction_runtime.v1.manifest import DomainSemanticManifestV1

RUNTIME_CONTRACT = {
    "contract": "extraction-runtime/v1",
    "phase_order": ["extract", "schema", "identity", "review_fix", "final_gate"],
    "terminal_contract": "extraction-terminal-body/v1",
    "graph_state_contract": "immutable-current-graph/v1",
}


@dataclass(frozen=True)
class FingerprintLayersV1:
    runtime_contract_digest: str
    domain_semantic_digest: str
    provider_execution_digest: str
    input_digest: str
    host_plan_digest: str | None
    run_fingerprint: str


def compute_input_digest(chunk: NormalizedChunkV1) -> str:
    return digest_json(
        {
            "contract": chunk.contract,
            "document_id": chunk.document_id,
            "chunk_id": chunk.chunk_id,
            "ordinal": chunk.ordinal,
            "text": chunk.text,
            "visible_metadata": chunk.visible_metadata,
        }
    )


def compose_run_fingerprint(
    *,
    manifest: DomainSemanticManifestV1,
    provider_execution: JsonObject,
    chunk: NormalizedChunkV1,
    host_plan: JsonObject | None = None,
) -> FingerprintLayersV1:
    ensure_stable_provenance(provider_execution, path="$.provider_execution")
    if host_plan is not None:
        ensure_stable_provenance(host_plan, path="$.host_plan")
    input_digest = compute_input_digest(chunk)
    if chunk.input_digest and chunk.input_digest != input_digest:
        raise ValueError("normalized chunk input_digest does not bind its visible content")
    runtime_contract_digest = digest_json(RUNTIME_CONTRACT)
    domain_semantic_digest = manifest.domain_semantic_digest
    provider_execution_digest = digest_json(provider_execution)
    host_plan_digest = digest_json(host_plan) if host_plan is not None else None
    run_fingerprint = digest_json(
        {
            "runtime_contract_digest": runtime_contract_digest,
            "domain_semantic_digest": domain_semantic_digest,
            "provider_execution_digest": provider_execution_digest,
            "input_digest": input_digest,
            "host_plan_digest": host_plan_digest,
        }
    )
    return FingerprintLayersV1(
        runtime_contract_digest=runtime_contract_digest,
        domain_semantic_digest=domain_semantic_digest,
        provider_execution_digest=provider_execution_digest,
        input_digest=input_digest,
        host_plan_digest=host_plan_digest,
        run_fingerprint=run_fingerprint,
    )
