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


from typing import Any, Dict, List

from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.llm_op.info_extract import extract_triples_by_regex


def generate_disambiguate_prompt(triples):
    return f"""
        Your task is to disambiguate the following triples:
        {triples}
        If the second element of the triples expresses the same meaning but in different ways,
        unify them and keep the most concise expression.

        For example, if the input is:
        [("Alice", "friend", "Bob"), ("Simon", "is friends with", "Bob")]

        The output should be:
        [("Alice", "friend", "Bob"), ("Simon", "friend", "Bob")]
        """


class DisambiguateData:
    def __init__(self, llm: BaseLLM) -> None:
        self.llm = llm

    def run(self, data: Dict) -> Dict[str, List[Any]]:
        # only disambiguate triples
        if "triples" in data:
            # TODO: ensure the logic here
            # log.debug(data)
            triples = data["triples"]
            prompt = generate_disambiguate_prompt(triples)
            llm_output = self.llm.generate(prompt=prompt)
            data["triples"] = []
            extract_triples_by_regex(llm_output, data)
            print(f"LLM {self.__class__.__name__} input:{prompt} \n output: {llm_output} \n data: {data}")
            data["call_count"] = data.get("call_count", 0) + 1

        return data
