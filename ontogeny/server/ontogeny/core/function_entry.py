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

"""Validate and resolve Python function entries inside the package."""

from pathlib import Path


def function_entry_file(entry: str) -> Path:
    file, separator, function = entry.partition(":")
    path = Path(file)
    if (
        not separator
        or not function.isidentifier()
        or not file
        or "\\" in file
        or "\x00" in file
        or path.is_absolute()
        or ".." in path.parts
        or path.suffix != ".py"
    ):
        raise ValueError("entry must name a relative .py file and function inside functions/")
    return path


def resolve_function_entry(package_root: str | Path, entry: str) -> Path:
    file = function_entry_file(entry)
    root = Path(package_root).resolve() / "functions"
    try:
        path = (root / file).resolve()
        path.relative_to(root)
    except (ValueError, OSError, RuntimeError) as exc:
        raise ValueError("function source must remain inside the package functions directory") from exc
    return path
