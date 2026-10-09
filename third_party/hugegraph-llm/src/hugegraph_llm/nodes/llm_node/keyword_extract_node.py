#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from typing import Any, Dict

from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.llm_op.keyword_extract import KeywordExtract
from hugegraph_llm.utils.log import log


class KeywordExtractNode(BaseNode):
    operator: KeywordExtract

    """
    Keyword extraction node, responsible for extracting keywords from query text.
    """

    def node_init(self):
        """
        Initialize the keyword extraction operator.
        """
        max_keywords = self.wk_input.max_keywords if self.wk_input.max_keywords is not None else 5
        extract_template = self.wk_input.keywords_extract_prompt

        self.operator = KeywordExtract(
            text=self.wk_input.query,
            max_keywords=max_keywords,
            extract_template=extract_template,
        )
        return super().node_init()

    def operator_schedule(self, data_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the keyword extraction operation.
        """
        try:
            # Perform keyword extraction
            result = self.operator.run(data_json)
            if "keywords" not in result:
                log.warning("Keyword extraction result missing 'keywords' field")
                result["keywords"] = []

            log.info("Extracted keywords: %s", result.get("keywords", []))

            return result

        except ValueError as e:
            log.error("Keyword extraction failed: %s", e)
            # Add error flag to indicate failure
            error_result = data_json.copy()
            error_result["error"] = str(e)
            error_result["keywords"] = []
            return error_result
