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
import sys
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError

import nltk
from nltk.corpus import stopwords

from hugegraph_llm.config import resource_path
from hugegraph_llm.utils.log import log


class NLTKHelper:
    _stopwords: Dict[str, Optional[List[str]]] = {
        "english": None,
        "chinese": None,
    }

    def stopwords(self, lang: str = "chinese") -> List[str]:
        """Get stopwords."""
        _hugegraph_source_dir = os.path.join(resource_path, "nltk_data")
        if _hugegraph_source_dir not in nltk.data.path:
            nltk.data.path.append(_hugegraph_source_dir)
        if self._stopwords.get(lang) is None:
            cache_dir = self.get_cache_dir()
            nltk_data_dir = os.environ.get("NLTK_DATA", cache_dir)

            # update nltk path for nltk so that it finds the data
            if nltk_data_dir not in nltk.data.path:
                nltk.data.path.append(nltk_data_dir)

            try:
                nltk.data.find("corpora/stopwords")
            except LookupError:
                try:
                    log.info("Start download nltk package stopwords")
                    nltk.download("stopwords", download_dir=nltk_data_dir, quiet=False)
                    log.debug("NLTK package stopwords is already downloaded")
                except (URLError, HTTPError, PermissionError) as e:
                    log.warning("Can't download package stopwords as error: %s", e)
        try:
            self._stopwords[lang] = stopwords.words(lang)
        except LookupError as e:
            log.error("NLTK stopwords for lang=%s not found: %s; using empty list", lang, e)
            self._stopwords[lang] = []

        # final check
        final_stopwords = self._stopwords[lang]
        if final_stopwords is None:
            return []

        return self._stopwords[lang]

    def check_nltk_data(self):
        _hugegraph_source_dir = os.path.join(resource_path, "nltk_data")
        if _hugegraph_source_dir not in nltk.data.path:
            nltk.data.path.append(_hugegraph_source_dir)

        cache_dir = self.get_cache_dir()
        nltk_data_dir = os.environ.get("NLTK_DATA", cache_dir)
        if nltk_data_dir not in nltk.data.path:
            nltk.data.path.append(nltk_data_dir)

        required_packages = {
            'punkt': 'tokenizers/punkt',
            'punkt_tab': 'tokenizers/punkt_tab',
            'averaged_perceptron_tagger': 'taggers/averaged_perceptron_tagger',
            "averaged_perceptron_tagger_eng": 'taggers/averaged_perceptron_tagger_eng',
        }

        for package, path in required_packages.items():
            try:
                nltk.data.find(path)
            except LookupError:
                log.info("Start download nltk package %s", package)
                try:
                    if not nltk.download(package, download_dir=nltk_data_dir, quiet=False):
                        log.warning("NLTK download command returned False for package %s.", package)
                        return False
                    # Verify after download
                    nltk.data.find(path)
                except PermissionError as e:
                    log.error("Permission denied when downloading %s: %s", package, e)
                    return False
                except (URLError, HTTPError) as e:
                    log.warning("Network error downloading %s: %s, will retry with backup method", package, e)
                    return False
                except LookupError:
                    log.error("Package %s not found after download. Check package name and nltk_data paths.", package)
                    return False
        return True

    @staticmethod
    def get_cache_dir() -> str:
        """Locate a platform-appropriate cache directory for hugegraph-llm,
        and create it if it doesn't yet exist
        """
        # User override
        if "HG_AI_CACHE_DIR" in os.environ:
            path = Path(os.environ["HG_AI_CACHE_DIR"])

        # Linux, Unix, AIX, etc.
        elif os.name == "posix" and sys.platform != "darwin":
            path = Path("/tmp/hugegraph_llm")

        # Mac OS
        elif sys.platform == "darwin":
            path = Path(os.path.expanduser("~"), "Library/Caches/hugegraph_llm")

        # Windows (hopefully)
        else:
            local = os.environ.get("LOCALAPPDATA", None) or os.path.expanduser("~\\AppData\\Local")
            path = Path(local, "hugegraph_llm")

        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)

        return str(path)


if __name__ == "__main__":
    NLTKHelper().stopwords()
