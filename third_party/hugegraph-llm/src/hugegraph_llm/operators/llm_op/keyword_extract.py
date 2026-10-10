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
import time
from typing import Any, Dict, Optional

from hugegraph_llm.config import llm_settings, prompt
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.models.llms.init_llm import LLMs
from hugegraph_llm.operators.document_op.textrank_word_extract import (
    MultiLingualTextRank,
)
from hugegraph_llm.utils.log import log

KEYWORDS_EXTRACT_TPL = prompt.keywords_extract_prompt


class KeywordExtract:
    def __init__(
        self,
        text: Optional[str] = None,
        llm: Optional[BaseLLM] = None,
        max_keywords: int = 5,
        extract_template: Optional[str] = None,
    ):
        self._llm = llm
        self._query = text
        self._language = llm_settings.language.lower()
        self._max_keywords = max_keywords
        self._extract_template = extract_template or KEYWORDS_EXTRACT_TPL
        self._extract_method = llm_settings.keyword_extract_type.lower()
        self._textrank_model = MultiLingualTextRank(keyword_num=max_keywords, window_size=llm_settings.window_size)

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if self._query is None:
            self._query = context.get("query")
            assert self._query is not None, "No query for keywords extraction."
        else:
            context["query"] = self._query

        if self._llm is None:
            self._llm = LLMs().get_extract_llm()
            assert isinstance(self._llm, BaseLLM), "Invalid LLM Object."

        # Use English by default
        self._language = "chinese" if self._language == "cn" else "english"
        max_keyword_num = context.get("max_keywords", self._max_keywords)
        try:
            max_keyword_num = int(max_keyword_num)
        except (TypeError, ValueError):
            max_keyword_num = self._max_keywords
        self._max_keywords = max(1, max_keyword_num)

        method = (context.get("extract_method", self._extract_method) or "LLM").strip().lower()
        if method == "llm":
            # LLM method
            ranks = self._extract_with_llm()
        elif method == "textrank":
            # TextRank method
            ranks = self._extract_with_textrank()
        elif method == "hybrid":
            # Hybrid method
            ranks = self._extract_with_hybrid()
        else:
            log.warning("Invalid extract_method %s", method)
            raise ValueError(f"Invalid extract_method: {method}")

        keywords = [] if not ranks else sorted(ranks, key=ranks.get, reverse=True)
        keywords = [k.replace("'", "") for k in keywords]
        context["keywords"] = keywords[: self._max_keywords]
        log.info("User Query: %s\nKeywords: %s", self._query, context["keywords"])

        # extracting keywords & expanding synonyms increase the call count by 1
        context["call_count"] = context.get("call_count", 0) + 1
        return context

    def _extract_with_llm(self) -> Dict[str, float]:
        prompt_run = f"{self._extract_template.format(question=self._query, max_keywords=self._max_keywords)}"
        start_time = time.perf_counter()
        response = self._llm.generate(prompt=prompt_run)
        end_time = time.perf_counter()
        log.debug("LLM Keyword extraction time: %.2f seconds", end_time - start_time)
        keywords = self._extract_keywords_from_response(response=response, lowercase=False, start_token="KEYWORDS:")
        return keywords

    def _extract_with_textrank(self) -> Dict[str, float]:
        """TextRank mode extraction"""
        start_time = time.perf_counter()
        ranks = {}
        try:
            ranks = self._textrank_model.extract_keywords(self._query)
        except (TypeError, ValueError) as e:
            log.error("TextRank parameter error: %s", e)
        except MemoryError as e:
            log.critical("TextRank memory error (text too large?): %s", e)
        end_time = time.perf_counter()
        log.debug("TextRank Keyword extraction time: %.2f seconds", end_time - start_time)
        return ranks

    def _extract_with_hybrid(self) -> Dict[str, float]:
        """Hybrid mode extraction"""
        ranks = {}

        if isinstance(llm_settings.hybrid_llm_weights, float):
            llm_weights = min(1.0, max(0.0, float(llm_settings.hybrid_llm_weights)))
        else:
            llm_weights = 0.5

        start_time = time.perf_counter()

        llm_scores = self._extract_with_llm()
        tr_scores = self._extract_with_textrank()
        lr_set = set(k for k in llm_scores)
        tr_set = set(k for k in tr_scores)

        log.debug("LLM extract results: %s", llm_scores)
        log.debug("TextRank extract results: %s", tr_scores)

        union_set = lr_set | tr_set
        for word in union_set:
            ranks[word] = 0
            if word in llm_scores:
                ranks[word] += llm_scores[word] * llm_weights
            if word in tr_scores:
                ranks[word] += tr_scores[word] * (1 - llm_weights)

        end_time = time.perf_counter()
        log.debug("Hybrid Keyword extraction time: %.2f seconds", end_time - start_time)
        return ranks

    def _extract_keywords_from_response(
        self,
        response: str,
        lowercase: bool = True,
        start_token: str = "",
    ) -> Dict[str, float]:
        results = {}

        # Strip markdown code fences before parsing
        response = re.sub(r"```\w*\n?", "", response)
        response = re.sub(r"```", "", response)
        response = response.strip()

        # use re.escape(start_token) if start_token contains special chars like */&/^ etc.
        matches = re.findall(rf"{start_token}([^\n]+\n?)", response)

        for match in matches:
            match = match.strip()
            for k in re.split(r"[,，]+", match):
                item = k.strip()
                if not item:
                    continue
                try:
                    parts = re.split(r"[:：]", item, maxsplit=1)
                    if len(parts) != 2:
                        log.warning("Skipping malformed item: %s", item)
                        continue
                    word_raw, score_raw = parts[0].strip(), parts[1].strip()
                    if not word_raw:
                        continue
                    score_val = float(score_raw)
                    if not 0.0 <= score_val <= 1.0:
                        log.warning("Score out of range for %s: %s", word_raw, score_val)
                        score_val = min(1.0, max(0.0, score_val))
                    word_out = word_raw.lower() if lowercase else word_raw
                    results[word_out] = score_val
                except (ValueError, AttributeError) as e:
                    log.warning("Failed to parse item '%s': %s", item, e)
                    continue
        return results
