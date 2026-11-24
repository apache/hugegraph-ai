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

"""Glob selectors must narrow the store's configured corpus."""

import pytest

from ontogeny.core.models import DocumentCfg
from ontogeny.documents.corpus import scan


@pytest.mark.parametrize("selector", ["*.md", "nested/*.md"])
def test_glob_respects_excludes(tmp_path, selector):
    folder = tmp_path / "nested" if selector.startswith("nested/") else tmp_path
    folder.mkdir(exist_ok=True)
    (folder / "keep.md").write_text("keep")
    (folder / "secret.md").write_text("secret")
    cfg = DocumentCfg(exclude=["secret.md"])
    docs = scan(tmp_path, cfg, selector, store_name="docs")
    assert [doc.path.name for doc in docs] == ["keep.md"]


def test_glob_respects_includes(tmp_path):
    (tmp_path / "keep.md").write_text("keep")
    (tmp_path / "skip.txt").write_text("skip")
    cfg = DocumentCfg(include=["**/*.md"])
    assert [doc.rel for doc in scan(tmp_path, cfg, "*", store_name="docs")] == ["keep.md"]


def test_glob_still_limits_matching_files(tmp_path):
    (tmp_path / "keep.md").write_text("keep")
    (tmp_path / "skip.txt").write_text("skip")
    assert [doc.rel for doc in scan(tmp_path, DocumentCfg(), "*.md", store_name="docs")] == ["keep.md"]
