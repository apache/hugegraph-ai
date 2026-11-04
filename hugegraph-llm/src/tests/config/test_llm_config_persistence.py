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


"""Exercise deployment configuration through the real settings sources and files."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import yaml

from hugegraph_llm import config
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config
from tests.fixtures.saved_config import save_chat

pytestmark = pytest.mark.contract


def test_test_failure_never_rolls_back_a_concurrent_save(saved_config, monkeypatch):
    settings, _, client = saved_config
    assert save_chat(client).status_code == 201
    entered, release = Event(), Event()
    from hugegraph_llm.models.llms import init_llm

    def unavailable(_client, **kwargs):
        entered.set()
        assert release.wait(10)
        raise RuntimeError("synthetic provider outage")

    monkeypatch.setattr(init_llm.OpenAIClient, "generate", unavailable)
    with ThreadPoolExecutor(2) as pool:
        testing = pool.submit(client.post, "/config/model/chat/test")
        try:
            assert entered.wait(10)
            saved = pool.submit(save_chat, client, api_key="", language_model="newer-model")
            assert saved.result(5).status_code == 201  # Network probe must not hold config lock.
        finally:
            release.set()
        assert testing.result(5).status_code == 502
    assert settings.openai_chat_language_model == LLMConfig().openai_chat_language_model == "newer-model"


def test_concurrent_role_saves_preserve_both_connections(saved_config):
    _, _, client = saved_config
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda role: save_chat(client, role=role, language_model=role), ("chat", "extract")))
    assert all(r.status_code == 201 for r in responses)
    reloaded = LLMConfig()
    assert reloaded.openai_chat_language_model == "chat"
    assert reloaded.openai_extract_language_model == "extract" and not reloaded.extract_use_chat
    document = yaml.safe_load(base_config.settings_path().read_text())
    assert set(document["llm"]) == {"chat", "extract"}


def test_snapshot_is_detached_from_later_save(saved_config):
    _, _, client = saved_config
    save_chat(client)
    snapshot = config.snapshot_llm_settings()
    save_chat(client, api_key="", language_model="newer-model")
    assert snapshot.openai_chat_language_model == "saved-model"
    assert config.snapshot_llm_settings().openai_chat_language_model == "newer-model"
