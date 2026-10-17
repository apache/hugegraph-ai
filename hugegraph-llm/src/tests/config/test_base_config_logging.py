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


"""Keep configuration values in storage, without copying them into diagnostics."""

import logging
from unittest.mock import Mock

import pytest
from dotenv import dotenv_values, set_key
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ConfigDict, ValidationError

from hugegraph_llm import config
from hugegraph_llm.api import rag_api
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config
from hugegraph_llm.demo.rag_demo import configs_block

pytestmark = pytest.mark.contract
ROLES = ("chat", "extract", "text2gql")


@pytest.fixture
def captured_logs(caplog, tmp_path):
    # This logger does not propagate to pytest's root handler. Attach pytest's
    # real capture handler and a real file handler without replacing the logger.
    logger = base_config.log
    log_file = tmp_path / "configuration.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(caplog.handler)
    logger.addHandler(file_handler)
    try:
        with caplog.at_level(logging.DEBUG, logger=logger.name):
            yield caplog, log_file
    finally:
        logger.removeHandler(caplog.handler)
        logger.removeHandler(file_handler)
        file_handler.close()


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    settings = LLMConfig.model_construct()
    for field in settings.model_dump():
        if field.endswith("api_key"):
            setattr(settings, field, "synthetic-old-key")
    for role in ROLES:
        setattr(settings, f"{role}_llm_type", "openai")
        setattr(settings, f"openai_{role}_api_base", "https://old.invalid/v1")
        setattr(settings, f"openai_{role}_language_model", "old-model")
    for module in (config, rag_api, configs_block):
        monkeypatch.setattr(module, "llm_settings", settings)
    env_file = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(env_file))
    # The constructor also lets pydantic load its configured env_file; isolate
    # that path too, so constructor-failure tests cannot read the project .env.
    monkeypatch.setitem(LLMConfig.model_config, "env_file", str(env_file))
    return settings, env_file


def seed_file(settings, env_file, *, omit=()):
    env_file.write_text(
        "".join(
            f"{key.upper()}={value if value is not None else ''}\n"
            for key, value in settings.model_dump().items()
            if key not in omit
        ),
        encoding="utf-8",
    )


def assert_values_absent(captured_logs, *values):
    captured, log_file = captured_logs
    for output in (captured.text, log_file.read_text(encoding="utf-8")):
        for value in values:
            assert value not in output


def test_successful_config_api_persists_all_role_keys_without_logging_values(
    isolated_settings, captured_logs, monkeypatch
):
    settings, env_file = isolated_settings
    seed_file(settings, env_file)
    submitted_key = "synthetic-private-api-key"
    transport = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr(configs_block.requests, "post", transport)
    router = APIRouter()
    rag_api.rag_http_api(
        router,
        Mock(),
        Mock(),
        Mock(),
        configs_block.apply_llm_config,
        configs_block.apply_embedding_config,
        configs_block.apply_reranker_config,
        Mock(),
    )
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/config/llm",
            json={
                "llm_type": "openai",
                "api_key": submitted_key,
                "api_base": "https://new.invalid/v1",
                "language_model": "new-model",
            },
        )

    assert response.status_code == 201
    transport.assert_called_once_with(
        "https://new.invalid/v1/chat/completions",
        headers={"Authorization": f"Bearer {submitted_key}"},
        params=None,
        json={"model": "new-model", "temperature": 0.01, "messages": [{"role": "user", "content": "test"}]},
        timeout=(1.0, 5.0),
        auth=None,
    )
    disk = dotenv_values(env_file)
    for role in ROLES:
        field = f"openai_{role}_api_key"
        assert getattr(settings, field) == submitted_key
        assert disk[field.upper()] == submitted_key
        assert field.upper() in captured_logs[0].text
    assert str(env_file) in captured_logs[0].text
    assert submitted_key not in response.text
    assert_values_absent(captured_logs, submitted_key)


def test_file_to_memory_sync_does_not_log_old_or_new_value(isolated_settings, captured_logs):
    settings, env_file = isolated_settings
    old_value, new_value = "synthetic-private-old", "synthetic-private-new"
    settings.openai_chat_api_key = old_value
    seed_file(settings, env_file)
    set_key(env_file, "OPENAI_CHAT_API_KEY", new_value, quote_mode="never")

    settings.check_env()

    assert settings.openai_chat_api_key == new_value
    assert dotenv_values(env_file)["OPENAI_CHAT_API_KEY"] == new_value
    assert "OPENAI_CHAT_API_KEY" in captured_logs[0].text
    assert_values_absent(captured_logs, old_value, new_value)


def test_missing_config_field_is_saved_without_logging_value(isolated_settings, captured_logs):
    settings, env_file = isolated_settings
    value = "synthetic-private-missing"
    settings.openai_chat_api_key = value
    seed_file(settings, env_file, omit=("openai_chat_api_key",))

    settings.check_env()

    assert settings.openai_chat_api_key == value
    assert dotenv_values(env_file)["OPENAI_CHAT_API_KEY"] == value
    assert "OPENAI_CHAT_API_KEY" in captured_logs[0].text
    assert_values_absent(captured_logs, value)


@pytest.mark.parametrize(
    ("field", "value", "private_fragment"),
    [
        ("openai_chat_language_model", "synthetic-private-model", "synthetic-private-model"),
        (
            "openai_chat_api_base",
            "https://user:synthetic-private-url@service.invalid/v1?token=synthetic-private-url",
            "synthetic-private-url",
        ),
    ],
)
def test_ordinary_field_values_are_not_logged(isolated_settings, captured_logs, field, value, private_fragment):
    settings, env_file = isolated_settings
    seed_file(settings, env_file)
    setattr(settings, field, value)

    settings.update_env()

    assert dotenv_values(env_file)[field.upper()] == value
    assert field.upper() in captured_logs[0].text
    assert_values_absent(captured_logs, value, private_fragment)


@pytest.mark.parametrize("value", ["private-ctor", "private-ctor-prefix-" + "x" * 80 + "-private-ctor-suffix"])
def test_constructor_error_logs_category_without_input_value(isolated_settings, captured_logs, value):
    _, env_file = isolated_settings
    # No environment keys are loaded into os.environ during this constructor.
    env_file.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        LLMConfig(language=value)

    assert any(error["loc"] == ("language",) and error["input"] == value for error in exc_info.value.errors())
    # Pydantic may abbreviate long input_value text; fragments catch that leak.
    assert_values_absent(captured_logs, value, "private-ctor-prefix", "private-ctor-suffix")
    assert "ValidationError" in captured_logs[0].text
    assert str(env_file) in captured_logs[0].text
    assert env_file.read_text(encoding="utf-8") == ""


def test_check_env_error_logs_category_and_preserves_validation_error(isolated_settings, captured_logs):
    _, env_file = isolated_settings

    class ValidatedConfig(base_config.BaseConfig):
        model_config = ConfigDict(validate_assignment=True)
        number: int = 1

    settings = ValidatedConfig.model_construct(number=1)
    value = "private-sync-error"
    env_file.write_text(f"NUMBER={value}\n", encoding="utf-8")
    file_before = env_file.read_bytes()

    with pytest.raises(ValidationError) as exc_info:
        settings.check_env()

    assert exc_info.value.errors()[0]["input"] == value
    assert settings.number == 1
    assert env_file.read_bytes() == file_before
    assert_values_absent(captured_logs, value)
    assert "ValidationError" in captured_logs[0].text
    assert str(env_file) in captured_logs[0].text
