# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
import pickle

import pytest

from hugegraph_llm_sdk import Issue
from hugegraph_llm_sdk.errors import LLMOutputTruncatedError, SchemaValidationError

CLONES = {
    "copy": copy.copy,
    "deepcopy": copy.deepcopy,
    "pickle-protocol-0": lambda error: pickle.loads(pickle.dumps(error, protocol=0)),
    "pickle-highest": lambda error: pickle.loads(pickle.dumps(error, protocol=pickle.HIGHEST_PROTOCOL)),
}


@pytest.mark.parametrize("clone", CLONES.values(), ids=CLONES.keys())
def test_schema_validation_error_survives_copy_and_pickle(clone):
    error = SchemaValidationError([Issue("schema.vertexlabels", "Required schema collection is missing")])
    error.add_note("while validating draft")

    restored = clone(error)

    assert type(restored) is SchemaValidationError
    assert restored.issues == error.issues
    assert (
        str(restored)
        == str(error)
        == "Invalid graph schema: schema.vertexlabels: Required schema collection is missing"
    )
    assert restored.__notes__ == ["while validating draft"]


@pytest.mark.parametrize("clone", CLONES.values(), ids=CLONES.keys())
def test_truncated_error_survives_copy_and_pickle(clone):
    error = LLMOutputTruncatedError("done_reason=length")
    error.add_note("while extracting chunk 3")

    restored = clone(error)

    assert type(restored) is LLMOutputTruncatedError
    assert restored.reason == "done_reason=length"
    assert str(restored) == str(error) == "LLM output was truncated (done_reason=length)."
    assert restored.__notes__ == ["while extracting chunk 3"]
