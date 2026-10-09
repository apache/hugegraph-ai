# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""agent-builtin-llm -- the builtin LLM agent engine (agent-paradigm §3 form C).

Registers a *factory* for engine kind ``builtin-llm`` into ``sc.agent_engines``;
the /run dispatcher builds the engine per run, so the factory always binds the
live broker and the live LLM gateway. This engine has no privileges -- it is
the reference implementation of the AgentEngine contract: it drives its
sessions over MCP (same tool surface, same protocol as external agents), and
only degrades to in-process broker calls when the optional mcp extra is absent.
"""
from .engine import (BrokerExecutor, BuiltinLlmEngine, EngineResult, McpExecutor,
                     ToolExecutor)

__all__ = ["BrokerExecutor", "BuiltinLlmEngine", "EngineResult", "McpExecutor",
           "ToolExecutor", "register"]


def register(sc, host) -> None:
    sc.agent_engines["builtin-llm"] = lambda sc: BuiltinLlmEngine(sc, sc.llm)
