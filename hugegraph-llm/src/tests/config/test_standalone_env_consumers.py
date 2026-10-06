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

import os
from types import SimpleNamespace

import pytest

from hugegraph_llm.config.models import base_config
from hugegraph_llm.operators.common_op import nltk_helper

pytestmark = pytest.mark.unit


def test_cache_directory_can_be_configured_only_in_dotenv(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    env_file = tmp_path / ".env"
    env_file.write_text(f"HG_AI_CACHE_DIR={cache_dir.as_posix()}\n", encoding="utf-8")
    monkeypatch.setattr(base_config, "env_path", str(env_file))
    monkeypatch.delenv("HG_AI_CACHE_DIR", raising=False)

    assert nltk_helper.NLTKHelper.get_cache_dir() == str(cache_dir)
    assert cache_dir.is_dir()
    assert "HG_AI_CACHE_DIR" not in os.environ


@pytest.mark.parametrize("method", ["stopwords", "check_nltk_data"])
def test_nltk_data_directory_can_be_configured_only_in_dotenv(tmp_path, monkeypatch, method):
    data_dir = tmp_path / "nltk-data"
    env_file = tmp_path / ".env"
    env_file.write_text(f"NLTK_DATA={data_dir.as_posix()}\n", encoding="utf-8")
    monkeypatch.setattr(base_config, "env_path", str(env_file))
    monkeypatch.delenv("NLTK_DATA", raising=False)
    monkeypatch.setattr(nltk_helper.nltk.data, "path", [])
    monkeypatch.setattr(nltk_helper.nltk.data, "find", lambda _: "present")
    monkeypatch.setattr(nltk_helper, "stopwords", SimpleNamespace(words=lambda _: ["word"]))
    monkeypatch.setattr(nltk_helper.NLTKHelper, "_stopwords", {"english": None})

    getattr(nltk_helper.NLTKHelper(), method)()

    assert data_dir.as_posix() in nltk_helper.nltk.data.path
    assert "NLTK_DATA" not in os.environ
