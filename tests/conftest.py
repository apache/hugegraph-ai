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
"""Shared fixtures. The manufacturing example is the golden package: it must
always validate, and runtime fixtures are derived from it.

A session-scoped guard snapshots the golden package tree and fails the session
if any test mutates it on disk -- promotion tests must work on temp copies.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "domains" / "product-manufacturing"

# extension packages are importable the same way the extension host loads them:
# their directory goes on sys.path (mirrors ontogeny.ext_host._load_one)
for _ext in sorted((REPO / "extensions").glob("*")):
    if _ext.is_dir() and str(_ext) not in sys.path:
        sys.path.insert(0, str(_ext))


def _tree_hash(root: Path) -> str:
    """Hash the package *sources* -- derived bytecode is ignored so unrelated
    tooling can never trip the guard."""
    h = hashlib.sha256()
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        if "__pycache__" in f.parts or f.suffix in (".pyc", ".pyo"):
            continue
        h.update(str(f.relative_to(root)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="session", autouse=True)
def protect_golden_example():
    """The golden package is read-only for the test session (e2e/promote paths
    must operate on copies -- a mutated example used to silently break signals)."""
    before = _tree_hash(EXAMPLES)
    yield
    after = _tree_hash(EXAMPLES)
    if before != after:
        raise AssertionError(
            "golden example tree was modified by the test session: tests must "
            "copy domains/product-manufacturing to a temp dir before promoting mutations"
        )


@pytest.fixture()
def golden_pkg_path() -> Path:
    assert (EXAMPLES / "ontology.yaml").is_file()
    return EXAMPLES


@pytest.fixture()
def golden_pkg(golden_pkg_path):
    from ontogeny.core import load_package

    return load_package(golden_pkg_path)


# HTTP client over a real ServiceContext (ASGI transport) — shared by the
# api and guided-demo test modules.
import shutil  # noqa: E402

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402

from ontogeny.api import build_app  # noqa: E402
from ontogeny.config import Settings  # noqa: E402
from ontogeny.service import ServiceContext  # noqa: E402

@pytest_asyncio.fixture()
async def client(golden_pkg_path, tmp_path):
    pkg_root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, pkg_root)
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL (same path the
    # demo bootstrap uses), so tests always agree with the shipped example
    from ontogeny.demo.bootstrap import seed_from_package

    seed_from_package(golden_pkg_path, src, force=True)

    settings = Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
                        # the platform's production default is dev_auth OFF;
                        # tests opt INTO the identity simulation explicitly
                        dev_auth=True,
                        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}",
                             "WMS_WEBHOOK": "https://wms.example.test/hook"})
    sc = ServiceContext(settings, str(pkg_root))
    await sc.initialize()
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    # Default identity for requests that do not name one: an admin dev
    # principal, because the admin/evolve planes are gated now. Tests that
    # exercise identity still pass their own X-Ontogeny-Principal header, which
    # overrides this default for that request.
    default_headers = {"X-Ontogeny-Principal": json.dumps({"id": "ci-admin", "is_admin": True})}
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 headers=default_headers) as c:
        yield c, sc

