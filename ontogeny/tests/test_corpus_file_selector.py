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

"""Literal file selectors must not expand to sibling documents."""

from pathlib import Path

import pytest

from ontogeny.core.models import DocumentCfg
from ontogeny.documents.corpus import resolve_selector, scan
from ontogeny.errors import StoreError


@pytest.mark.parametrize("directory", ["", "nested"])
def test_file_selector_only_returns_selected_file(tmp_path, directory):
    folder = tmp_path / directory
    folder.mkdir(exist_ok=True)
    target = folder / "selected.md"
    target.write_text("selected")
    (folder / "sibling.md").write_text("sibling")
    docs = scan(tmp_path, DocumentCfg(), target.relative_to(tmp_path).as_posix(), store_name="docs")
    assert [doc.path for doc in docs] == [target]
    assert docs[0].rel == "selected.md"


def test_file_selector_respects_excludes(tmp_path):
    (tmp_path / "selected.md").write_text("selected")
    docs = scan(tmp_path, DocumentCfg(exclude=["selected.md"]), "selected.md", store_name="docs")
    assert docs == []


def test_directory_selector_keeps_all_matching_files(tmp_path):
    folder = tmp_path / "nested"
    folder.mkdir()
    for name in ["a.md", "b.md"]:
        (folder / name).write_text(name)
    assert [doc.rel for doc in scan(tmp_path, DocumentCfg(), "nested", store_name="docs")] == ["a.md", "b.md"]


def test_file_selector_resolves_symlinked_parent(tmp_path):
    folder = tmp_path / "nested"
    folder.mkdir()
    target = folder / "selected.md"
    target.write_text("selected")
    (folder / "sibling.md").write_text("sibling")
    (tmp_path / "alias").symlink_to(folder, target_is_directory=True)

    direct = scan(tmp_path, DocumentCfg(), "nested/selected.md", store_name="docs")
    through_alias = scan(tmp_path, DocumentCfg(), "alias/selected.md", store_name="docs")
    assert len(direct) == 1
    assert through_alias == direct
    assert scan(tmp_path, DocumentCfg(exclude=["nested/**"]), "alias/selected.md", store_name="docs") == []


def test_directory_selector_rejects_base_outside_corpus(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (tmp_path / "outside.md").write_text("outside the corpus")
    with pytest.raises(StoreError, match="escapes the corpus root"):
        scan(root, DocumentCfg(), "../outside.md", store_name="docs")


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("logical-table", ["note.md"]),
        ("./logical-table", []),
        ("missing/file.md", []),
        ("missing.md", []),
    ],
)
def test_only_bare_missing_identifier_falls_back_to_corpus(tmp_path, selector, expected):
    (tmp_path / "note.md").write_text("a document")
    assert [doc.rel for doc in scan(tmp_path, DocumentCfg(), selector, store_name="docs")] == expected


def test_unreadable_bare_selector_is_not_treated_as_missing(tmp_path, monkeypatch):
    lstat = Path.lstat

    def deny_lstat(self):
        if self == tmp_path / "protected":
            raise PermissionError("cannot check selector")
        return lstat(self)

    monkeypatch.setattr(Path, "lstat", deny_lstat)
    assert resolve_selector(tmp_path, "protected") == "protected"
