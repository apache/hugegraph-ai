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

"""Prompt files must remain inside the configured package root."""

from types import SimpleNamespace

import pytest

from ontogeny.core.models import DocumentCfg
from ontogeny.documents.engine import DocumentError, DocumentService


def service_for(root):
    return DocumentService(SimpleNamespace(package_root=str(root)))


@pytest.mark.parametrize("absolute", [False, True])
def test_prompt_rejects_sibling_with_matching_directory_prefix(tmp_path, absolute):
    root = tmp_path / "package"
    root.mkdir()
    sibling = tmp_path / "package-extra"
    sibling.mkdir()
    (sibling / "prompt.txt").write_text("outside", encoding="utf-8")
    with pytest.raises(DocumentError, match="must stay inside"):
        prompt = str(sibling / "prompt.txt") if absolute else "../package-extra/prompt.txt"
        service_for(root)._instructions(DocumentCfg(prompt_file=prompt))


def test_prompt_accepts_file_inside_package(tmp_path):
    folder = tmp_path / "prompts"
    folder.mkdir()
    (folder / "extract.txt").write_text("提取提示词", encoding="utf-8")
    assert service_for(tmp_path)._instructions(DocumentCfg(prompt_file="prompts/extract.txt")) == "提取提示词"


def test_prompt_rejects_symlink_to_outside_package(tmp_path):
    root = tmp_path / "package"
    root.mkdir()
    outside = tmp_path / "package-extra"
    outside.mkdir()
    (outside / "prompt.txt").write_text("outside", encoding="utf-8")
    link = root / "prompts"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(DocumentError, match="must stay inside"):
        service_for(root)._instructions(DocumentCfg(prompt_file="prompts/prompt.txt"))


def test_prompt_reports_missing_file_inside_package(tmp_path):
    with pytest.raises(DocumentError, match="prompt_file not found"):
        service_for(tmp_path)._instructions(DocumentCfg(prompt_file="missing.txt"))


def test_prompt_accepts_normalized_path_inside_package(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompt.txt").write_text("inside", encoding="utf-8")
    assert service_for(tmp_path)._instructions(DocumentCfg(prompt_file="prompts/../prompt.txt")) == "inside"


def test_prompt_accepts_symlink_remaining_inside_package(tmp_path):
    target = tmp_path / "prompt.txt"
    target.write_text("inside", encoding="utf-8")
    try:
        (tmp_path / "alias.txt").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    assert service_for(tmp_path)._instructions(DocumentCfg(prompt_file="alias.txt")) == "inside"


def test_absent_prompt_configuration_still_returns_none(tmp_path):
    assert service_for(tmp_path)._instructions(DocumentCfg()) is None
