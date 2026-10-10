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


import re
from typing import Any, Dict, List, Optional

import jieba

from hugegraph_llm.config import llm_settings
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.models.llms.init_llm import LLMs
from hugegraph_llm.operators.common_op.nltk_helper import NLTKHelper


class WordExtract:
    def __init__(
        self,
        text: Optional[str] = None,
        llm: Optional[BaseLLM] = None,
    ):
        self._llm = llm
        self._query = text
        # Use English by default when the value is missing or unsupported.
        lang_raw = llm_settings.language.lower()
        self._language = "chinese" if lang_raw == "cn" else "english"

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if self._query is None:
            self._query = context.get("query")
            assert self._query is not None, "No query for keywords extraction."
        else:
            context["query"] = self._query

        if self._llm is None:
            self._llm = LLMs().get_extract_llm()
            assert isinstance(self._llm, BaseLLM), "Invalid LLM Object."

        keywords = jieba.lcut(self._query)
        keywords = self._filter_keywords(keywords, lowercase=False)

        context["keywords"] = keywords
        from hugegraph_llm.utils.log import log

        log.info("KEYWORDS: %s", context["keywords"])
        return context

    def _filter_keywords(
        self,
        keywords: List[str],
        lowercase: bool = True,
    ) -> List[str]:
        if lowercase:
            keywords = [w.lower() for w in keywords]

        # if the keyword consists of multiple words, split into sub-words
        # (removing stopwords)
        results = set()
        for token in keywords:
            results.add(token)
            sub_tokens = re.findall(r"\w+", token)
            if len(sub_tokens) > 1:
                results.update({w for w in sub_tokens if w not in NLTKHelper().stopwords(lang=self._language)})

        return list(results)
