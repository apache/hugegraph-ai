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

from typing import List, Optional

import requests


class SiliconReranker:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model

    def get_rerank_lists(self, query: str, documents: List[str], top_n: Optional[int] = None) -> List[str]:
        if not documents:
            raise ValueError("Documents list cannot be empty")

        if top_n is None:
            top_n = len(documents)

        if top_n < 0:
            raise ValueError("'top_n' should be non-negative")

        if top_n > len(documents):
            raise ValueError("'top_n' should be less than or equal to the number of documents")

        if top_n == 0:
            return []

        url = "https://api.siliconflow.cn/v1/rerank"
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "return_documents": False,
            "max_chunks_per_doc": 1024,
            "overlap_tokens": 80,
            "top_n": top_n,
        }
        from pyhugegraph.utils.constants import Constants

        headers = {
            "accept": Constants.HEADER_CONTENT_TYPE,
            "content-type": Constants.HEADER_CONTENT_TYPE,
            "authorization": f"Bearer {self.api_key}",
        }
        response = requests.post(url, json=payload, headers=headers, timeout=(1.0, 10.0))
        response.raise_for_status()  # Raise an error for bad status codes
        results = response.json()["results"]
        sorted_docs = [documents[item["index"]] for item in results]
        return sorted_docs
