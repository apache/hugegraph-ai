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
"""Platform hardening details: honest linting of unimplemented engine kinds,
the single-process deployment contract, and extension module ownership.
"""
from __future__ import annotations

from types import SimpleNamespace


from ontogeny.api_factory import multiprocess_suspected
from ontogeny.config import Settings
from ontogeny.ext_host import ExtensionHost


# ------------------------------------------------------------------ B6


class TestExternalPushWarning:
    def test_declared_push_engine_warns_at_package_check(self, golden_pkg):
        import dataclasses

        from ontogeny.core import validate

        pkg = dataclasses.replace(golden_pkg, resources=list(golden_pkg.resources))
        for i, res in enumerate(pkg.resources):
            if getattr(res, "kind", None) == "AgentPlugin":
                plugin = res.model_copy(deep=True)
                plugin.spec.engine.kind = "external-push"
                plugin.spec.engine.endpoint = "https://engine.example.test/drive"
                pkg.resources[i] = plugin
        rep = validate(pkg)
        codes = {i.code for i in rep.issues}
        assert "AGENT-ENGINE-UNIMPLEMENTED" in codes
        # a warning, not an error: the package still publishes
        errs = [i for i in rep.issues if i.severity == "error"]
        assert not any(i.code == "AGENT-ENGINE-UNIMPLEMENTED" for i in errs)

    def test_pull_and_builtin_stay_silent(self, golden_pkg):
        from ontogeny.core import validate

        rep = validate(golden_pkg)
        assert not any(i.code == "AGENT-ENGINE-UNIMPLEMENTED" for i in rep.issues)


# ------------------------------------------------------------------ B7


class TestSingleProcessContract:
    def test_default_env_is_fine(self, monkeypatch):
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        assert multiprocess_suspected() is None

    def test_web_concurrency_above_one_is_flagged(self, monkeypatch):
        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        why = multiprocess_suspected()
        assert why is not None
        assert "single-process" in why

    def test_garbage_env_is_ignored(self, monkeypatch):
        monkeypatch.setenv("WEB_CONCURRENCY", "auto")
        assert multiprocess_suspected() is None


# ------------------------------------------------------------------ B8


GOOD = """\
apiVersion: ontogeny-ext/v1
name: {name}
kind: generic
entry:
  module: {module}
  function: register
"""


def _host(tmp_path, modules: dict[str, str], names: list[str]):
    root = tmp_path / "extensions"
    for name in names:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        module = modules[name]
        (d / "extension.yaml").write_text(
            GOOD.format(name=name, module=module), encoding="utf-8")
        pkgdir = d / module
        pkgdir.mkdir(exist_ok=True)
        (pkgdir / "__init__.py").write_text(
            f"def register(sc, host):\n    host.provide('capability:{name}')\n",
            encoding="utf-8")
    sc = SimpleNamespace(settings=Settings(extensions_dir=str(root)),
                         agent_engines={}, llm=None, graph_store_factory=None)
    host = ExtensionHost(sc)
    host.discover()
    return host


class TestModuleOwnership:
    async def test_duplicate_module_name_is_refused_loudly(self, tmp_path):
        host = _host(tmp_path,
                     modules={"ext-a": "pkg_shared", "ext-b": "pkg_shared"},
                     names=["ext-a", "ext-b"])
        host.load()
        by_name = {r.name: r for r in host.records}
        assert by_name["ext-a"].status == "loaded"
        assert by_name["ext-b"].status == "error"
        assert "already provided by extension 'ext-a'" in by_name["ext-b"].error

    async def test_same_extension_reloads_fine(self, tmp_path):
        host = _host(tmp_path, modules={"ext-a": "pkg_solo"}, names=["ext-a"])
        host.load()
        assert host.records[0].status == "loaded"
        host.reload_providers()  # same module, same owner: not a conflict
        assert host.records[0].status == "loaded"
