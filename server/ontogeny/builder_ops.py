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
"""Builder materialization: resource JSON -> YAML files -> validated publish.

Used to be ~190 lines of file orchestration inside the HTTP handler; it is a
platform operation (the role manager writes managed Cedar through it too), so
it lives at the service level where CLI/other shells can reach it. Raises
``DSLValidationError`` instead of returning error responses."""
from __future__ import annotations

from pathlib import Path
from typing import Any


async def builder_save(sc, resources: list[dict[str, Any]], *, deletes: list[str] | None = None,
                       layout: dict[str, Any] | None = None, story: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from .core import load_package, validate as _v
    from .core.models import RESOURCE_BY_KIND
    from .errors import DSLValidationError

    body = _Body(resources=resources, deletes=deletes, layout=layout, story=story)

    """Scenario Builder: accept resource JSON → write YAML to pkg dir → publish.

    The package_root must be writable (a demo data-dir copy or a git work
    tree). The builder sends only the resources it touched (partial save is
    the data-loss-safe default: untouched YAML on disk is never rewritten
    from lossy meta), plus explicit ``deletes`` for removed resources.
    """
    import yaml as _yaml

    if sc.package_root is None:
        raise DSLValidationError("ONTOGENY_PACKAGE_ROOT not configured")
    pkg_dir = Path(sc.package_root)
    if not pkg_dir.is_dir():
        raise DSLValidationError(f"package dir {pkg_dir} does not exist")



    # Inline data-source declarations: the console's data-mount editor puts
    # the source INTO backing.store_spec ({kind, connection}) — a bare store
    # name would be a placeholder, not a source. Extract it before the
    # pydantic parse (BackingSpec has no such field) and materialize it as
    # stores/<store>.yaml right after (same pattern as PolicySet cedar
    # sidecars). The object YAML on disk stays clean.
    store_sidecars: list[tuple[str, str, str]] = []
    for raw in resources:
        if raw.get("kind") != "ObjectType":
            continue
        backing = (raw.get("spec") or {}).get("backing") or {}
        store_spec = backing.get("store_spec")
        store_name = str(backing.get("store") or "").strip()
        if isinstance(store_spec, dict) and store_name:
            kind = str(store_spec.get("kind") or "").strip()
            connection = str(store_spec.get("connection") or "").strip()
            if kind and connection:
                store_sidecars.append((store_name, kind, connection))
            backing.pop("store_spec", None)

    # parse + validate all resources client-side model
    parsed = []
    errors = []
    for raw in resources:
        kind = raw.get("kind", "")
        cls = RESOURCE_BY_KIND.get(kind)
        if cls is None:
            errors.append({"resource": kind, "message": f"unknown kind {kind!r}"})
            continue
        try:
            parsed.append(cls.model_validate(raw))
        except Exception as exc:
            errors.append({"resource": f"{kind}/{raw.get('metadata',{}).get('name','?')}",
                           "message": str(exc)[:200]})
    if errors:
        # the console shows per-resource errors; raise and let the HTTP shell
        # keep its legacy 422 envelope
        raise DSLValidationError("builder resources failed validation", details={"errors": errors})

    # write YAML files into the package directory (grouped by kind)
    _DIR_MAP = {"Store": "stores", "ObjectType": "objects", "LinkType": "links",
                "Action": "actions", "Function": "functions", "PolicySet": "policies",
                "Projection": "projections", "EvalSuite": "evals", "AgentPlugin": "agents",
                "EvolutionPolicy": None, "Ontology": None}
    # Ontology → ontology.yaml; EvolutionPolicy → evolution.yaml (flat files)
    manifest = next((r for r in parsed if r.kind == "Ontology"), None)
    if manifest is None:
        # keep existing manifest if builder doesn't send one
        existing_manifest = pkg_dir / "ontology.yaml"
        if existing_manifest.is_file():
            from .core.models import OntologyResource
            manifest = OntologyResource.model_validate(_yaml.safe_load(existing_manifest.read_text(encoding="utf-8")))

    import yaml as _yaml_mod
    # ObjectType store sidecars: the console's data-mount editor declares the
    # source INLINE as backing.store_spec ({kind, connection}) because a bare
    # store NAME would be a placeholder, not a source. Materialize it as
    # stores/<store>.yaml (same pattern as PolicySet cedar sidecars) and strip
    # it from the object YAML -- BackingSpec has no such field on disk.
    for res in parsed:
        if res.kind != "ObjectType":
            continue
        backing = (res.spec.get("backing") if isinstance(res.spec, dict) else None) or {}
        store_spec = backing.get("store_spec")
        if not isinstance(store_spec, dict):
            continue
        store_name = str(backing.get("store") or "").strip()
        kind = str(store_spec.get("kind") or "").strip()
        connection = str(store_spec.get("connection") or "").strip()
        if not store_name or not kind or not connection:
            raise DSLValidationError(
                f"ObjectType/{res.metadata.name}: incomplete data source — "
                "store name, source type and connection are all required",
                details={"store": store_name, "kind": kind},
            )
        access = "read-only" if kind == "csv" else "read-write"
        stores_dir = pkg_dir / "stores"
        stores_dir.mkdir(parents=True, exist_ok=True)
        (stores_dir / f"{store_name}.yaml").write_text(
            _yaml_mod.safe_dump({
                "apiVersion": "ontogeny/v1", "kind": "Store",
                "metadata": {"name": store_name},
                "spec": {"type": kind, "connection": connection, "access": access},
            }, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    # PolicySet sidecars: spec.source is a FILE reference (policies/<name>.cedar),
    # not inline text. The builder sends the cedar text inline; materialize it
    # as the sidecar and rewrite source to the conventional filename -- inline
    # text would be lost on the next disk load, silently default-denying.
    for res in parsed:
        if res.kind == "PolicySet" and not res.spec.source.strip().endswith(".cedar"):
            pol_dir = pkg_dir / "policies"
            pol_dir.mkdir(parents=True, exist_ok=True)
            (pol_dir / f"{res.metadata.name}.cedar").write_text(res.spec.source, encoding="utf-8")
            res.spec.source = f"{res.metadata.name}.cedar"

    # tracked deletions first (also cleans a renamed resource's old file)
    removed = []
    for entry in deletes or []:
        kind, _, name = entry.partition("/")
        subdir = _DIR_MAP.get(kind)
        if subdir and "/" not in name and ".." not in name and name:
            fp = pkg_dir / subdir / f"{name}.yaml"
            if fp.is_file():
                fp.unlink()
                removed.append(entry)
            if kind == "PolicySet":
                sidecar = pkg_dir / "policies" / f"{name}.cedar"
                if sidecar.is_file():
                    sidecar.unlink()

    written = []
    for res in parsed:
        subdir = _DIR_MAP.get(res.kind)
        if subdir is None:
            continue
        d = pkg_dir / subdir
        d.mkdir(parents=True, exist_ok=True)
        fp = d / f"{res.metadata.name}.yaml"
        payload = res.model_dump(mode="json", by_alias=True, exclude_none=True)
        fp.write_text(_yaml_mod.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        written.append(f"{res.kind}/{res.metadata.name}")
    # manifest
    if manifest is not None:
        (pkg_dir / "ontology.yaml").write_text(
            _yaml_mod.safe_dump(manifest.model_dump(mode="json", by_alias=True, exclude_none=True),
                                allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Enforce one YAML file per (kind, metadata.name). A resource renamed by
    # a prior save can otherwise leave the old filename behind; the next
    # load then sees two resources with the same identity and the package
    # becomes unswitchable with DUP-NAME. Prefer the conventional
    # `<metadata.name>.yaml` filename when both exist.
    for subdir in {v for v in _DIR_MAP.values() if v}:
        d = pkg_dir / subdir
        if not d.is_dir():
            continue
        by_name: dict[str, list[Path]] = {}
        for fp in sorted(d.glob("*.yaml")):
            try:
                doc = _yaml_mod.safe_load(fp.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001 -- malformed files fail in validate()
                continue
            name = (doc.get("metadata") or {}).get("name")
            if isinstance(name, str):
                by_name.setdefault(name, []).append(fp)
        for name, files in by_name.items():
            if len(files) <= 1:
                continue
            preferred = next((f for f in files if f.stem == name), files[0])
            for fp in files:
                if fp != preferred:
                    fp.unlink()

    # reload from disk and publish
    compiled = await sc.publish(str(pkg_dir), created_by="builder")

    # the layout is committed alongside the model: a drag is an edit like
    # any other, so it lands on disk only when the user saves
    if layout is not None:
        sc.write_layout(body.layout)

    # run validation report for the response
    rep = _v(load_package(str(pkg_dir)))
    return {
        "published": True,
        "content_hash": compiled.content_hash,
        "written": written,
        "removed": removed,
        "issues": [{"code": i.code, "severity": i.severity, "message": i.message} for i in rep.issues],
    }



class _Body:
    """Keyword bag so the moved implementation reads exactly as it did inside
    the HTTP handler (body.resources / body.deletes / body.layout)."""

    def __init__(self, resources, deletes, layout, story):
        self.resources = resources
        self.deletes = deletes
        self.layout = layout
        self.story = story
