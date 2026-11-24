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

"""The OpenAI judge factory wires a client, model name and options."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("openai", reason="install hugegraph-llm-eval[openai] to run provider contracts")

from test_judge import FakeCompletions, _request, _response

from hugegraph_llm_eval import openai_judge
from hugegraph_llm_eval.evaluation.judges.base import JudgeOptions

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class _FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = _FakeChat(completions)


def test_factory_wires_the_client_and_model() -> None:
    completions = FakeCompletions(_response())
    judge = openai_judge(model="example-judge", client=_FakeClient(completions))

    result = judge.judge(_request(), JudgeOptions(max_attempts=1))

    assert result.output.score == 0.9
    assert completions.calls[0]["model"] == "example-judge"
    assert judge.descriptor.model == "example-judge"


def test_factory_records_pricing_in_the_descriptor() -> None:
    free = openai_judge(model="judge", client=_FakeClient(FakeCompletions()))
    priced = openai_judge(
        model="judge",
        client=_FakeClient(FakeCompletions()),
        input_usd_per_million=1.0,
        output_usd_per_million=2.0,
    )

    assert free.descriptor.configuration_digest != priced.descriptor.configuration_digest


def test_real_model_example_explains_missing_configuration() -> None:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("EVAL_JUDGE_")}
    environment["PYTHONPATH"] = str(PACKAGE_ROOT / "src")

    result = subprocess.run(
        [sys.executable, str(PACKAGE_ROOT / "examples/real_model.py")],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=PACKAGE_ROOT,
    )

    assert result.returncode == 2
    assert "EVAL_JUDGE_MODEL" in result.stderr
    assert "hugegraph-llm-eval[openai]" in result.stderr
