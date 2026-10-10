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
"""Demo bootstrap: a complete, runnable installation from one command.

Creates a self-contained data directory containing

    <root>/ontogeny.db      metadata + object tables (SQLite)
    <root>/erp.db     a seeded *source* database (stands in for ERP/MES)
    <root>/pkg/       a copy of the example ontology package (sqlite-ized)

The package is COPIED, never mutated in place: the example tree stays the
golden reference for tests, and demo-mode promotions write into the copy
(revert = delete the directory).
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_DEMO_DIR = ".ontogeny-demo"
DEFAULT_PACKAGE = "domains/product-manufacturing"

# Source rows for the demo: 2 pieces of equipment, 3 work orders, 2 spare parts.
EQUIPMENT = [
    ("E-001", "CNC-Alpha", "north", "POINT(120.1 30.2)", "DOWN", "2020-01-01"),
    ("E-002", "Press-Beta", "south", "POINT(121.5 31.1)", "RUNNING", "2019-06-15"),
]
WORK_ORDERS = [
    ("WO-1001", "E-001", "主轴异响", "BREAKDOWN", "HIGH", "north", "OPEN", None,
     "2026-09-17T08:00:00+00:00", None, "2026-09-17T08:00:00+00:00"),
    ("WO-1002", "E-002", "液压油渗漏", "BREAKDOWN", "LOW", "south", "OPEN", None,
     "2026-09-17T09:30:00+00:00", None, "2026-09-17T09:30:00+00:00"),
    ("WO-1003", "E-001", "季度点检", "INSPECTION", "LOW", "north", "CLOSED", "已完成点检",
     "2026-09-10T08:00:00+00:00", "2026-09-10T10:30:00+00:00", "2026-09-10T10:30:00+00:00"),
]
PARTS = [("P-001", "主轴轴承", "1280.00", "6"), ("P-002", "液压密封圈", "45.50", "40")]
WORK_ORDER_PARTS = [("WO-1003", "P-001")]


@dataclass(frozen=True)
class DemoPaths:
    root: Path
    db_dsn: str
    package_root: Path
    pristine_pkg_root: Path
    erp_dsn: str
    # True when the metadata/object store was created (or reset) by this call --
    # a fresh demo is worth acting out a story for, a reused one is not.
    fresh: bool = False

    def as_env(self) -> dict[str, str]:
        env = {
            "ONTOGENY_DB_DSN": self.db_dsn,
            "ONTOGENY_PACKAGE_ROOT": str(self.package_root),
            "ONTOGENY_PRISTINE_PKG_ROOT": str(self.pristine_pkg_root),
            "ERP_DSN": self.erp_dsn,
            "WMS_WEBHOOK": "https://wms.example.test/hook",
        }
        # A demo is an explicitly local, throwaway context: keep the identity
        # simulation available so the console works out of the box, unless the
        # operator explicitly decided ONTOGENY_DEV_AUTH for this process.
        import os

        if "ONTOGENY_DEV_AUTH" not in os.environ:
            env["ONTOGENY_DEV_AUTH"] = "1"
        return env


def package_seed_files(pkg_dir: Path) -> list[Path]:
    """SQL seeds shipped by the package itself (domains/<pkg>/seed/*.sql)."""
    seed_dir = pkg_dir / "seed"
    return sorted(seed_dir.glob("*.sql")) if seed_dir.is_dir() else []


def seed_from_package(pkg_dir: Path, db_path: Path, *, force: bool = True) -> list[str]:
    """Build the demo source database from the package's own seed scripts.

    Example packages own their demo data this way: the ontology and the data it
    describes travel together, so `serve --demo` needs no extra arguments.
    """
    files = package_seed_files(pkg_dir)
    if not files:
        return []
    if db_path.exists() and not force:
        return [f.name for f in files]
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(str(db_path))
    try:
        for f in files:
            con.executescript(f.read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()
    return [f.name for f in files]


def seed_source_db(path: Path, *, force: bool = False) -> None:
    """(Re)create the built-in demo source database. Idempotent unless force=True."""
    if path.exists() and not force:
        return
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE equipment (
            equipment_id TEXT PRIMARY KEY, name TEXT, site TEXT,
            location TEXT, status TEXT, installed_at TEXT
        );
        CREATE TABLE work_orders (
            wo_id TEXT PRIMARY KEY, eq_id TEXT, title TEXT, type TEXT, priority TEXT,
            site TEXT, status TEXT, resolution TEXT,
            created_at TEXT, closed_at TEXT, updated_at TEXT
        );
        CREATE TABLE parts (
            part_id TEXT PRIMARY KEY, name TEXT, unit_price TEXT, stock TEXT
        );
        CREATE TABLE work_order_parts (wo_id TEXT, part_id TEXT);
        """
    )
    con.executemany("INSERT INTO equipment VALUES (?,?,?,?,?,?)", EQUIPMENT)
    con.executemany("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)", WORK_ORDERS)
    con.executemany("INSERT INTO parts VALUES (?,?,?,?)", PARTS)
    con.executemany("INSERT INTO work_order_parts VALUES (?,?)", WORK_ORDER_PARTS)
    con.commit()
    con.close()


def copy_package(src: Path, dest: Path, *, force: bool = False) -> Path:
    """Copy the ontology package and point its store at the demo source DB.

    The example ships a postgres store for real deployments; the demo swaps in
    SQLite so the whole thing runs with zero external services.
    """
    if dest.exists():
        if not force:
            return dest
        shutil.rmtree(dest)
    shutil.copytree(src, dest)

    store_file = dest / "stores" / "erp.yaml"
    if store_file.is_file():
        doc = yaml.safe_load(store_file.read_text(encoding="utf-8"))
        doc["spec"]["type"] = "sqlite"
        doc["spec"]["connection"] = "${ERP_DSN}"
        doc["spec"]["access"] = "read-write"  # close-work-order writes back
        doc["metadata"]["description"] = "演示用本地 SQLite 源库（由 ontogeny serve --demo 生成）"
        store_file.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    return dest


def prepare_demo(
    root: str | Path = DEFAULT_DEMO_DIR,
    *,
    package: str | Path = DEFAULT_PACKAGE,
    reseed: bool = False,
    direct: bool = False,
) -> DemoPaths:
    """Materialize (or reuse) the demo data directory.

    With ``direct`` (used when the package is a first-class domain under a
    ``domains/`` root), the source directory IS the served package: console
    saves — model edits and the canvas ``layout.yaml`` — land in the repo's
    ``domains/<name>/`` instead of a throwaway copy. No ``pkg/`` or
    ``pkg.pristine`` copies are made, so the demo's runtime reset cannot wipe
    them; ``--reseed`` then only rebuilds the seeded source DB and the
    metadata DB, deliberately keeping model edits.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    pkg_src = Path(package)
    if not pkg_src.is_absolute():
        pkg_src = Path.cwd() / pkg_src

    erp = root / "erp.db"
    # a package that ships seed/*.sql owns its demo data; otherwise fall back to
    # the built-in minimal dataset (used by the legacy example and by tests)
    seeded = seed_from_package(pkg_src, erp, force=reseed or not erp.exists())
    if not seeded:
        seed_source_db(erp, force=reseed)

    if direct:
        return DemoPaths(
            root=root,
            db_dsn=f"sqlite+aiosqlite:///{(root / 'ontogeny.db').resolve()}",
            package_root=pkg_src.resolve(),
            pristine_pkg_root=root / "pkg.pristine",  # deliberately absent
            erp_dsn=f"sqlite+aiosqlite:///{erp.resolve()}",
            fresh=reseed or not db_exists(root),
        )

    pkg = copy_package(pkg_src, root / "pkg", force=reseed)
    # a never-mutated copy for the guided demo's runtime reset: mounting,
    # evolution promotions and new plugins all write into pkg/, and reset()
    # restores from here without touching the repo's domains
    pristine = root / "pkg.pristine"
    if reseed or not pristine.is_dir():
        copy_package(pkg_src, pristine, force=True)

    # --reseed means "rebuild from scratch": the package copy alone is not
    # enough, because the service serves the PUBLISHED ontology out of the
    # metadata DB and would otherwise keep the previous package's snapshot.
    db = root / "ontogeny.db"
    fresh = reseed or not db.exists()
    if reseed and db.exists():
        db.unlink()

    return DemoPaths(
        root=root,
        db_dsn=f"sqlite+aiosqlite:///{(root / 'ontogeny.db').resolve()}",
        package_root=pkg,
        pristine_pkg_root=pristine,
        erp_dsn=f"sqlite+aiosqlite:///{erp.resolve()}",
        fresh=fresh,
    )


def db_exists(root: str | Path) -> bool:
    return (Path(root) / "ontogeny.db").exists()


def reset_demo(root: str | Path = DEFAULT_DEMO_DIR) -> None:
    """Delete the demo directory (metadata, seeded source, package copy)."""
    p = Path(root)
    if p.exists():
        shutil.rmtree(p)
