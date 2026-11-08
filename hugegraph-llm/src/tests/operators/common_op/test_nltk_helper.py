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
import unittest
from unittest.mock import Mock

import pytest


class TestNLTKHelper(unittest.TestCase):
    def test_stopwords(self):
        from hugegraph_llm.operators.common_op.nltk_helper import NLTKHelper

        nltk_helper = NLTKHelper()
        stopwords = nltk_helper.stopwords()
        print(stopwords)


@pytest.mark.contract
@pytest.mark.parametrize("language", ["english", "chinese"])
@pytest.mark.parametrize("user_override", [False, True])
@pytest.mark.parametrize("existing_cache", [False, True])
def test_external_root_keeps_bundled_stopwords_available_offline(
    tmp_path, monkeypatch, language, user_override, existing_cache
):
    from hugegraph_llm.operators.common_op import nltk_helper

    root = tmp_path / "fresh-resources"
    if user_override:
        corpus = root / "nltk_data/corpora/stopwords"
        corpus.mkdir(parents=True)
        (corpus / language).write_text("operator-stopword\n", encoding="utf-8")
    before = sorted(root.rglob("*"))
    monkeypatch.setattr(nltk_helper, "resource_path", str(root))
    cached_root = tmp_path / "existing-nltk"
    cached = cached_root / "corpora/stopwords"
    cached.mkdir(parents=True)
    (cached / language).write_text("cached-stopword\n", encoding="utf-8")
    user_path = str(root / "nltk_data")
    packaged_path = str(nltk_helper.PACKAGED_RESOURCES / "nltk_data")
    existing = [str(cached_root), packaged_path, user_path, str(cached_root)] if existing_cache else []
    monkeypatch.setattr(nltk_helper.nltk.data, "path", existing)
    monkeypatch.setattr(nltk_helper.NLTKHelper, "_stopwords", {"english": None, "chinese": None})
    monkeypatch.setenv("HG_AI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NLTK_DATA", str(tmp_path / "empty-cache"))
    download = Mock(side_effect=AssertionError("offline deployment must use installed corpora"))
    monkeypatch.setattr(nltk_helper.nltk, "download", download)

    words = nltk_helper.NLTKHelper().stopwords(language)
    assert words
    if user_override:
        assert words == ["operator-stopword"]
    else:
        assert ("the" if language == "english" else "的") in words
    download.assert_not_called()
    assert sorted(root.rglob("*")) == before
    assert nltk_helper.nltk.data.path[:3] == [str(tmp_path / "empty-cache"), user_path, packaged_path]
    if existing_cache:
        assert nltk_helper.nltk.data.path.count(str(cached_root)) == 1
    paths = list(nltk_helper.nltk.data.path)
    nltk_helper._add_resource_search_paths()
    assert nltk_helper.nltk.data.path == paths
    assert len(paths) == len(set(paths))


@pytest.mark.contract
@pytest.mark.parametrize("language", ["english", "chinese"])
def test_partial_external_corpus_falls_back_per_language(tmp_path, monkeypatch, language):
    from hugegraph_llm.operators.common_op import nltk_helper

    root = tmp_path / "resources"
    corpus = root / "nltk_data/corpora/stopwords"
    corpus.mkdir(parents=True)
    other = "chinese" if language == "english" else "english"
    (corpus / other).write_text("external-word\n", encoding="utf-8")
    monkeypatch.setattr(nltk_helper, "resource_path", str(root))
    monkeypatch.setattr(nltk_helper.nltk.data, "path", [])
    monkeypatch.setenv("NLTK_DATA", str(tmp_path / "empty"))
    monkeypatch.setenv("HG_AI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(nltk_helper.NLTKHelper, "_stopwords", {})
    monkeypatch.setattr(nltk_helper.nltk, "download", Mock(side_effect=AssertionError("offline")))
    helper = nltk_helper.NLTKHelper()
    assert helper.stopwords(other) == ["external-word"]
    assert ("the" if language == "english" else "的") in helper.stopwords(language)


@pytest.mark.contract
def test_explicit_nltk_data_precedes_packaged_and_resource_defaults(tmp_path, monkeypatch):
    from hugegraph_llm.operators.common_op import nltk_helper

    roots = [tmp_path / "first", tmp_path / "second"]
    for root, language in zip(roots, ["english", "chinese"]):
        corpus = root / "corpora/stopwords"
        corpus.mkdir(parents=True)
        (corpus / language).write_text(f"custom-{language}\n", encoding="utf-8")
    monkeypatch.setenv("NLTK_DATA", os.pathsep.join(map(str, roots)))
    monkeypatch.setattr(nltk_helper.nltk.data, "path", [])
    monkeypatch.setattr(nltk_helper.NLTKHelper, "_stopwords", {})
    monkeypatch.setenv("HG_AI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(nltk_helper.nltk, "download", Mock(side_effect=AssertionError("offline")))
    helper = nltk_helper.NLTKHelper()
    assert helper.stopwords("english") == ["custom-english"]
    assert helper.stopwords("chinese") == ["custom-chinese"]
    assert nltk_helper.nltk.data.path[:2] == list(map(str, roots))


@pytest.mark.contract
@pytest.mark.parametrize("language", ["english", "chinese"])
def test_user_zip_stopwords_override_with_per_language_fallback(tmp_path, monkeypatch, language):
    import zipfile

    from hugegraph_llm.operators.common_op import nltk_helper

    root = tmp_path / "nltk"
    (root / "corpora").mkdir(parents=True)
    archive = root / "corpora/stopwords.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(f"stopwords/{language}", "operator-zip-word\n")
    before = archive.read_bytes()
    monkeypatch.setenv("NLTK_DATA", str(root))
    monkeypatch.setattr(nltk_helper.nltk.data, "path", [])
    monkeypatch.setattr(nltk_helper, "resource_path", str(tmp_path / "resources"))
    monkeypatch.setattr(nltk_helper.NLTKHelper, "_stopwords", {})
    monkeypatch.setattr(nltk_helper.nltk, "download", Mock(side_effect=AssertionError("offline")))
    helper = nltk_helper.NLTKHelper()
    assert helper.stopwords(language) == ["operator-zip-word"]
    other = "chinese" if language == "english" else "english"
    assert ("the" if other == "english" else "的") in helper.stopwords(other)
    assert archive.read_bytes() == before
