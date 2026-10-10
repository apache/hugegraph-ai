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
"""Shared data-mounting core: store resource + backing binding + publish + sync.

Used by both the builder's HTTP endpoint and the demo orchestrator, so the two
can never drift: the demo mounts data through exactly the same code the
interactive builder does.
"""
from __future__ import annotations

import csv as _csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..errors import OOError


class MountError(OOError):
    code = "MOUNT_INVALID"
    http_status = 422


@dataclass
class MountRequest:
    object_type: str
    source_kind: str                      # csv | sqlite | postgres
    store_name: str = ""
    filename: str | None = None           # csv
    content: str | None = None            # csv
    dsn: str | None = None                # sql
    table: str | None = None              # sql
    mapping: dict[str, str] = field(default_factory=dict)


async def mount_source(sc, req: MountRequest) -> dict[str, Any]:
    """Materialize the source, write the store, bind the backing, publish,
    sync, and return the run summary with quarantine detail."""
    if sc.package_root is None:
        raise MountError("ONTOGENY_PACKAGE_ROOT not configured")
    pkg_dir = Path(sc.package_root)
    if not pkg_dir.is_dir():
        raise MountError(f"package dir {pkg_dir} does not exist")
    if sc.compiled is None or req.object_type not in sc.compiled.objects:
        from ..errors import NotFoundError

        raise NotFoundError(f"unknown object type: {req.object_type}")

    props = sc.compiled.objects[req.object_type].spec.properties
    store_name = req.store_name.strip() or f"csv-{req.object_type}"
    if not store_name.replace("-", "").replace("_", "").isalnum():
        raise MountError("store name must be alphanumeric/-/_")

    # ---- materialize the data -------------------------------------------
    if req.source_kind == "csv":
        if not req.content:
            raise MountError("csv source requires content")
        filename = Path(req.filename or f"{req.object_type}.csv").name
        data_dir = pkg_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / filename).write_text(req.content, encoding="utf-8")
        connection = str(data_dir / filename)
        table = Path(filename).stem
    elif req.source_kind in ("sqlite", "postgres", "mysql"):
        if not req.dsn or not req.table:
            raise MountError(f"{req.source_kind} source requires dsn and table")
        connection = req.dsn
        table = req.table
    else:
        raise MountError(f"unsupported source kind: {req.source_kind!r}")

    # ---- store resource ---------------------------------------------------
    # CSV is a snapshot source: read-only (the validator enforces read-write =>
    # transactional). SQL sources bind read-write.
    access = "read-only" if req.source_kind == "csv" else "read-write"
    stores_dir = pkg_dir / "stores"
    stores_dir.mkdir(parents=True, exist_ok=True)
    (stores_dir / f"{store_name}.yaml").write_text(
        yaml.safe_dump({
            "apiVersion": "ontogeny/v1", "kind": "Store",
            "metadata": {"name": store_name},
            "spec": {"type": req.source_kind, "connection": connection, "access": access},
        }, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # ---- mapping (ownership semantics!) -----------------------------------
    # a prop LISTED in mapping is source-owned; one absent is ontology-owned.
    # an EMPTY mapping means full same-name direct mode = everything
    # source-owned, which strips the actions' write rights. For a CSV the
    # same-name mapping is derived from the header; SQL callers state theirs.
    mapping = dict(req.mapping)
    if not mapping and req.source_kind == "csv" and req.content:
        header = next(_csv.reader(req.content.splitlines()))
        mapping = {col: col for col in header if col in props and not props[col].derived}

    missing_required = [
        name for name, d in props.items()
        if d.required and not d.derived and name not in mapping
    ]
    if missing_required:
        raise MountError(
            f"source does not provide required properties: {', '.join(missing_required)}",
            details={"missing": missing_required},
        )

    # ---- bind the backing on disk ------------------------------------------
    obj_path = pkg_dir / "objects" / f"{req.object_type}.yaml"
    if not obj_path.is_file():
        raise MountError(f"object yaml not found: {obj_path.name}")
    obj_doc = yaml.safe_load(obj_path.read_text(encoding="utf-8")) or {}
    obj_doc.setdefault("spec", {})["backing"] = {
        "store": store_name,
        "mode": "materialized",
        "source": {"table": table},
        "mapping": mapping,
        "sync": {"strategy": "snapshot"},
    }
    obj_path.write_text(
        yaml.safe_dump(obj_doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # ---- publish + sync ------------------------------------------------------
    await sc.publish(str(pkg_dir), created_by=f"mount:{store_name}")
    async with sc.sessionmaker() as session:
        summary = await sc.sync(req.object_type)
        await session.commit()
        from ..stores.sync import QuarantineRow

        from sqlalchemy import select

        qrows = (await session.execute(
            select(QuarantineRow)
            .where(QuarantineRow.object_type == req.object_type)
            .order_by(QuarantineRow.id.desc()).limit(20)
        )).scalars().all()
    return {
        "published": True,
        "store": store_name,
        "object": req.object_type,
        "connection": connection,
        "mapping": mapping,
        "sync": {k: summary.get(k, 0) for k in ("inserted", "updated", "noop", "quarantined")},
        "quarantine": [{"pk": q.source_pk, "code": q.code, "reason": q.reason} for q in reversed(qrows)],
    }
