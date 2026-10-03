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

from hugegraph_llm.extraction_runtime.v1 import BudgetExhaustedError, ReviewBudgetStateV1, ReviewBudgetV1

pytestmark = pytest.mark.unit


def test_review_and_fix_budget_are_deterministic_and_immutable() -> None:
    state = ReviewBudgetStateV1(ReviewBudgetV1(max_reviews=2, max_fixes=1))
    after_review = state.consume_review()
    after_fix = after_review.consume_fix()
    exhausted = after_fix.consume_review()

    assert state.reviews_used == 0 and state.fixes_used == 0
    assert exhausted.reviews_used == 2 and exhausted.fixes_used == 1
    assert not exhausted.can_review
    assert not exhausted.can_fix
    with pytest.raises(BudgetExhaustedError, match="review"):
        exhausted.consume_review()
    with pytest.raises(BudgetExhaustedError, match="fix"):
        exhausted.consume_fix()


@pytest.mark.parametrize("field", ["max_reviews", "max_fixes"])
def test_budget_rejects_negative_limits(field: str) -> None:
    values = {"max_reviews": 1, "max_fixes": 1, field: -1}
    with pytest.raises(ValueError, match=field):
        ReviewBudgetV1(**values)
