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

import asyncio
from unittest.mock import Mock

import gradio as gr
import pytest
from pydantic import ValidationError

from hugegraph_llm.config import llm_settings
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.demo.rag_demo import rag_block, text2gremlin_block

pytestmark = pytest.mark.contract


def test_limit_configuration_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HUGEGRAPH_LLM_SETTINGS_PATH", str(tmp_path / "settings.yaml"))
    monkeypatch.setenv("RAG_QUERY_MAX_LENGTH", "123")
    assert LLMConfig(_env_file=None).rag_query_max_length == 123
    monkeypatch.setenv("RAG_QUERY_MAX_LENGTH", "0")
    with pytest.raises(ValidationError):
        LLMConfig(_env_file=None)


def test_demo_paths_reject_long_queries_before_scheduling(monkeypatch):
    monkeypatch.setattr(llm_settings, "rag_query_max_length", 5)
    scheduler = Mock()
    monkeypatch.setattr(rag_block.SchedulerSingleton, "get_instance", lambda: scheduler)
    args = ("toolong", True, False, False, False, 0.5, "bleu", False, "", "", "")

    with pytest.raises(gr.Error, match="maximum allowed length of 5"):
        rag_block.rag_answer(*args)

    async def consume():
        return [item async for item in rag_block.rag_answer_streaming(*args)]

    with pytest.raises(gr.Error, match="maximum allowed length of 5"):
        asyncio.run(consume())

    with pytest.raises(ValueError, match="maximum allowed length of 5"):
        text2gremlin_block.graph_rag_recall("toolong", 1, "bleu", False, "", "", 30, 20, 0.9, 1)
    scheduler.schedule_flow.assert_not_called()
    scheduler.schedule_stream_flow.assert_not_called()
