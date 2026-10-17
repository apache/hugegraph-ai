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

"""Run two reviewed chunks with the configured chat model and an inline schema."""

import json
from pathlib import Path

from hugegraph_llm.config import llm_settings
from hugegraph_llm.extraction_runtime.property_graph import PropertyGraphBundle
from hugegraph_llm.extraction_runtime.v1 import ChunkInput, ExtractionOptions, run_chunks_v1
from hugegraph_llm.models.llms.init_llm import get_chat_llm


def main() -> None:
    request = json.loads(Path(__file__).with_name("reviewed-extraction.json").read_text(encoding="utf-8"))

    def prepare(_chunk):
        return PropertyGraphBundle(
            llm=get_chat_llm(llm_settings, limit_output=False, raise_on_truncation=True), schema=request["schema"]
        )

    results = run_chunks_v1(
        chunks=[ChunkInput(index, text) for index, text in enumerate(request["texts"])],
        prepare=prepare,
        options=ExtractionOptions(**request["review_options"]),
    )
    print(json.dumps([result.as_dict() for result in results], ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
