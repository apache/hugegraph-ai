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

"""Deterministic inventory Bundle used to exercise the experimental runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from hugegraph_llm.extraction_runtime.provider import (
    EffectiveRequestV1,
    ProviderCapabilitiesV1,
    ProviderDialectV1,
    ProviderMessageV1,
    ProviderNeutralRequestV1,
    ProviderTransportV1,
)
from hugegraph_llm.extraction_runtime.v1 import (
    DomainSemanticManifestV1,
    GateDisposition,
    GateOutcomeV1,
    GraphSnapshotV1,
    IdentityOutcomeV1,
    JsonObject,
    NormalizedChunkV1,
    RepairOutcomeV1,
    RepairRequestV1,
    ReviewDisposition,
    ReviewOutcomeV1,
    SemanticResourceV1,
    ValidationOutcomeV1,
    canonical_json,
)
from hugegraph_llm.extraction_runtime.v1.json_value import freeze_json_object, thaw_json

_EXTRACT_PROMPT = "Extract inventory items as SKU and non-negative integer count."
_REPAIR_PROMPT = "Repair the inventory graph using the supplied reason and current graph."
_GRAPH_SCHEMA: JsonObject = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["sku", "count"],
                "properties": {"sku": {"type": "string"}, "count": {"type": "integer", "minimum": 0}},
            },
        }
    },
}
_GRAPH_TOOL: JsonObject = {
    "type": "function",
    "function": {"name": "emit_inventory_graph", "parameters": _GRAPH_SCHEMA},
}


@dataclass(frozen=True)
class InventoryPolicyV1:
    minimum_count: int = 1
    blocked_skus: tuple[str, ...] = ()
    gate_disposition: GateDisposition = GateDisposition.PASS

    def __post_init__(self) -> None:
        if self.minimum_count < 0:
            raise ValueError("minimum_count must be non-negative")


class InventoryBundleV1:
    """Small realistic Bundle with independent graph and review semantics."""

    model = "inventory-replay"

    def __init__(self, provider: ProviderTransportV1, policy: InventoryPolicyV1 | None = None) -> None:
        self.provider = provider
        self.policy = policy or InventoryPolicyV1()
        self.dialect = ProviderDialectV1()
        self.capabilities = ProviderCapabilitiesV1(
            structured_tools=True,
            strict_schema=True,
            parallel_tool_calls=True,
        )

    def semantic_manifest(self) -> DomainSemanticManifestV1:
        return DomainSemanticManifestV1(
            bundle_id="inventory-conformance",
            bundle_version="1",
            resources=(
                SemanticResourceV1.from_text("extract-prompt", _EXTRACT_PROMPT),
                SemanticResourceV1.from_text("repair-prompt", _REPAIR_PROMPT),
                SemanticResourceV1.from_text(
                    "graph-schema", canonical_json(_GRAPH_SCHEMA), media_type="application/json"
                ),
            ),
            semantics={
                "identity": "sku-exact/v1",
                "minimum_count": self.policy.minimum_count,
                "blocked_skus": list(self.policy.blocked_skus),
                "gate_disposition": self.policy.gate_disposition.value,
                "materializer": "inventory-provider-output/v1",
            },
        )

    def provider_execution(self) -> JsonObject:
        return freeze_json_object(
            {
                "adapter_contract": self.dialect.contract,
                "capabilities_contract": self.capabilities.contract,
                "model": self.model,
                "temperature": 0.0,
                "max_output_tokens": 512,
                "structured_output": "tool-and-schema",
                "strict_schema": True,
                "parallel_tool_calls": False,
                "timeout_seconds": 30.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            }
        )

    def plan_extract(self, chunk: NormalizedChunkV1) -> EffectiveRequestV1:
        return self.dialect.plan(
            ProviderNeutralRequestV1(
                stage="extract",
                model=self.model,
                messages=(
                    ProviderMessageV1(role="system", content=_EXTRACT_PROMPT),
                    ProviderMessageV1(role="user", content=chunk.text),
                ),
                max_output_tokens=512,
                temperature=0.0,
                tools=(_GRAPH_TOOL,),
                response_schema=_GRAPH_SCHEMA,
                strict_schema=True,
                parallel_tool_calls=False,
            ),
            self.capabilities,
        )

    def plan_repair(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        request: RepairRequestV1,
    ) -> EffectiveRequestV1:
        repair_input = canonical_json(
            {
                "reason": request.reason.value,
                "expected_graph_digest": request.expected_graph_digest,
                "context": request.context,
                "graph": graph.graph,
                "chunk": chunk.text,
            }
        )
        return self.dialect.plan(
            ProviderNeutralRequestV1(
                stage="repair",
                model=self.model,
                messages=(
                    ProviderMessageV1(role="system", content=_REPAIR_PROMPT),
                    ProviderMessageV1(role="user", content=repair_input),
                ),
                max_output_tokens=512,
                temperature=0.0,
                tools=(_GRAPH_TOOL,),
                response_schema=_GRAPH_SCHEMA,
                strict_schema=True,
                parallel_tool_calls=False,
            ),
            self.capabilities,
        )

    def extract(self, chunk: NormalizedChunkV1) -> JsonObject:
        response = self.provider.execute(self.plan_extract(chunk))
        return self._materialize_graph(response.output)

    def validate_schema(self, graph: GraphSnapshotV1, chunk: NormalizedChunkV1) -> ValidationOutcomeV1:
        del chunk
        plain = thaw_json(graph.graph)
        valid = isinstance(plain, dict) and self._valid_items(plain.get("items"))
        diagnostics = () if valid else ({"code": "inventory_schema_invalid"},)
        return ValidationOutcomeV1(valid=valid, diagnostics=diagnostics)

    def identify(self, graph: GraphSnapshotV1, chunk: NormalizedChunkV1) -> IdentityOutcomeV1:
        del chunk
        items = self._items(graph.graph)
        skus = [self._sku(item) for item in items]
        valid = len(set(skus)) == len(skus)
        diagnostics = () if valid else ({"code": "duplicate_inventory_sku"},)
        return IdentityOutcomeV1(valid=valid, identity={"skus": skus}, diagnostics=diagnostics)

    def review(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        validation: ValidationOutcomeV1,
        identity: IdentityOutcomeV1,
    ) -> ReviewOutcomeV1:
        del chunk, validation, identity
        items = self._items(graph.graph)
        blocked = sorted(self._sku(item) for item in items if self._sku(item) in self.policy.blocked_skus)
        low = sorted(self._sku(item) for item in items if self._count(item) < self.policy.minimum_count)
        if blocked:
            disposition = ReviewDisposition.BLOCK
            findings = ({"code": "blocked_sku", "skus": blocked},)
        elif low:
            disposition = ReviewDisposition.FIX
            findings = ({"code": "count_below_minimum", "skus": low},)
        else:
            disposition = ReviewDisposition.PASS
            findings = ()
        return ReviewOutcomeV1(
            disposition=disposition,
            expected_graph_digest=graph.graph_digest,
            findings=findings,
        )

    def repair(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        request: RepairRequestV1,
    ) -> RepairOutcomeV1:
        response = self.provider.execute(self.plan_repair(graph, chunk, request))
        patch = response.output.get("patch")
        return RepairOutcomeV1(
            base_graph_digest=graph.graph_digest,
            candidate_graph=self._materialize_graph(response.output),
            patch=patch if isinstance(patch, Mapping) else None,
        )

    def final_gate(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        validation: ValidationOutcomeV1,
        identity: IdentityOutcomeV1,
        review: ReviewOutcomeV1,
    ) -> GateOutcomeV1:
        del chunk, validation, identity, review
        return GateOutcomeV1(
            disposition=self.policy.gate_disposition,
            expected_graph_digest=graph.graph_digest,
            report={"item_count": len(self._items(graph.graph))},
        )

    @staticmethod
    def _materialize_graph(output: JsonObject) -> JsonObject:
        graph = output.get("graph")
        if not isinstance(graph, Mapping):
            raise TypeError("provider output must contain a graph object")
        return freeze_json_object(graph)

    @staticmethod
    def _valid_items(value: object) -> bool:
        if not isinstance(value, list):
            return False
        return all(
            isinstance(item, dict)
            and isinstance(item.get("sku"), str)
            and bool(item["sku"])
            and isinstance(item.get("count"), int)
            and not isinstance(item.get("count"), bool)
            and item["count"] >= 0
            for item in value
        )

    @staticmethod
    def _items(graph: JsonObject) -> list[dict[str, object]]:
        plain = thaw_json(graph)
        if not isinstance(plain, dict) or not InventoryBundleV1._valid_items(plain.get("items")):
            return []
        items = plain["items"]
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _sku(item: dict[str, object]) -> str:
        value = item["sku"]
        if not isinstance(value, str):
            raise TypeError("inventory SKU must be a string")
        return value

    @staticmethod
    def _count(item: dict[str, object]) -> int:
        value = item["count"]
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("inventory count must be an integer")
        return value
