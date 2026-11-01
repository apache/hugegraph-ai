"""Shared fixtures for the document ingestion tests (not a test module)."""

from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.documents.protocol import ChunkResult
from ontogeny.service import ServiceContext

DOMAIN = Path(__file__).resolve().parent / "fixtures" / "supplier-risk"


class FakeExtractor:
    """Deterministic stand-in for the LLM extractor.

    It implements the same contract and returns the same shape a real
    extractor does, so the engine/binder/review paths are exercised without a
    model or network. ``calls`` proves packet caching: a rerun with unchanged
    input must not call it again.
    """

    def __init__(
        self, *, chunks_per_doc: int = 1, fail_names: set[str] | None = None, skip_supplier_edge: bool = False
    ) -> None:
        self.calls = 0
        self.documents_seen: list[str] = []
        self.chunks_per_doc = chunks_per_doc
        self.fail_names = fail_names or set()
        self.skip_supplier_edge = skip_supplier_edge

    async def health(self):
        return {"status": "ok", "engine": "fake"}

    async def read(self, path: Path) -> str:
        return Path(path).read_text(encoding="utf-8")

    async def extract(self, request):
        self.calls += 1
        out: list[ChunkResult] = []
        for doc in request.docs:
            self.documents_seen.append(doc.path)
            if Path(doc.path).name in self.fail_names:
                raise RuntimeError("simulated extractor failure")
            fields: dict[str, str] = {}
            for line in doc.text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fields[k.strip().lower()] = v.strip()
            supplier = fields.get("supplier")
            date = fields.get("effective date")
            if not supplier or not date:
                out.append(ChunkResult(doc.doc_id, 0, doc.text, {"vertices": [], "edges": []}, [], "final"))
                continue
            note_id = "n-" + doc.doc_id[:8]
            supplier_id = "s-" + re.sub(r"[^a-z0-9]+", "-", supplier.lower())
            vertices = [
                {"id": supplier_id, "label": "supplier", "properties": {"name": supplier}},
                {
                    "id": note_id,
                    "label": "supplier-note",
                    "properties": {
                        "supplier_name": supplier,
                        "risk_level": fields.get("risk level"),
                        "effective_date": date,
                        "summary": fields.get("summary"),
                    },
                },
            ]
            edges = []
            if not self.skip_supplier_edge:
                edges.append(
                    {
                        "label": "supplier-risk-note",
                        "outV": supplier_id,
                        "outVLabel": "supplier",
                        "inV": note_id,
                        "inVLabel": "supplier-note",
                        "properties": {},
                    }
                )
            out.append(ChunkResult(doc.doc_id, 0, doc.text, {"vertices": vertices, "edges": edges}, [], "final"))
        return out


class ChatStub:
    """Minimal LLM gateway: answers every extraction prompt with one graph."""

    def __init__(self, graph_json: str) -> None:
        self.graph_json = graph_json
        self.calls = 0

    async def chat(self, messages, **_kw):
        self.calls += 1
        return {"content": self.graph_json}


def seed_suppliers(db: Path) -> None:
    con = sqlite3.connect(db)
    con.executescript((DOMAIN / "seed" / "01_suppliers.sql").read_text(encoding="utf-8"))
    con.commit()
    con.close()


def copy_domain(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    shutil.copytree(DOMAIN, pkg)
    # the real corpus is user-editable (uploaded notes must survive); tests use
    # the three shipped fixtures only so counts do not depend on local uploads
    shipped = {"acme-2026-03.md", "globex-2026-02.md", "note-format.md"}
    notes = pkg / "data" / "docs" / "supplier-notes"
    if notes.is_dir():
        for path in notes.iterdir():
            if path.is_file() and path.name not in shipped:
                path.unlink()
    return pkg


async def make_context(
    tmp_path: Path, extractor=None, mutate=None, **settings_kwargs
) -> tuple[ServiceContext, Path, Path]:
    pkg = copy_domain(tmp_path)
    if mutate is not None:
        mutate(pkg)
    db = tmp_path / "suppliers.db"
    seed_suppliers(db)
    ext = tmp_path / "ext"
    ext.mkdir(exist_ok=True)
    settings = Settings(
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        dev_auth=True,
        env={"SUPPLIER_DSN": f"sqlite+aiosqlite:///{db}"},
        extensions_dir=str(ext),
        llm_model="fake-model",
        **settings_kwargs,
    )
    sc = ServiceContext(settings, str(pkg))
    await sc.initialize()
    sc.document_extractor = extractor or FakeExtractor()
    await sc.sync("supplier")
    return sc, pkg, db


@pytest_asyncio.fixture()
async def doc_context(tmp_path):
    sc, pkg, db = await make_context(tmp_path)
    yield sc, pkg, db


def add_note(pkg: Path, name: str, supplier: str, date: str, risk: str, summary: str = "note") -> Path:
    path = pkg / "data" / "docs" / "supplier-notes" / name
    path.write_text(
        f"# {supplier} risk\n\nSupplier: {supplier}\nEffective date: {date}\nRisk level: {risk}\nSummary: {summary}\n",
        encoding="utf-8",
    )
    return path
