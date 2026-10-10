# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""CLI: validate (golden + broken), docs, diff."""
from __future__ import annotations

from typer.testing import CliRunner

from ontogeny.cli import app

runner = CliRunner()


class TestValidate:
    def test_golden_package_passes(self, golden_pkg_path):
        result = runner.invoke(app, ["validate", str(golden_pkg_path)])
        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    def test_broken_package_fails(self, golden_pkg_path, tmp_path):
        import shutil

        broken = tmp_path / "broken"
        shutil.copytree(golden_pkg_path, broken)
        link = broken / "links" / "bom-material.yaml"
        text = link.read_text(encoding="utf-8").replace("target: bom", "target: ghost")
        link.write_text(text, encoding="utf-8")
        result = runner.invoke(app, ["validate", str(broken)])
        assert result.exit_code == 1
        assert "LINK-ENDPOINT" in result.output


class TestDocsAndDiff:
    def test_docs(self, golden_pkg_path, tmp_path):
        out = tmp_path / "gen"
        result = runner.invoke(app, ["docs", str(golden_pkg_path), "--out", str(out)])
        assert result.exit_code == 0
        content = (out / "ontology.md").read_text(encoding="utf-8")
        assert "ObjectType: production-order" in content

    def test_diff_detects_change(self, golden_pkg_path, tmp_path):
        import shutil

        other = tmp_path / "other"
        shutil.copytree(golden_pkg_path, other)
        obj = other / "objects" / "material.yaml"
        obj.write_text(obj.read_text(encoding="utf-8").replace("display: Material",
                                                               "display: Raw material"),
                       encoding="utf-8")
        result = runner.invoke(app, ["diff", str(golden_pkg_path), str(other)])
        assert "~ ObjectType/material" in result.output
