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

import tempfile
import unittest
from collections.abc import Callable
from importlib import util
from pathlib import Path
from typing import Any, cast

_MODULE_PATH = Path(__file__).resolve().parents[2] / "docker" / "patch_litellm_nuitka.py"
_SPEC = util.spec_from_file_location("patch_litellm_nuitka", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load compatibility patch module from {_MODULE_PATH}")
patch = util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(patch)


class Delta:
    def __init__(self, role):
        self.role = role


class StreamingChoices(dict):
    """Test object that can deliberately match both class and mapping patterns."""

    def __init__(self, class_role, mapping_role):
        super().__init__(delta={"role": mapping_role})
        self.delta = Delta(class_role)


class TestLiteLLMNuitkaPatch(unittest.TestCase):
    @staticmethod
    def source(block: str) -> str:
        return "from __future__ import annotations\n\n# before\nclass ChunkProcessor:\n" + block + "\n# after\n"

    @staticmethod
    def role_function(block: str) -> Callable[[object], str]:
        namespace: dict[str, Any] = {
            "Delta": Delta,
            "StreamingChoices": StreamingChoices,
        }
        exec(TestLiteLLMNuitkaPatch.source(block), namespace)
        return cast(Callable[[object], str], namespace["ChunkProcessor"]._role_of_choice)

    def test_removes_mixed_or_pattern_and_keeps_valid_syntax(self):
        source = self.source(patch._ORIGINAL_ROLE_MATCH)

        updated, changed = patch.patch_source(source)

        self.assertTrue(changed)
        self.assertNotIn(patch._ORIGINAL_ROLE_MATCH, updated)
        self.assertIn(patch._PATCHED_ROLE_MATCH, updated)
        self.assertTrue(updated.startswith("from __future__ import annotations\n"))
        self.assertTrue(updated.endswith("# after\n"))
        compile(updated, "<test-litellm>", "exec")

    def test_preserves_or_pattern_order_and_guard_short_circuiting(self):
        original = self.role_function(patch._ORIGINAL_ROLE_MATCH)
        rewritten = self.role_function(patch._PATCHED_ROLE_MATCH)
        choices = (
            StreamingChoices("class-role", "mapping-role"),
            # The class alternative matches first but its guard is false. The
            # original OR-pattern therefore does not retry the mapping side.
            StreamingChoices("", "mapping-role"),
            {"delta": {"role": "mapping-role"}},
            {"delta": {"role": ""}},
            object(),
        )

        for choice in choices:
            with self.subTest(choice=choice):
                self.assertEqual(original(choice), rewritten(choice))

    def test_already_patched_source_is_idempotent(self):
        source = self.source(patch._PATCHED_ROLE_MATCH)

        updated, changed = patch.patch_source(source)

        self.assertFalse(changed)
        self.assertEqual(source, updated)

    def test_rejects_unreviewed_litellm_source(self):
        source = self.source(patch._ORIGINAL_ROLE_MATCH.replace("if role:", "if role is not None:"))

        with self.assertRaisesRegex(
            patch.UnsupportedLiteLLMSourceError,
            "Expected exactly one reviewed",
        ):
            patch.patch_source(source)

    def test_patch_file_changes_only_the_reviewed_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "streaming_chunk_builder_utils.py"
            source = self.source(patch._ORIGINAL_ROLE_MATCH)
            path.write_text(source, encoding="utf-8")

            self.assertTrue(patch.patch_file(path))
            self.assertEqual(
                self.source(patch._PATCHED_ROLE_MATCH),
                path.read_text(encoding="utf-8"),
            )
            self.assertFalse(patch.patch_file(path))


if __name__ == "__main__":
    unittest.main()
