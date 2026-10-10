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
"""Extension host: discovery, manifest parsing, load isolation, capabilities,
and the /admin/extensions inventory endpoint.

The shipped extensions/ directory is the default discovery root, so the tests
that exercise the real host also prove the three bundled extensions load and
register their contracts (llm gateway, engine factory, graph store factory).
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.ext_host import ExtensionHost


def _host(tmp_path, packages: dict[str, str], manifests: dict[str, str],
          settings: Settings | None = None, monkeypatch=None):
    """An ExtensionHost over a synthetic extensions directory."""
    root = tmp_path / "extensions"
    for name, manifest in manifests.items():
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "extension.yaml").write_text(manifest, encoding="utf-8")
        pkg = d / f"pkg_{name.replace('-', '_')}"
        pkg.mkdir(exist_ok=True)
        (pkg / "__init__.py").write_text(packages[name], encoding="utf-8")
    settings = settings or Settings(extensions_dir=str(root))
    sc = SimpleNamespace(settings=settings, agent_engines={}, llm=None,
                         graph_store_factory=None, agents=None)
    host = ExtensionHost(sc)
    host.discover()
    return sc, host


GOOD_PROVIDER = """\
apiVersion: ontogeny-ext/v1
name: fake-llm
kind: llm-provider
provides: [capability:llm]
entry:
  module: pkg_fake_llm
  function: register
"""

GOOD_ENGINE = """\
apiVersion: ontogeny-ext/v1
name: fake-engine
kind: agent-engine
requires: [capability:llm]
entry:
  module: pkg_fake_engine
  function: register
