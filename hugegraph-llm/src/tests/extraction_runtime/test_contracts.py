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
from pydantic import ValidationError

from hugegraph_llm.extraction_runtime.v1 import ChunkResult, ExtractionOptions, Issue

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("field", ["max_reviews", "max_fixes", "max_workers"])
@pytest.mark.parametrize("value", [-1, True, 1.5, "2"])
def test_options_reject_invalid_limits(field, value):
    with pytest.raises(ValidationError):
        ExtractionOptions(**{field: value})


def test_options_allow_zero_business_budgets_but_require_workers():
    assert ExtractionOptions(max_reviews=0, max_fixes=0).max_workers == 4
    with pytest.raises(ValidationError):
        ExtractionOptions(max_workers=0)


@pytest.mark.parametrize("field, upper", [("max_reviews", 5), ("max_fixes", 3), ("max_workers", 8)])
def test_options_accept_upper_boundary_and_reject_excess(field, upper):
    assert getattr(ExtractionOptions(**{field: upper}), field) == upper
    with pytest.raises(ValidationError) as exc_info:
        ExtractionOptions(**{field: upper + 1})
    error = exc_info.value.errors()[0]
    assert error["loc"] == (field,)
    assert error["type"] == "less_than_equal"


def test_options_reject_unknown_fields_instead_of_using_defaults():
    with pytest.raises(ValidationError) as exc_info:
        ExtractionOptions(max_review=0)
    error = exc_info.value.errors()[0]
    assert error["loc"] == ("max_review",)
    assert error["type"] == "extra_forbidden"


def test_result_serializes_issues_and_detaches_payload():
    result = ChunkResult(
        0, "blocked", {"vertices": []}, [Issue("vertices", "missing", "Alice")], "invalid", None, 0, 0, 1
    )
    payload = result.as_dict()
    assert payload["issues"] == [{"path": "vertices", "message": "missing", "evidence": "Alice"}]
    payload["graph"]["vertices"].append({"id": "new"})
    assert result.graph == {"vertices": []}
