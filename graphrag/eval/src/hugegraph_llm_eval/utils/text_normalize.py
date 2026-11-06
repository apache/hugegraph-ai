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

"""Text normalization utilities for text evaluation.

Implements the MRQA official evaluation standard from HippoRAG 2 (eval_utils.py)
with Porter stemming and bilingual (EN/ZH) support.

For Chinese text the normalization additionally:
- converts full-width ASCII characters (letters, digits, punctuation) to half-width
- performs simplified/traditional Chinese conversion when ``opencc`` is available
- removes Chinese punctuation and collapses whitespace
"""

import re
import string
from typing import cast

# Chinese punctuation set
_CHINESE_PUNCTUATION = set("，。！？、；：''（）【】《》〈〉…—～·「」『』〔〕")
# English stop words removed during normalization (MRQA standard)
_ARTICLES_PATTERN = re.compile(r"\b(a|an|the)\b")

# Full-width ASCII block: U+FF01..U+FF5E map to U+0021..U+007E.
_FULLWIDTH_SPACE = "　"  # full-width space


def _to_halfwidth(text: str) -> str:
    """Convert full-width ASCII characters to their half-width forms.

    Covers full-width letters, digits, punctuation and the full-width space.
    This unifies mixed full/half-width text (e.g. Chinese manuals often contain
    full-width numbers and letters) before comparison.
    """
    # Full-width ASCII block U+FF01..U+FF5E maps to U+0021..U+007E.
    table = {0xFF01 + i: 0x0021 + i for i in range(94)}
    table[ord(_FULLWIDTH_SPACE)] = ord(" ")
    return text.translate(table)


def _simplify_chinese(text: str) -> str:
    """Convert traditional Chinese characters to simplified forms if possible.

    Uses ``opencc-python-reimplemented`` / ``opencc`` when installed. If the
    library is not available the text is returned unchanged so evaluation
    keeps working without extra dependencies.
    """
    try:
        # opencc-python-reimplemented exposes OpenCC in the same way
        from opencc import OpenCC  # type: ignore[import-not-found]  # ty: ignore[import-not-found]

        converter = OpenCC("t2s")
        return cast(str, converter.convert(text))
    except Exception:
        return text


def normalize_answer(answer: str, language: str = "en") -> str:
    """Normalize an answer string for comparison.

    Steps (EN): lowercase → remove punctuation → remove articles
    (a/an/the) → collapse whitespace.
    Steps (ZH): full-width to half-width → traditional to simplified Chinese
    → lowercase → remove punctuation (incl. Chinese) → collapse whitespace.

    Reference: HippoRAG 2 / MRQA official eval_utils.normalize_answer
    (standard SQuAD normalization: lowercase, remove punctuation, remove
    a/an/the, collapse whitespace). Note: ``and`` is a conjunction, not an
    article, and is intentionally NOT removed.

    Args:
        answer: Raw answer text.
        language: 'en' for English, 'zh' for Chinese.

    Returns:
        Normalized string.
    """
    if not answer:
        return ""

    def _preprocess(text: str) -> str:
        # Language-specific preprocessing before shared normalization.
        if language == "zh":
            text = _to_halfwidth(text)
            text = _simplify_chinese(text)
        return text

    def _lower(text: str) -> str:
        return text.lower()

    def _remove_punc(text: str) -> str:
        exclude = set(string.punctuation) | _CHINESE_PUNCTUATION
        return "".join(ch for ch in text if ch not in exclude)

    def _remove_articles(text: str) -> str:
        if language == "en":
            return _ARTICLES_PATTERN.sub(" ", text)
        return text

    def _white_space_fix(text: str) -> str:
        return " ".join(text.split())

    return _white_space_fix(_remove_articles(_remove_punc(_lower(_preprocess(answer)))))


def tokenize(text: str, language: str = "en", stem: bool = False) -> list[str]:
    """Tokenize text into words, optionally with stemming.

    For English: split on whitespace after normalization.
    For Chinese: use jieba segmentation.

    Args:
        text: Raw text to tokenize.
        language: 'en' or 'zh'.
        stem: If True, apply Porter stemmer to English tokens (HippoRAG 2 standard).

    Returns:
        List of tokens.
    """
    if language == "zh":
        import jieba  # type: ignore[import-untyped]

        return list(jieba.cut(normalize_answer(text, language)))

    tokens = normalize_answer(text, language).split()
    if stem:
        try:
            from nltk.stem import PorterStemmer
        except ImportError as exc:
            msg = "tokenize(stem=True) requires nltk: pip install nltk"
            raise ImportError(msg) from exc

        _stemmer = PorterStemmer()
        return [_stemmer.stem(t) for t in tokens]
    return tokens


def normalize_doc_id(doc_id: str) -> str:
    """Normalize a document ID for comparison in retrieval metrics.

    Strips whitespace and lowercases to prevent false negatives from
    case or formatting differences.
    """
    return str(doc_id).strip().lower()