"""


class TestDiscoveryAndLoading:
    async def test_loads_in_order_and_records_capabilities(self, tmp_path, monkeypatch):
        sc, host = _host(
            tmp_path,
            packages={
                "fake-llm": "CAPS = []\ndef register(sc, host):\n    sc.llm = 'GATEWAY'\n    host.provide('capability:llm', {'model': 'x'})\n",
                "fake-engine": "def register(sc, host):\n    sc.agent_engines['fake'] = lambda sc: 'ENGINE'\n",
            },
            manifests={"fake-llm": GOOD_PROVIDER, "fake-engine": GOOD_ENGINE},
            monkeypatch=monkeypatch,
        )
        host.load()
        by_name = {r.name: r for r in host.records}
        assert by_name["fake-llm"].status == "loaded"
        assert by_name["fake-engine"].status == "loaded"
        assert host.capabilities["capability:llm"] == {"extension": "fake-llm", "model": "x"}
        assert sc.llm == "GATEWAY"
        assert sc.agent_engines["fake"](sc) == "ENGINE"

    async def test_unmet_require_skips_with_reason(self, tmp_path, monkeypatch):
        sc, host = _host(
            tmp_path,
            packages={"fake-engine": "def register(sc, host):\n    raise AssertionError('must not run')\n"},
            manifests={"fake-engine": GOOD_ENGINE},
            monkeypatch=monkeypatch,
        )
        host.load()
        rec = host.records[0]
        assert rec.status == "skipped"
        assert "capability:llm" in rec.error

    async def test_broken_extension_is_isolated(self, tmp_path, monkeypatch):
        broken = GOOD_PROVIDER.replace("name: fake-llm", "name: broken-llm").replace(
            "module: pkg_fake_llm", "module: pkg_broken_llm")
        engine_no_req = GOOD_ENGINE.replace("requires: [capability:llm]\n", "")
        sc, host = _host(
            tmp_path,
            packages={
                "broken-llm": "raise RuntimeError('nope')\n",
                "fake-engine": "def register(sc, host):\n    sc.agent_engines['fake'] = lambda sc: 'ENGINE'\n",
            },
            manifests={"broken-llm": broken, "fake-engine": engine_no_req},
            monkeypatch=monkeypatch,
        )
        host.load()
        by_name = {r.name: r for r in host.records}
        assert by_name["broken-llm"].status == "error"
        assert "RuntimeError" in by_name["broken-llm"].error
        assert by_name["fake-engine"].status == "loaded"

    async def test_empty_allowlist_disables_everything(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ONTOGENY_EXTENSIONS", "")
        sc, host = _host(
            tmp_path,
            packages={"fake-llm": "def register(sc, host):\n    pass\n"},
            manifests={"fake-llm": GOOD_PROVIDER},
            monkeypatch=monkeypatch,
        )
        host.load()
        assert host.records[0].status == "disabled"

    async def test_allowlist_selects_by_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ONTOGENY_EXTENSIONS", "fake-llm")
        sc, host = _host(
            tmp_path,
            packages={
                "fake-llm": "def register(sc, host):\n    sc.llm = 'GATEWAY'\n    host.provide('capability:llm')\n",
                "fake-engine": "def register(sc, host):\n    sc.agent_engines['fake'] = lambda sc: 'ENGINE'\n",
            },
            manifests={"fake-llm": GOOD_PROVIDER, "fake-engine": GOOD_ENGINE},
            monkeypatch=monkeypatch,
        )
        host.load()
        by_name = {r.name: r for r in host.records}
        assert by_name["fake-llm"].status == "loaded"
        assert by_name["fake-engine"].status == "disabled"  # not selected

    async def test_manifest_without_entry_is_skipped(self, tmp_path, monkeypatch):
        sc, host = _host(
            tmp_path,
            packages={"fake-llm": ""},
            manifests={"fake-llm": "apiVersion: ontogeny-ext/v1\nname: fake-llm\n"},
            monkeypatch=monkeypatch,
        )
        host.load()
        assert host.records[0].status == "skipped"


class TestShippedExtensions:
    """The three extensions bundled in the repo must load through the real host."""

    async def test_default_dir_discovers_three_extensions(self, monkeypatch):
        monkeypatch.delenv("ONTOGENY_EXTENSIONS", raising=False)
        sc = SimpleNamespace(settings=Settings(), agent_engines={}, llm=None,
                             graph_store_factory=None, agents=None)
        host = ExtensionHost(sc)
        host.discover()
        names = {r.name for r in host.records}
        assert {"llm-ollama", "agent-builtin-llm", "graph-hugegraph"} <= names

    async def test_shipped_providers_register_contracts(self, monkeypatch):
        monkeypatch.delenv("ONTOGENY_EXTENSIONS", raising=False)
        engines: dict = {}
        sc = SimpleNamespace(
            settings=Settings(llm_base_url="http://ollama.test", llm_model="m1"),
            agent_engines=engines, llm=None, graph_store_factory=None,
            llm_http=None, agents=None,
        )
        host = ExtensionHost(sc)
        host.discover()
        host.load()
        by_name = {r.name: r for r in host.records}
        assert by_name["llm-ollama"].status == "loaded"
        assert by_name["graph-hugegraph"].status == "loaded"
        assert by_name["agent-builtin-llm"].status == "loaded"
        assert sc.llm is not None and sc.llm.model == "m1"
        assert callable(sc.graph_store_factory)
        # engine factory builds lazily; llm present -> engine carries it
        engine = engines["builtin-llm"](sc)
        assert engine.llm is sc.llm

    async def test_without_base_url_llm_capability_is_absent_but_engine_registers(self, monkeypatch):
        monkeypatch.delenv("ONTOGENY_EXTENSIONS", raising=False)
        engines: dict = {}
        sc = SimpleNamespace(settings=Settings(), agent_engines=engines, llm=None,
                             graph_store_factory=None, llm_http=None, agents=None)
        host = ExtensionHost(sc)
        host.discover()
        host.load()
        assert sc.llm is None
        assert "capability:llm" not in host.capabilities
        # graceful degradation: engine still registers; run endpoint surfaces
        # LLM_NOT_CONFIGURED because the built engine's .llm is None
        assert engines["builtin-llm"](sc).llm is None


@pytest_asyncio.fixture()
async def api(golden_pkg_path, tmp_path):
    import shutil

    from ontogeny.api import build_app
    from ontogeny.service import ServiceContext

    pkg_root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, pkg_root)
    settings = Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
                        env={"ERP_DSN": f"sqlite+aiosqlite:///{tmp_path/'erp.db'}"})
    sc = ServiceContext(settings, str(pkg_root))
    await sc.initialize()
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    import json as J
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 headers={"X-Ontogeny-Principal": J.dumps({"id": "ci-admin", "is_admin": True})}) as c:
        yield c


class TestExtensionsEndpoint:
    async def test_inventory_lists_shipped_extensions(self, api):
        r = await api.get("/api/v1/admin/extensions")
        assert r.status_code == 200
        body = r.json()
        names = {e["name"] for e in body["extensions"]}
        assert {"llm-ollama", "agent-builtin-llm", "graph-hugegraph"} <= names
        statuses = {e["name"]: e["status"] for e in body["extensions"]}
        assert all(v == "loaded" for k, v in statuses.items()
                   if k in {"llm-ollama", "agent-builtin-llm", "graph-hugegraph"})
