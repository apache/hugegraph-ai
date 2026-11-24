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

"""Store filters stay relative to the corpus when selecting a subdirectory."""

import pytest

from ontogeny.core.models import DocumentCfg
from ontogeny.documents.corpus import scan


@pytest.mark.parametrize("selector", ["private", "private/note.md"])
def test_corpus_relative_exclusion_with_literal_selector(tmp_path, selector):
    folder = tmp_path / "private"
    folder.mkdir()
    (folder / "note.md").write_text("note")
    assert scan(tmp_path, DocumentCfg(exclude=["private/**"]), selector, store_name="docs") == []


@pytest.mark.parametrize("selector", ["public", "public/note.md"])
def test_corpus_relative_include_preserves_document_identity(tmp_path, selector):
    folder = tmp_path / "public"
    folder.mkdir()
    (folder / "note.md").write_text("note")
    before = scan(tmp_path, DocumentCfg(), selector, store_name="docs")
    filtered = scan(tmp_path, DocumentCfg(include=["public/*.md"]), selector, store_name="docs")
    assert len(filtered) == 1
    assert filtered[0].rel == before[0].rel == "note.md"
    assert filtered[0].doc_id == before[0].doc_id
    assert filtered[0].legacy_id == before[0].legacy_id


def test_basename_exclusion_still_applies_in_subdirectory(tmp_path):
    folder = tmp_path / "private"
    folder.mkdir()
    (folder / "note.md").write_text("note")
    assert scan(tmp_path, DocumentCfg(exclude=["note.md"]), "private", store_name="docs") == []


def test_exclude_wins_over_include_in_nested_directory(tmp_path):
    folder = tmp_path / "public" / "nested"
    folder.mkdir(parents=True)
    (folder / "note.md").write_text("note")
    cfg = DocumentCfg(include=["public/**/*.md"], exclude=["public/nested/**"])
    assert scan(tmp_path, cfg, "public/nested", store_name="docs") == []


def test_root_selector_behavior_is_unchanged(tmp_path):
    (tmp_path / "public.md").write_text("public")
    (tmp_path / "private.md").write_text("private")
    cfg = DocumentCfg(exclude=["private.md"])
    assert [doc.rel for doc in scan(tmp_path, cfg, store_name="docs")] == ["public.md"]
