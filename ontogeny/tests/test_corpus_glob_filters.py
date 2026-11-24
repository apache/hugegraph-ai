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

import os
from pathlib import Path

import pytest

from ontogeny.core.models import DocumentCfg
from ontogeny.documents.corpus import scan, scan_incremental


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


def test_subdirectory_excludes_do_not_prune_the_corpus_root(tmp_path, monkeypatch):
    (tmp_path / "keep.md").write_text("keep")
    nested = tmp_path / "private"
    nested.mkdir()
    scandir = os.scandir

    def reject_nested_walk(path):
        assert path not in (nested, str(nested))
        return scandir(path)

    monkeypatch.setattr(os, "scandir", reject_nested_walk)
    cfg = DocumentCfg(exclude=["*/**"])
    assert [doc.rel for doc in scan(tmp_path, cfg, store_name="docs")] == ["keep.md"]


@pytest.mark.parametrize(
    ("selector", "exclude", "unreadable"),
    [
        ("public/*.md", [], False),
        ("public/[a-z]*/readable.md", [], False),
        ("*.md", ["notes/private*"], False),
        ("*.md", ["**/notes/private*"], False),
        ("*.md", ["private*"], True),
        ("*.md", ["notes/private*/secret.md"], True),
        ("*/private-data/*.md", [], True),
        ("*.md", [], True),
    ],
)
def test_coverage_only_counts_subtrees_that_might_match(tmp_path, monkeypatch, selector, exclude, unreadable):
    blocked = tmp_path / "notes" / "private-data"
    blocked.mkdir(parents=True)
    (blocked / "unknown.md").write_text("unreadable")
    readable = tmp_path / "public" / "nested" / "readable.md"
    readable.parent.mkdir(parents=True)
    readable.write_text("readable")
    scandir = os.scandir

    def deny_blocked(path):
        if Path(path) == blocked:
            raise PermissionError(13, "Permission denied", path)
        return scandir(path)

    monkeypatch.setattr(os, "scandir", deny_blocked)
    docs, _, failed = scan_incremental(tmp_path, DocumentCfg(exclude=exclude), selector, store_name="docs")
    expected = [] if selector == "*/private-data/*.md" else [readable]
    assert [doc.path for doc in docs] == expected
    assert failed == ({blocked} if unreadable else set())
