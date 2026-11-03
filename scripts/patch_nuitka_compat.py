#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Apply narrow source compatibility fixes required by the Nuitka image build.

The regular Python package and source distribution are not modified. The script
runs only inside Dockerfile.nk's disposable builder virtual environment before
Nuitka compiles third-party dependencies.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
from pathlib import Path

LITELLM_STREAMING_UTILS = Path("litellm/litellm_core_utils/streaming_chunk_builder_utils.py")

# Nuitka 4.3.4 aborts in ReformulationMatchStatements._buildMatchOr when the
# alternatives bind the same name through different pattern shapes. This exact
# valid Python construct is present in LiteLLM 1.104.0 through 1.106.6.
VULNERABLE_CASE = (
    '            case StreamingChoices(delta=Delta(role=str() as role)) | {"delta": {"role": str() as role}} if role:\n'
)
VULNERABLE_BLOCK = VULNERABLE_CASE + "                return role\n"

# Splitting the alternatives and returning the fallback inside each matched
# case preserves the original guard semantics, including an empty role.
PATCHED_BLOCK = """            # Compatibility: Nuitka 4.3.4 crashes while lowering the equivalent
            # OR-pattern above. Keep the two pattern shapes separate until the
            # compiler accepts the upstream form.
            case StreamingChoices(delta=Delta(role=str() as role)):
                return role or "assistant"
            case {"delta": {"role": str() as role}}:
                return role or "assistant"
"""

VULNERABLE_SIGNATURE = 'StreamingChoices(delta=Delta(role=str() as role)) | {"delta": {"role": str() as role}}'
PATCH_MARKER = "Compatibility: Nuitka 4.3.4 crashes while lowering"


class CompatibilityPatchError(RuntimeError):
    """Raised when a known vulnerable source changed unexpectedly."""


def rewrite_litellm_source(source: str, *, filename: str = "<litellm>") -> tuple[str, bool]:
    """Return a Nuitka-compatible LiteLLM source and whether it changed."""
    if PATCH_MARKER in source:
        compile(source, filename, "exec")
        return source, False

    matches = source.count(VULNERABLE_BLOCK)
    if matches == 1:
        updated = source.replace(VULNERABLE_BLOCK, PATCHED_BLOCK, 1)
        compile(updated, filename, "exec")
        return updated, True

    if matches > 1:
        raise CompatibilityPatchError(f"{filename}: expected one LiteLLM match-OR block, found {matches}")

    if VULNERABLE_SIGNATURE in source:
        raise CompatibilityPatchError(
            f"{filename}: LiteLLM still contains the vulnerable match-OR pattern "
            "but its source shape changed; review the compatibility patch"
        )

    # A future LiteLLM release may remove the unsupported source construct.
    # In that case the workaround is intentionally a no-op.
    compile(source, filename, "exec")
    return source, False


def locate_litellm_source() -> Path:
    """Locate LiteLLM without importing it or its optional dependencies."""
    try:
        distribution = importlib.metadata.distribution("litellm")
    except importlib.metadata.PackageNotFoundError as exc:
        raise CompatibilityPatchError(
            "LiteLLM is not installed; run this script after `uv sync --extra nk-llm`"
        ) from exc

    source = Path(distribution.locate_file(LITELLM_STREAMING_UTILS)).resolve()
    if not source.is_file():
        raise CompatibilityPatchError(f"LiteLLM source file not found: {source}")
    return source


def patch_file(path: Path) -> bool:
    """Patch one installed source file atomically enough for a disposable build env."""
    original = path.read_text(encoding="utf-8")
    updated, changed = rewrite_litellm_source(original, filename=str(path))
    if changed:
        path.write_text(updated, encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        help="Override the installed LiteLLM source path (used by regression tests)",
    )
    args = parser.parse_args(argv)

    source = args.source.resolve() if args.source else locate_litellm_source()
    changed = patch_file(source)
    version = importlib.metadata.version("litellm") if args.source is None else "fixture"
    action = "patched" if changed else "no patch required"
    sys.stdout.write(f"LiteLLM {version}: {action}: {source}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
