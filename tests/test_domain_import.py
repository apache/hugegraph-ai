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
"""Domain-package import: the "New domain -> import" path.

The zip is untrusted input: these tests pin the safety contract (traversal,
invalid package, duplicate name -> clean refusal with no residue) and the
happy path against the real product-manufacturing package.
"""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.service import DomainError
from ontogeny.service import ServiceContext

REPO = Path(__file__).resolve().parent.parent
DOMAIN = REPO / "domains" / "product-manufacturing"

ADMIN = {"id": "admin", "Role": ["admin"], "is_admin": True}


def _hdr(p):
    return {"X-Ontogeny-Principal": json.dumps(p)}


def zip_domain(with_root_folder: bool = True) -> bytes:
    """Zip the real domain package, optionally wrapped in its folder."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(DOMAIN.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                arc = (f"{DOMAIN.name}/{f.relative_to(DOMAIN)}" if with_root_folder
                       else str(f.relative_to(DOMAIN)))
                zf.write(f, arc)
    return buf.getvalue()


@pytest_asyncio.fixture()
async def rig(tmp_path):
    """A ServiceContext booted from a temp copy of the package: its domains
    root derives to ``tmp_path/domains`` (sibling of the boot copy), so every
    import lands in scratch space and the repo tree stays untouched."""
    pkg_root = tmp_path / "pkg"
    shutil.copytree(DOMAIN, pkg_root)
    root = tmp_path / "domains"
    settings = Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'ontogeny.db'}")
    sc = ServiceContext(settings, str(pkg_root))
    await sc.initialize()
    assert sc.domains_root() == root
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield sc, c, root


class TestImportService:
    async def test_import_installs_and_reports_the_domain(self, rig):
        sc, _c, root = rig
        out = await sc.import_domain(zip_domain(), activate=False)
        assert out["name"] == "product-manufacturing"
        assert out["objects"] == 7 and out["links"] == 6 and out["actions"] == 11
        assert (root / "product-manufacturing" / "ontology.yaml").is_file()
        assert out["active"] is False
        # it shows up in the switcher like any other domain
        names = [d["name"] for d in sc.list_domains()]
        assert "product-manufacturing" in names

    async def test_import_can_activate_and_functions_resolve(self, rig):
        sc, _c, root = rig
        out = await sc.import_domain(zip_domain(), activate=True)
        assert out["active"] is True and out.get("content_hash")
        assert set(sc.compiled.functions) == {
            "material-availability", "capacity-check", "order-yield"}
        assert sc.compiled.package_name == "product-manufacturing"

    async def test_zip_without_root_folder_works_too(self, rig):
        sc, _c, root = rig
        out = await sc.import_domain(zip_domain(with_root_folder=False))
        assert (root / "product-manufacturing" / "seed" / "01_source.sql").is_file()
        assert out["name"] == "product-manufacturing"

    async def test_not_a_zip_is_refused(self, rig):
        sc, _c, root = rig
        with pytest.raises(DomainError, match="not a zip"):
            await sc.import_domain(b"this is not a zip at all")
        assert list(root.iterdir()) == []

    async def test_missing_manifest_is_refused(self, rig):
        sc, _c, root = rig
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "no ontology here")
        with pytest.raises(DomainError, match="ontology.yaml"):
            await sc.import_domain(buf.getvalue())
        assert list(root.iterdir()) == []

    async def test_path_traversal_is_refused(self, rig):
        """A member that escapes the extraction dir must never be written."""
        sc, _c, root = rig
        evil_target = root.parent / "escaped.txt"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ontology.yaml", "apiVersion: ontogeny/v1\nkind: Ontology\n"
                                        "metadata: {name: evil}\nspec: {imports: []}\n")
            zf.writestr("../escaped.txt", "pwn")
        with pytest.raises(DomainError, match="unsafe archive member"):
            await sc.import_domain(buf.getvalue())
        assert not evil_target.exists()
        # the staged manifest did not become a domain either
        assert not (root / "evil").exists()

    async def test_invalid_package_is_refused_with_issues(self, rig):
        sc, _c, root = rig
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("bad/ontology.yaml",
                        "apiVersion: ontogeny/v1\nkind: Ontology\n"
                        "metadata: {name: bad-domain}\nspec: {imports: []}\n")
            # an action pointing at a type that does not exist -> validator error
            zf.writestr("bad/actions/x.yaml",
                        "apiVersion: ontogeny/v1\nkind: Action\nmetadata: {name: x}\n"
                        "spec: {target: ghost, effects: []}\n")
        with pytest.raises(DomainError, match="rejected by validator") as excinfo:
            await sc.import_domain(buf.getvalue())
        assert excinfo.value.details["issues"]
        assert not (root / "bad-domain").exists()
        # no staging residue
        assert [p.name for p in root.iterdir() if p.name.startswith(".import-")] == []

    async def test_duplicate_import_is_refused(self, rig):
        sc, _c, root = rig
        await sc.import_domain(zip_domain(), activate=False)
        with pytest.raises(DomainError, match="already exists"):
            await sc.import_domain(zip_domain(), activate=False)


class TestImportRoute:
    async def test_http_import_requires_admin(self, rig):
        _sc, c, _root = rig
        r = await c.post("/api/v1/admin/domains/import", content=zip_domain())
        assert r.status_code == 403

    async def test_http_import_round_trip(self, rig):
        sc, c, root = rig
        r = await c.post("/api/v1/admin/domains/import?activate=false",
                         content=zip_domain(), headers=_hdr(ADMIN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "product-manufacturing" and body["objects"] == 7
        # activating through the regular switch endpoint works on the import
        r = await c.post("/api/v1/admin/domains/activate",
                         json={"name": "product-manufacturing"}, headers=_hdr(ADMIN))
        assert r.status_code == 200 and r.json()["activated"] is True
        assert sc.compiled.package_name == "product-manufacturing"

    async def test_http_rejects_wrong_content_type(self, rig):
        _sc, c, _root = rig
        r = await c.post("/api/v1/admin/domains/import",
                         content=b"{}", headers={**_hdr(ADMIN),
                                                 "content-type": "application/json"})
        assert r.status_code == 415

    async def test_http_reports_validator_issues(self, rig):
        _sc, c, _root = rig
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ontology.yaml", "not: a package")
        r = await c.post("/api/v1/admin/domains/import",
                         content=buf.getvalue(), headers=_hdr(ADMIN))
        assert r.status_code == 400
        assert "ontology.yaml" in r.json()["message"] or "rejected" in r.json()["message"]


def teardown_module(module):
    """Safety net: nothing in this module may touch the repo's domains/ tree."""
    stray = REPO / "domains" / "product-manufacturing"
    assert stray.is_dir(), "the checked-in package must still be there"
