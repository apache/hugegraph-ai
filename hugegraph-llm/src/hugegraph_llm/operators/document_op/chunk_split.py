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
from typing import Any, Dict, List, Literal, Optional, Union

from langchain_text_splitters import RecursiveCharacterTextSplitter

# Constants
LANGUAGE_ZH = "zh"
LANGUAGE_EN = "en"
SPLIT_TYPE_DOCUMENT = "document"
SPLIT_TYPE_PARAGRAPH = "paragraph"
SPLIT_TYPE_SENTENCE = "sentence"
VALID_SPLIT_TYPES = (
    SPLIT_TYPE_DOCUMENT,
    SPLIT_TYPE_PARAGRAPH,
    SPLIT_TYPE_SENTENCE,
)


def _split_sentence_boundaries(text: str) -> list[str]:
    sentence_pattern = re.compile(r"[^.!?\u3002\uff01\uff1f\uff1b;]+[.!?\u3002\uff01\uff1f\uff1b;]*")
    return [sentence.strip() for sentence in sentence_pattern.findall(text) if sentence.strip()]


def _split_paragraph_boundaries(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", text) if paragraph.strip()]


class ChunkSplit:
    def __init__(
        self,
        texts: Union[str, List[str]],
        split_type: Literal["document", "paragraph", "sentence"] = SPLIT_TYPE_DOCUMENT,
        language: Literal["zh", "en"] = LANGUAGE_ZH,
    ):
        if isinstance(texts, str):
            texts = [texts]
        self.texts = texts
        self.separators = self._get_separators(language)
        self.text_splitter = self._get_text_splitter(split_type)

    def _get_separators(self, language: str) -> List[str]:
        if language == LANGUAGE_ZH:
            return ["\n\n", "\n", "。", "，", ""]
        if language == LANGUAGE_EN:
            return ["\n\n", "\n", ".", ",", " ", ""]
        raise ValueError("language must be zh or en")

    def _get_text_splitter(self, split_type: str):
        if split_type == SPLIT_TYPE_DOCUMENT:
            return lambda text: [text]
        if split_type == SPLIT_TYPE_PARAGRAPH:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=30, separators=self.separators)

            def split_paragraphs(text: str) -> list[str]:
                chunks = []
                paragraphs = _split_paragraph_boundaries(text) or [text]
                for paragraph in paragraphs:
                    chunks.extend(text_splitter.split_text(paragraph))
                return chunks

            return split_paragraphs
        if split_type == SPLIT_TYPE_SENTENCE:
            return _split_sentence_boundaries
        raise ValueError("split_type must be document, paragraph, or sentence")

    def run(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        all_chunks = []
        for text in self.texts:
            chunks = self.text_splitter(text)
            all_chunks.extend(chunks)

        if context is None:
            return {"chunks": all_chunks}
        context["chunks"] = all_chunks
        return context
