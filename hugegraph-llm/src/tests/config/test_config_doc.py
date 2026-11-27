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
from pathlib import Path

import pytest
from pydantic import AliasChoices

from hugegraph_llm.config import AdminConfig, HugeGraphConfig, IndexConfig, LLMConfig

pytestmark = pytest.mark.unit

CONFIG_DOC = Path(__file__).resolve().parents[3] / "config.md"
SETTINGS_CLASSES = (HugeGraphConfig, AdminConfig, LLMConfig, IndexConfig)


def _settings_names():
    fields, aliases = set(), set()
    for cls in SETTINGS_CLASSES:
        for name, info in cls.model_fields.items():
            fields.add(name.upper())
            alias = info.validation_alias
            choices = alias.choices if isinstance(alias, AliasChoices) else [alias]
            aliases.update(c.upper() for c in choices if isinstance(c, str))
    return fields, aliases


def _documented_names():
    text = CONFIG_DOC.read_text(encoding="utf-8")
    return set(re.findall(r"^\|\s*`([A-Z0-9_]+)`", text, re.MULTILINE))


def test_every_setting_is_documented():
    fields, _ = _settings_names()
    missing = sorted(fields - _documented_names())
    assert not missing, f"add these settings to {CONFIG_DOC.name}: {missing}"


def test_every_documented_setting_exists():
    fields, aliases = _settings_names()
    stale = sorted(_documented_names() - fields - aliases)
    assert not stale, f"{CONFIG_DOC.name} documents unknown settings: {stale}"
