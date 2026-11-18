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

"""The SDK must stay importable without the application or vendor packages."""

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
INSTALLED = bool(os.environ.get("HUGEGRAPH_LLM_EVAL_TEST_INSTALLED"))

_SCRIPT = """
import sys
if not {installed!r}:
    sys.path.insert(0, {src!r})
import hugegraph_llm_eval  # noqa: F401

forbidden_roots = {{
    "openai",
    "networkx",
    "rouge_score",
    "litellm",
    "ollama",
    "jieba",
    "nltk",
    "tenacity",
    "tiktoken",
}}
forbidden = sorted(
    name
    for name in sys.modules
    if name == "hugegraph_llm"
    or name.startswith("hugegraph_llm.")
    or name.startswith("hugegraph_llm_sdk")
    or name.split(".")[0] in forbidden_roots
)
print("|".join(forbidden))
"""


def test_import_does_not_load_application_or_vendor_modules() -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c", _SCRIPT.format(installed=INSTALLED, src=str(SRC))],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_package_exposes_only_documented_entry_points() -> None:
    import hugegraph_llm_eval

    missing = [name for name in hugegraph_llm_eval.__all__ if not hasattr(hugegraph_llm_eval, name)]
    assert missing == []
