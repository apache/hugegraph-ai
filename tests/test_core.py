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
"""Golden package: load + validate + lint, plus injected-fault detection."""
from __future__ import annotations

import copy

import pytest

from ontogeny.core import load_package, validate
from ontogeny.core.linter import lint
from ontogeny.core.types import PropertyType
from ontogeny.errors import DSLValidationError, TypeMismatchError


class TestGoldenPackage:
    def test_loads_all_resources(self, golden_pkg):
        assert golden_pkg.manifest.metadata.name == "product-manufacturing"
        assert len(golden_pkg.stores()) == 1
        assert len(golden_pkg.objects()) == 7
        assert len(golden_pkg.links()) == 6
        assert len(golden_pkg.actions()) == 11
        assert len(golden_pkg.functions()) == 3
        assert len(golden_pkg.policies()) == 2  # production + package default
        assert len(golden_pkg.projections()) == 1
        assert len(golden_pkg.eval_suites()) == 1
        assert golden_pkg.evolution_policy() is not None

    def test_validates_clean(self, golden_pkg):
        rep = validate(golden_pkg)
        errs = [i for i in rep.issues if i.severity == "error"]
        assert not errs, [f"{i.code}:{i.message}" for i in errs]
        assert rep.ok

    def test_lint_runs(self, golden_pkg):
        rep = lint(golden_pkg)
        assert isinstance(rep.issues, list)

    def test_lint_survives_a_function_derived_property(self, golden_pkg):
        """Regression: `_derived_depth` handed every `derived` value to the
        expression parser, but a function-derived property's `derived` is a
        *dict* (`{kind: function, entry: ...}`), not an expression string. The
        parser caches on its source, so the dict raised
        `TypeError: unhashable type: 'dict'` and `ontogeny lint` died on any package
        that used a derived property backed by a function.

        The product-manufacturing domain does exactly that once such a property
        is declared, which is how this was found: `ontogeny lint` on a freshly
        booted `--demo` instance crashed.
        """
        import copy

        pkg = copy.deepcopy(golden_pkg)
        obj = pkg.find("ObjectType", "work-center")
        # a function-backed derived property (a dict), alongside the golden
        # package's expression-backed one
        obj.spec.properties["open_orders"] = obj.spec.properties["work_center_id"].model_copy(
            update={"derived": {"kind": "function", "entry": "count.py:main", "triggers": ["production-order"]}},
        )
        rep = lint(pkg)
        assert isinstance(rep.issues, list)
        # and the expression-backed property is still measured
        assert not [i for i in rep.issues if i.code == "OO-004" and "work-center" in i.resource]

    def test_marking_does_not_leak_into_projection(self, golden_pkg):
        prj = golden_pkg.find("Projection", "production-graph")
        mat = golden_pkg.find("ObjectType", "material")
        marked = {n for n, p in mat.spec.properties.items() if p.marking}
        whitelisted = set(prj.spec.include.objects["material"].properties)
        assert marked, "material must carry at least one marked property"
        assert not (marked & whitelisted), "marked property in graph whitelist"


class TestInjectedFaults:
    """Each case mutates the golden package and expects a specific validator error."""

    def _mutated(self, golden_pkg):
        return copy.deepcopy(golden_pkg)

    def test_link_endpoint_unknown(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        pkg.find("LinkType", "operation-work-center").spec.target = "no-such-type"
        rep = validate(pkg)
        assert any(i.code == "LINK-ENDPOINT" for i in rep.issues)

    def test_action_sets_source_owned_property(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        eff = pkg.find("Action", "release-production-order").spec.effects[0]
        eff.set["due_date"] = "'2026-12-01'"  # due_date is source-owned (mapped)
        rep = validate(pkg)
        assert any(i.code == "ACTION-OWNER" for i in rep.issues)

    def test_action_sets_derived_property(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        eff = pkg.find("Action", "release-production-order").spec.effects[0]
        eff.set["release_lag_h"] = "60"
        rep = validate(pkg)
        assert any(i.code == "ACTION-DERIVED" for i in rep.issues)

    def test_projection_marked_property(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        prj = pkg.find("Projection", "production-graph")
        prj.spec.include.objects["material"].properties.append("unit_cost")
        rep = validate(pkg)
        assert any(i.code == "PROJ-MARKING" for i in rep.issues)

    def test_projection_link_endpoint_missing(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        prj = pkg.find("Projection", "production-graph")
        del prj.spec.include.objects["operation"]
        rep = validate(pkg)
        assert any(i.code == "PROJ-LINK-ENDPOINT" for i in rep.issues)

    def test_missing_default_policy(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        # every golden action declares `policy: production`; strip one so it
        # falls back to the package default, then remove that default -- the
        # safety net that keeps undeclared actions denied must be required
        pkg.find("Action", "record-inspection").spec.policy = None
        pkg.resources = [r for r in pkg.resources if not (r.kind == "PolicySet" and r.metadata.name == "default")]
        rep = validate(pkg)
        assert any(i.code == "ACTION-POLICY" for i in rep.issues)

    def test_bad_rule_expression_path(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        pkg.find("Action", "release-production-order").spec.rules[0].expr = "target.nonexistent == 1"
        rep = validate(pkg)
        assert any(i.code == "EXPR-PATH" for i in rep.issues)

    def test_create_missing_pk(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        eff = pkg.find("Action", "create-production-order").spec.effects[0]
        del eff.properties["order_id"]
        rep = validate(pkg)
        assert any(i.code == "ACTION-PK" for i in rep.issues)

    def test_watermark_without_column(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        po = pkg.find("ObjectType", "production-order")
        po.spec.backing.sync.watermark = None
        rep = validate(pkg)
        assert any(i.code == "SYNC-WATERMARK" for i in rep.issues)

    def test_unknown_backing_store(self, golden_pkg):
        pkg = self._mutated(golden_pkg)
        pkg.find("ObjectType", "production-order").spec.backing.store = "ghost"
        rep = validate(pkg)
        assert any(i.code == "BACKING-STORE" for i in rep.issues)


class TestTypes:
    def test_parse_enum(self):
        t = PropertyType.parse("enum[OPEN, CLOSED]")
        assert t.kind == "enum" and t.enum_values == ("OPEN", "CLOSED")

    def test_parse_decimal(self):
        t = PropertyType.parse("decimal(12,2)")
        assert (t.precision, t.scale) == (12, 2)

    def test_parse_nested(self):
        t = PropertyType.parse("array(enum[A, B])")
        assert t.kind == "array" and t.inner.kind == "enum"

    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            PropertyType.parse("int8")

    def test_coerce_roundtrip(self):
        t = PropertyType.parse("integer")
        assert t.coerce("42") == 42
        t = PropertyType.parse("boolean")
        assert t.coerce("true") is True
        with pytest.raises(TypeMismatchError):
            t.coerce("maybe")

    def test_coerce_enum_rejects_out_of_domain(self):
        t = PropertyType.parse("enum[LOW, HIGH]")
        with pytest.raises(TypeMismatchError):
            t.coerce("MID")


class TestLoader:
    def test_missing_manifest(self, tmp_path):
        with pytest.raises(DSLValidationError):
            load_package(tmp_path)

    def test_wrong_kind_in_dir(self, tmp_path, golden_pkg_path):
        import shutil

        dest = tmp_path / "pkg"
        shutil.copytree(golden_pkg_path, dest)
        (dest / "objects" / "bad.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Store\nmetadata: {name: bad}\nspec: {type: sqlite, connection: x}\n",
            encoding="utf-8",
        )
        with pytest.raises(DSLValidationError):
            load_package(dest)
