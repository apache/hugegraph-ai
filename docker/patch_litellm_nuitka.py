#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Apply a narrow LiteLLM source workaround before the Nuitka binary build."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_LITELLM_TARGET = Path("litellm_core_utils") / "streaming_chunk_builder_utils.py"

_ORIGINAL_ROLE_MATCH = (
    "    @staticmethod\n"
    "    def _role_of_choice(choice: object) -> str:\n"
    "        match choice:\n"
    "            case StreamingChoices(delta=Delta(role=str() as role)) | "
    '{"delta": {"role": str() as role}} if role:\n'
    "                return role\n"
    "            case _:\n"
    '                return "assistant"\n'
)

# Keep the original OR-pattern's left-to-right and guard short-circuiting:
# when the class alternative matches but captures an empty role, Python does
# not try the mapping alternative; the case guard fails and the wildcard case
# returns "assistant". Returning that fallback directly from the first split
# case preserves this behavior even for an object matching both patterns.
_PATCHED_ROLE_MATCH = (
    "    @staticmethod\n"
    "    def _role_of_choice(choice: object) -> str:\n"
    "        match choice:\n"
    "            case StreamingChoices(delta=Delta(role=str() as role)):\n"
    '                return role if role else "assistant"\n'
    '            case {"delta": {"role": str() as role}} if role:\n'
    "                return role\n"
    "            case _:\n"
    '                return "assistant"\n'
)


class UnsupportedLiteLLMSourceError(RuntimeError):
    """Raised when the installed LiteLLM source no longer matches the reviewed form."""


def patch_source(source: str, *, filename: str = "<litellm>") -> tuple[str, bool]:
    """Remove the unsupported OR-pattern while preserving its exact behavior."""

    original_count = source.count(_ORIGINAL_ROLE_MATCH)
    patched_count = source.count(_PATCHED_ROLE_MATCH)

    if original_count == 0 and patched_count == 1:
        compile(source, filename, "exec")
        return source, False

    if original_count != 1 or patched_count != 0:
        raise UnsupportedLiteLLMSourceError(
            "Expected exactly one reviewed LiteLLM _role_of_choice pattern; "
            f"found original={original_count}, patched={patched_count}. "
            "Review the installed LiteLLM source before changing this workaround."
        )

    updated = source.replace(_ORIGINAL_ROLE_MATCH, _PATCHED_ROLE_MATCH, 1)
    compile(updated, filename, "exec")
    return updated, True


def locate_litellm_source() -> Path:
    """Find the installed source file without importing LiteLLM."""

    spec = importlib.util.find_spec("litellm")
    if spec is None or spec.submodule_search_locations is None:
        raise FileNotFoundError("The litellm package is not installed")

    candidates = [
        Path(package_root) / _LITELLM_TARGET
        for package_root in spec.submodule_search_locations
    ]
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if len(existing) != 1:
        rendered = ", ".join(str(candidate) for candidate in candidates) or "<none>"
        raise FileNotFoundError(
            "Expected exactly one installed LiteLLM source file, "
            f"found {len(existing)} among: {rendered}"
        )
    return existing[0]


def patch_file(path: Path) -> bool:
    """Patch one file and return whether it changed."""

    source = path.read_text(encoding="utf-8")
    updated, changed = patch_source(source, filename=str(path))
    if changed:
        path.write_text(updated, encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        help="Override the installed LiteLLM source path (primarily for verification)",
    )
    args = parser.parse_args(argv)

    try:
        target = args.path or locate_litellm_source()
        changed = patch_file(target)
    except (OSError, RuntimeError, SyntaxError) as exc:
        print(f"LiteLLM Nuitka compatibility patch failed: {exc}", file=sys.stderr)
        return 1

    state = "patched" if changed else "already patched"
    print(f"LiteLLM Nuitka compatibility source {state}: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
