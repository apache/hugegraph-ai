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
def test_external_root_keeps_bundled_stopwords_available_offline(tmp_path, monkeypatch, language, user_override):
    from nltk.corpus.reader import WordListCorpusReader
    from nltk.corpus.util import LazyCorpusLoader

    from hugegraph_llm.operators.common_op import nltk_helper

    root = tmp_path / "fresh-resources"
    if user_override:
        corpus = root / "nltk_data/corpora/stopwords"
        corpus.mkdir(parents=True)
        (corpus / language).write_text("operator-stopword\n", encoding="utf-8")
    before = sorted(root.rglob("*"))
    monkeypatch.setattr(nltk_helper, "resource_path", str(root))
    monkeypatch.setattr(nltk_helper.nltk.data, "path", [])
    monkeypatch.setattr(nltk_helper.NLTKHelper, "_stopwords", {"english": None, "chinese": None})
    monkeypatch.setattr(
        nltk_helper, "stopwords", LazyCorpusLoader("stopwords", WordListCorpusReader, r".*", encoding="utf-8")
    )
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
