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

from hugegraph_llm.config import llm_settings
from hugegraph_llm.models.rerankers.cohere import CohereReranker
from hugegraph_llm.models.rerankers.siliconflow import SiliconReranker


class Rerankers:
    def __init__(self):
        self.reranker_type = llm_settings.reranker_type

    def get_reranker(self):
        if self.reranker_type == "cohere":
            return CohereReranker(
                api_key=llm_settings.reranker_api_key,
                base_url=llm_settings.cohere_base_url,
                model=llm_settings.reranker_model,
            )
        if self.reranker_type == "siliconflow":
            return SiliconReranker(api_key=llm_settings.reranker_api_key, model=llm_settings.reranker_model)
        raise Exception("Reranker type is not supported!")
