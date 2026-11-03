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

import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts import patch_nuitka_compat


SOURCE = """
class Delta:
    def __init__(self, role):
        self.role = role

class StreamingChoices:
    def __init__(self, delta):
        self.delta = delta

class ChunkProcessor:
    @staticmethod
    def _role_of_choice(choice: object) -> str:
        match choice:
            case StreamingChoices(delta=Delta(role=str() as role)) | {"delta": {"role": str() as role}} if role:
                return role
            case _:
                return "assistant"
"""


def evaluate(source: str, shape: str, role: str | None = None) -> str:
    namespace: dict[str, Any] = {}
    exec(compile(source, "<fixture>", "exec"), namespace)

    if shape == "object":
        choice = namespace["StreamingChoices"](namespace["Delta"](role))
    elif shape == "mapping":
        choice = {"delta": {"role": role}}
    else:
        choice = None

    return namespace["ChunkProcessor"]._role_of_choice(choice)


class TestNuitkaCompatibilityPatch(unittest.TestCase):
    def test_rewrites_the_known_litellm_pattern(self):
        updated, changed = patch_nuitka_compat.rewrite_litellm_source(SOURCE)

        self.assertTrue(changed)
        self.assertNotIn(patch_nuitka_compat.VULNERABLE_SIGNATURE, updated)
        self.assertIn(patch_nuitka_compat.PATCH_MARKER, updated)
        compile(updated, "<updated>", "exec")

    def test_patch_preserves_object_mapping_and_fallback_behavior(self):
        updated, _ = patch_nuitka_compat.rewrite_litellm_source(SOURCE)
        cases = (
            ("object", "system", "system"),
            ("object", "", "assistant"),
            ("mapping", "tool", "tool"),
            ("mapping", "", "assistant"),
            ("fallback", None, "assistant"),
        )

        for shape, role, expected in cases:
            with self.subTest(shape=shape, role=role):
                self.assertEqual(expected, evaluate(SOURCE, shape, role))
                self.assertEqual(expected, evaluate(updated, shape, role))

    def test_second_application_is_a_no_op(self):
        updated, changed = patch_nuitka_compat.rewrite_litellm_source(SOURCE)
        second, changed_again = patch_nuitka_compat.rewrite_litellm_source(updated)

        self.assertTrue(changed)
        self.assertFalse(changed_again)
        self.assertEqual(updated, second)

    def test_changed_vulnerable_source_fails_loudly(self):
        changed_shape = SOURCE.replace(
            " if role:\n                return role",
            " if role:  # upstream formatting changed\n                return role",
        )
        with self.assertRaisesRegex(
            patch_nuitka_compat.CompatibilityPatchError,
            "source shape changed",
        ):
            patch_nuitka_compat.rewrite_litellm_source(changed_shape)

    def test_future_source_without_the_pattern_is_a_no_op(self):
        source = "def role(choice):\n    return 'assistant'\n"
        updated, changed = patch_nuitka_compat.rewrite_litellm_source(source)
        self.assertFalse(changed)
        self.assertEqual(source, updated)

    def test_file_patch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "streaming_chunk_builder_utils.py"
            path.write_text(SOURCE, encoding="utf-8")

            self.assertTrue(patch_nuitka_compat.patch_file(path))
            first = path.read_text(encoding="utf-8")
            self.assertFalse(patch_nuitka_compat.patch_file(path))
            self.assertEqual(first, path.read_text(encoding="utf-8"))

    def test_docker_context_includes_the_compatibility_script(self):
        repository = Path(__file__).resolve().parents[2]
        dockerignore = (repository / ".dockerignore").read_text(encoding="utf-8")

        self.assertNotIn("\nscripts/\n", dockerignore)
        self.assertIn("\nscripts/*\n!scripts/patch_nuitka_compat.py\n", dockerignore)


if __name__ == "__main__":
    unittest.main()
