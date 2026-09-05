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

"""Deterministic review and successful-fix budget accounting."""

from __future__ import annotations

from dataclasses import dataclass

from hugegraph_llm.extraction_runtime.v1.errors import BudgetExhaustedError


@dataclass(frozen=True)
class ReviewBudgetV1:
    max_reviews: int
    max_fixes: int

    def __post_init__(self) -> None:
        if self.max_reviews < 0:
            raise ValueError("max_reviews must be non-negative")
        if self.max_fixes < 0:
            raise ValueError("max_fixes must be non-negative")


@dataclass(frozen=True)
class ReviewBudgetStateV1:
    budget: ReviewBudgetV1
    reviews_used: int = 0
    fixes_used: int = 0

    @property
    def can_review(self) -> bool:
        return self.reviews_used < self.budget.max_reviews

    @property
    def can_fix(self) -> bool:
        return self.fixes_used < self.budget.max_fixes

    def consume_review(self) -> ReviewBudgetStateV1:
        if not self.can_review:
            raise BudgetExhaustedError("review budget exhausted")
        return ReviewBudgetStateV1(self.budget, self.reviews_used + 1, self.fixes_used)

    def consume_fix(self) -> ReviewBudgetStateV1:
        if not self.can_fix:
            raise BudgetExhaustedError("fix budget exhausted")
        return ReviewBudgetStateV1(self.budget, self.reviews_used, self.fixes_used + 1)
