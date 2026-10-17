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

"""Small scripted domains for exercising the real engine and batch."""

from hugegraph_llm.extraction_runtime.v1 import ChunkInput, Issue, ReviewResult


class ScriptedBundle:
    def __init__(self, *, initial=1, repaired=2, decisions=("pass",), fail_at=None):
        self.initial = initial
        self.repaired = repaired
        self.decisions = iter(decisions)
        self.fail_at = fail_at
        self.calls = []
        self.validated = []
        self.repair_issues = []

    def _call(self, stage):
        self.calls.append(stage)
        if self.fail_at == stage:
            raise ValueError("scripted failure")

    def extract(self, chunk: ChunkInput) -> dict:
        self._call("extract")
        return {"value": self.initial, "chunk": chunk.index}

    def validate(self, graph, chunk):
        self._call("validate")
        self.validated.append(graph["value"])
        graph["normalized"] = True
        return [Issue("value", "must be non-negative")] if graph["value"] < 0 else []

    def review(self, graph, chunk):
        self._call("review")
        assert graph["normalized"]
        decision = next(self.decisions)
        return ReviewResult(decision, [Issue("value", "old review issue")] if decision != "pass" else [])

    def repair(self, graph, chunk, issues):
        self._call("repair")
        self.repair_issues.append(issues)
        return {"value": self.repaired, "chunk": chunk.index}
