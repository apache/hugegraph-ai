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

import logging

import pytest

from hugegraph_llm.config.models import base_config
from hugegraph_llm.utils.log import log
from tests.fixtures.saved_config import save_chat

pytestmark = pytest.mark.contract


def test_save_clear_and_test_errors_do_not_expose_secrets(saved_config, monkeypatch, caplog):
    settings, _, client = saved_config
    log.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.DEBUG):
            response = save_chat(client)
            assert response.status_code == 201
            from hugegraph_llm.models.llms import init_llm

            def fail(*args, **kwargs):
                raise RuntimeError("synthetic-user-key synthetic-provider-secret")

            monkeypatch.setattr(init_llm.OpenAIClient, "generate", fail)
            tested = client.post("/config/model/chat/test")
            assert tested.status_code == 502
            invalid = save_chat(client, api_key="", api_base="http://another.invalid")
            assert invalid.status_code == 400
            assert settings.openai_chat_api_key == "synthetic-user-key"
            assert "synthetic-user-key" in base_config.settings_path().read_text()
        for secret in ("synthetic-user-key", "synthetic-provider-secret"):
            assert secret not in caplog.text + response.text + tested.text + invalid.text
    finally:
        log.removeHandler(caplog.handler)
