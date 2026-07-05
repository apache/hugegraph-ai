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

"""Schema-aware prompt contract for the enhanced graph extraction strategy.

The contract is a short structural-constraint block appended after the
caller's ``example_prompt`` and before the per-chunk input section. It does
NOT try to replace the downstream quality layer — parser, normalizer,
assembler, and quality gate remain the effective guarantors. The contract
only nudges the LLM toward a schema-clean first candidate so those stages
have less to fix up.

Scope is intentionally narrow (design section 6.1):

* structural constraints only — no chain-of-thought scaffolding, no
  hallucination-avoidance instructions beyond the design's "omit uncertain
  entities" clause, no anti-jailbreak text;
* no per-property or per-edge examples — the block stays language-agnostic
  and short enough to leave headroom for the caller's own prompt content;
* no attempt to fix the ``example_prompt`` — the block is *appended*, so
  a user-supplied prompt keeps whatever framing it already has.
"""

from __future__ import annotations

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.schema_index import (
    GraphSchemaIndex,
)


def build_prompt_contract(schema_index: GraphSchemaIndex) -> str:
    """Return the constraint block to append after the caller's example_prompt."""
    vertex_labels = ", ".join(sorted(schema_index.vertex_label_names())) or "(none)"
    edge_labels = ", ".join(sorted(schema_index.edge_label_names())) or "(none)"

    return (
        "\n"
        "# Enhanced-strategy constraints\n"
        "The extraction below is post-processed by a schema-aware quality layer. To "
        "maximize the fraction of your output that survives that layer:\n"
        "\n"
        f"1. Vertex `label` MUST be one of: {vertex_labels}.\n"
        f"2. Edge `label` MUST be one of: {edge_labels}.\n"
        "3. Every property key you emit on a vertex or edge MUST be declared in the "
        "schema for that label. Omit properties whose keys are not declared.\n"
        "4. Every vertex MUST include the primary-key properties declared by its "
        "schema label; without them the vertex will be dropped.\n"
        "5. Edge endpoints MAY be given either as `outV`/`inV` (referring to a "
        "vertex `id` you emit in the same output) OR as `source`/`target` objects "
        "containing `label` and `properties` (with the referenced vertex's primary "
        "keys). Either form is accepted.\n"
        "6. When the input text does not clearly state a fact, OMIT it. Do not "
        "fabricate entities, edges, or property values.\n"
        "7. Output ONLY JSON — no prose before or after the JSON block.\n"
        "\n"
    )
