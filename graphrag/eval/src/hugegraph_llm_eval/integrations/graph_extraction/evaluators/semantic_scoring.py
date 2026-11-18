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

"""Global weighted matching and evidence for semantic graph matches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import networkx as nx

from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvidenceLink,
    Finding,
    FindingSeverity,
    Measurement,
    MeasurementDirection,
)


@dataclass(frozen=True, slots=True)
class MatchPair:
    """A scored candidate/reference semantic match proposed by the LLM."""

    candidate_index: int
    reference_index: int
    reason: str
    match_score: float
    match_issues: tuple[str, ...] = ()


def _networkx():
    try:
        import networkx
    except ImportError as exc:
        msg = "semantic graph matching requires the 'graph' extra: pip install hugegraph-llm-eval[graph]"
        raise ImportError(msg) from exc
    return networkx


def global_optimal_matches(
    matches: list[MatchPair], *, strategy: Literal["max_weight", "max_cardinality"] = "max_weight"
) -> tuple[MatchPair, ...]:
    """Select a maximum-weight one-to-one matching over all proposed pairs."""
    if strategy not in ("max_weight", "max_cardinality"):
        raise ValueError("unknown matching strategy")
    graph, pair_by_edge = _matching_graph(matches)
    matching = _networkx().max_weight_matching(graph, maxcardinality=strategy == "max_cardinality", weight="weight")
    return _accepted_pairs(matching, pair_by_edge)


def _matching_graph(
    matches: list[MatchPair],
) -> tuple[nx.Graph, dict[frozenset[tuple[str, int]], MatchPair]]:
    """Build a sparse graph and retain the highest-scoring duplicate edge."""
    graph = _networkx().Graph()
    pair_by_edge: dict[frozenset[tuple[str, int]], MatchPair] = {}
    for pair in matches:
        candidate_node = ("candidate", pair.candidate_index)
        reference_node = ("reference", pair.reference_index)
        edge_key = frozenset((candidate_node, reference_node))
        previous = pair_by_edge.get(edge_key)
        if previous is None or pair.match_score > previous.match_score:
            pair_by_edge[edge_key] = pair
            graph.add_edge(candidate_node, reference_node, weight=pair.match_score)
    return graph, pair_by_edge


def _accepted_pairs(
    matching: set[frozenset[tuple[str, int]]],
    pair_by_edge: dict[frozenset[tuple[str, int]], MatchPair],
) -> tuple[MatchPair, ...]:
    """Convert NetworkX edges into stable, indexed match pairs."""
    return tuple(
        sorted(
            (pair_by_edge[frozenset(edge)] for edge in matching),
            key=lambda pair: (pair.candidate_index, pair.reference_index),
        )
    )


def deduplicate_matches(matches: list[MatchPair]) -> tuple[MatchPair, ...]:
    """Keep the historical API name while using global optimal matching."""
    return global_optimal_matches(matches)


def semantic_measurements(
    kind: str,
    precision: float,
    recall: float,
    f1: float,
) -> tuple[Measurement, ...]:
    values = (("precision", precision), ("recall", recall), ("f1", f1))
    return tuple(
        Measurement(
            name=f"semantic_{kind}_{name}",
            value=value,
            unit="ratio",
            direction=MeasurementDirection.HIGHER_IS_BETTER,
        )
        for name, value in values
    )


def semantic_findings(
    kind: str,
    candidate_count: int,
    reference_count: int,
    accepted: tuple[MatchPair, ...],
    candidate_artifact: ArtifactRef,
    reference_artifact: ArtifactRef,
) -> tuple[Finding, ...]:
    collection = "vertices" if kind == "entity" else "edges"
    matched_candidates = {pair.candidate_index for pair in accepted}
    matched_references = {pair.reference_index for pair in accepted}
    return (
        *_matched_findings(kind, collection, accepted, candidate_artifact, reference_artifact),
        *_match_issue_findings(kind, collection, accepted, candidate_artifact, reference_artifact),
        *_unmatched_findings(
            kind,
            collection,
            candidate_count,
            reference_count,
            matched_candidates,
            matched_references,
            candidate_artifact,
            reference_artifact,
        ),
    )


def _matched_findings(
    kind: str,
    collection: str,
    accepted: tuple[MatchPair, ...],
    candidate_artifact: ArtifactRef,
    reference_artifact: ArtifactRef,
) -> tuple[Finding, ...]:
    return tuple(
        Finding(
            code=f"semantic_{kind}.matched",
            severity=FindingSeverity.INFO,
            message=pair.reason,
            evidence=(
                EvidenceLink(artifact=candidate_artifact, locator=f"{collection}[{pair.candidate_index}]"),
                EvidenceLink(artifact=reference_artifact, locator=f"{collection}[{pair.reference_index}]"),
            ),
        )
        for pair in accepted
    )


def _match_issue_findings(
    kind: str,
    collection: str,
    accepted: tuple[MatchPair, ...],
    candidate_artifact: ArtifactRef,
    reference_artifact: ArtifactRef,
) -> tuple[Finding, ...]:
    """Expose accepted-match quality issues as machine-readable findings."""
    return tuple(
        Finding(
            code=f"semantic_{kind}.match_issue.{issue}",
            severity=FindingSeverity.WARNING,
            message=pair.reason,
            evidence=(
                EvidenceLink(artifact=candidate_artifact, locator=f"{collection}[{pair.candidate_index}]"),
                EvidenceLink(artifact=reference_artifact, locator=f"{collection}[{pair.reference_index}]"),
            ),
        )
        for pair in accepted
        for issue in pair.match_issues
    )


def _unmatched_findings(
    kind: str,
    collection: str,
    candidate_count: int,
    reference_count: int,
    matched_candidates: set[int],
    matched_references: set[int],
    candidate_artifact: ArtifactRef,
    reference_artifact: ArtifactRef,
) -> tuple[Finding, ...]:
    candidate_findings = tuple(
        Finding(
            code=f"semantic_{kind}.unmatched_candidate",
            severity=FindingSeverity.WARNING,
            message="candidate has no accepted semantic reference match",
            evidence=(EvidenceLink(artifact=candidate_artifact, locator=f"{collection}[{index}]"),),
        )
        for index in range(candidate_count)
        if index not in matched_candidates
    )
    reference_findings = tuple(
        Finding(
            code=f"semantic_{kind}.unmatched_reference",
            severity=FindingSeverity.ERROR,
            message="reference has no accepted semantic candidate match",
            evidence=(EvidenceLink(artifact=reference_artifact, locator=f"{collection}[{index}]"),),
        )
        for index in range(reference_count)
        if index not in matched_references
    )
    return (*candidate_findings, *reference_findings)
