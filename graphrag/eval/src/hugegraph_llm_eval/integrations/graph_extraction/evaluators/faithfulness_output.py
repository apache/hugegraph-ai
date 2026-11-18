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

"""Compact provider output and lossless item-level faithfulness verdicts."""

from enum import StrEnum

from pydantic import Field, model_validator

from hugegraph_llm_eval.contracts.base import StrictModel


class FaithfulnessItemKind(StrEnum):
    VERTEX = "vertex"
    EDGE = "edge"


class FaithfulnessErrorCategory(StrEnum):
    """Controlled categories for unsupported extraction claims."""

    UNSUPPORTED_CLAIM = "unsupported_claim"
    NUMERIC_MISMATCH = "numeric_mismatch"
    UNIT_MISMATCH = "unit_mismatch"
    CONDITION_LOSS = "condition_loss"
    RANGE_LOSS = "range_loss"
    TEMPORAL_MISMATCH = "temporal_mismatch"
    POLARITY_REVERSAL = "polarity_reversal"
    SUBJECT_SCOPE_ERROR = "subject_scope_error"


class FaithfulnessVerdict(StrictModel):
    item_kind: FaithfulnessItemKind
    item_index: int = Field(ge=0)
    faithful: bool
    error_categories: tuple[FaithfulnessErrorCategory, ...] = ()
    support_reason: str | None = Field(max_length=4_000)
    error_reason: str | None = Field(default=None, max_length=4_000)
    evidence_quote: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def _validate_error_categories(self) -> "FaithfulnessVerdict":
        """Require categories only for unsupported claims."""
        if len(self.error_categories) != len(set(self.error_categories)):
            raise ValueError("faithfulness error categories must be unique")
        if self.faithful and self.error_categories:
            raise ValueError("faithful items must not contain error categories")
        if self.faithful and self.error_reason is not None:
            raise ValueError("faithful items must not contain an error reason")
        if not self.faithful:
            if not self.error_categories:
                raise ValueError("unsupported items must contain error categories")
            if not self.error_reason:
                raise ValueError("unsupported items must contain an error reason")
        return self


class FaithfulnessIssueGroup(StrictModel):
    item_indices: tuple[int, ...] = Field(min_length=1)
    error_categories: tuple[FaithfulnessErrorCategory, ...] = Field(min_length=1)
    support_reason: str | None = Field(default=None, max_length=4_000)
    error_reason: str = Field(min_length=1, max_length=4_000)
    evidence_quote: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def _validate_indices(self) -> "FaithfulnessIssueGroup":
        if any(index < 0 for index in self.item_indices):
            raise ValueError("faithfulness item indices must be non-negative")
        if len(self.item_indices) != len(set(self.item_indices)):
            raise ValueError("faithfulness issue group item indices must be unique")
        if len(self.error_categories) != len(set(self.error_categories)):
            raise ValueError("faithfulness error categories must be unique")
        return self


class FaithfulnessJudgeOutput(StrictModel):
    """Compact partition returned by a Judge and expanded by the evaluator."""

    supported_vertex_indices: tuple[int, ...] = ()
    supported_edge_indices: tuple[int, ...] = ()
    unsupported_vertex_groups: tuple[FaithfulnessIssueGroup, ...] = ()
    unsupported_edge_groups: tuple[FaithfulnessIssueGroup, ...] = ()

    @model_validator(mode="after")
    def _validate_item_partition(self) -> "FaithfulnessJudgeOutput":
        _validate_partition(self.supported_vertex_indices, self.unsupported_vertex_groups, "vertex")
        _validate_partition(self.supported_edge_indices, self.unsupported_edge_groups, "edge")
        return self

    @classmethod
    def from_verdicts(cls, verdicts: tuple[FaithfulnessVerdict, ...]) -> "FaithfulnessJudgeOutput":
        return cls(
            supported_vertex_indices=_supported_indices(verdicts, FaithfulnessItemKind.VERTEX),
            supported_edge_indices=_supported_indices(verdicts, FaithfulnessItemKind.EDGE),
            unsupported_vertex_groups=_unsupported_groups(verdicts, FaithfulnessItemKind.VERTEX),
            unsupported_edge_groups=_unsupported_groups(verdicts, FaithfulnessItemKind.EDGE),
        )

    def verdicts(self) -> tuple[FaithfulnessVerdict, ...]:
        verdicts = (
            *_supported_verdicts(FaithfulnessItemKind.VERTEX, self.supported_vertex_indices),
            *_supported_verdicts(FaithfulnessItemKind.EDGE, self.supported_edge_indices),
            *_unsupported_verdicts(FaithfulnessItemKind.VERTEX, self.unsupported_vertex_groups),
            *_unsupported_verdicts(FaithfulnessItemKind.EDGE, self.unsupported_edge_groups),
        )
        return tuple(sorted(verdicts, key=_verdict_order))


def _supported_indices(
    verdicts: tuple[FaithfulnessVerdict, ...],
    kind: FaithfulnessItemKind,
) -> tuple[int, ...]:
    return tuple(item.item_index for item in verdicts if item.item_kind is kind and item.faithful)


def _unsupported_groups(
    verdicts: tuple[FaithfulnessVerdict, ...],
    kind: FaithfulnessItemKind,
) -> tuple[FaithfulnessIssueGroup, ...]:
    return tuple(_issue_group(item) for item in verdicts if item.item_kind is kind and not item.faithful)


def _validate_partition(
    supported: tuple[int, ...],
    unsupported: tuple[FaithfulnessIssueGroup, ...],
    kind: str,
) -> None:
    if any(index < 0 for index in supported):
        raise ValueError(f"supported {kind} indices must be non-negative")
    if len(supported) != len(set(supported)):
        raise ValueError(f"supported {kind} indices must be unique")
    unsupported_indices = tuple(index for group in unsupported for index in group.item_indices)
    if len(unsupported_indices) != len(set(unsupported_indices)):
        raise ValueError(f"unsupported {kind} indices must be unique across groups")
    if set(supported) & set(unsupported_indices):
        raise ValueError(f"supported and unsupported {kind} indices must not overlap")


def _issue_group(verdict: FaithfulnessVerdict) -> FaithfulnessIssueGroup:
    return FaithfulnessIssueGroup(
        item_indices=(verdict.item_index,),
        error_categories=verdict.error_categories,
        support_reason=verdict.support_reason,
        error_reason=verdict.error_reason or "unsupported claim",
        evidence_quote=verdict.evidence_quote,
    )


def _supported_verdicts(
    kind: FaithfulnessItemKind,
    indices: tuple[int, ...],
) -> tuple[FaithfulnessVerdict, ...]:
    return tuple(
        FaithfulnessVerdict(
            item_kind=kind,
            item_index=index,
            faithful=True,
            support_reason="source evidence supports this item",
        )
        for index in indices
    )


def _unsupported_verdicts(
    kind: FaithfulnessItemKind,
    groups: tuple[FaithfulnessIssueGroup, ...],
) -> tuple[FaithfulnessVerdict, ...]:
    return tuple(
        FaithfulnessVerdict(
            item_kind=kind,
            item_index=index,
            faithful=False,
            error_categories=group.error_categories,
            support_reason=group.support_reason,
            error_reason=group.error_reason,
            evidence_quote=group.evidence_quote,
        )
        for group in groups
        for index in group.item_indices
    )


def _verdict_order(verdict: FaithfulnessVerdict) -> tuple[bool, int]:
    return verdict.item_kind is FaithfulnessItemKind.EDGE, verdict.item_index
