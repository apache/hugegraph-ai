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

"""Select an API key or local subscription account without changing call sites."""

import os
from collections.abc import Mapping

from hugegraph_llm_eval import managed_judge


def judge_config_from_env() -> Mapping[str, object]:
    backend = os.getenv("EVAL_JUDGE_BACKEND", "openai")
    model = os.environ["EVAL_JUDGE_MODEL"]
    if backend == "openai":
        return {
            "backend": "openai",
            "model": model,
            "api_key": os.getenv("EVAL_JUDGE_API_KEY"),
            "base_url": os.getenv("EVAL_JUDGE_BASE_URL"),
            "provider": os.getenv("EVAL_JUDGE_PROVIDER", "openai"),
        }
    if backend in ("claude-code", "codex"):
        return {
            "backend": backend,
            "model": model,
            "auth_mode": os.getenv("EVAL_JUDGE_AUTH_MODE", "subscription"),
        }
    raise ValueError(f"Unsupported EVAL_JUDGE_BACKEND: {backend}")


def main() -> None:
    with managed_judge(judge_config_from_env()) as judge:
        print(judge.descriptor.model_dump_json(indent=2))
        # Pass ``judge`` to any evaluator or EvaluationEngine here.


if __name__ == "__main__":
    main()
