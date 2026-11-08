# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The extraction distribution must not include the nested evaluation package."""

import io
import tarfile
import zipfile

import pytest
from distribution_smoke import verify_archive


def _archive(tmp_path, format, extra=()):
    path = tmp_path / f"hugegraph_llm_sdk-1.8.0.{format}"
    if format == "whl":
        with zipfile.ZipFile(path, "w") as archive:
            for name in ("hugegraph_llm_sdk/__init__.py", *extra):
                archive.writestr(name, b"")
    else:
        with tarfile.open(path, "w:gz") as archive:
            for name in ("src/hugegraph_llm_sdk/__init__.py", *extra):
                info = tarfile.TarInfo(f"hugegraph_llm_sdk-1.8.0/{name}")
                archive.addfile(info, io.BytesIO(b""))
    return path


@pytest.mark.parametrize("format", ("whl", "tar.gz"))
def test_extraction_archives_remain_independent(tmp_path, format):
    verify_archive(_archive(tmp_path, format))


@pytest.mark.parametrize("format", ("whl", "tar.gz"))
@pytest.mark.parametrize(
    "leaked_path",
    ("eval/pyproject.toml", "eval/src/hugegraph_llm_eval/__init__.py", "hugegraph_llm_eval/__init__.py"),
)
def test_distribution_guard_rejects_nested_eval_sources(tmp_path, format, leaked_path):
    with pytest.raises(AssertionError, match="bundles"):
        verify_archive(_archive(tmp_path, format, (leaked_path,)))


def test_distribution_guard_rejects_missing_extraction_package(tmp_path):
    path = tmp_path / "wrong.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("other/__init__.py", b"")
    with pytest.raises(AssertionError, match="missing"):
        verify_archive(path)
