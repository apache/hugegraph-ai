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
"""Package loader: directory -> OntologyPackage.

Layout (dsl-spec §2): ontology.yaml manifest + stores/ objects/ links/
actions/ functions/ projections/ evals/ policies/ + evolution.yaml.
Non-YAML sidecars (.py, .cedar) are carried as file references, not parsed
here. Loading is pure: no IO beyond reading the package directory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..errors import DSLValidationError
from .models import (
    RESOURCE_BY_KIND,
    ActionResource,
    AgentPluginResource,
    AnyResource,
    EvalSuiteResource,
    EvolutionPolicyResource,
    FunctionResource,
    LinkTypeResource,
    ObjectTypeResource,
    OntologyResource,
    PolicySetResource,
    ProjectionResource,
    StoreResource,
)

_SIDECAR_DIRS = {"PolicySet": "policies", "Function": "functions"}

_DIR_KINDS = {
    "stores": "Store",
    "objects": "ObjectType",
    "links": "LinkType",
    "actions": "Action",
    "functions": "Function",
    "projections": "Projection",
    "evals": "EvalSuite",
    "agents": "AgentPlugin",
    "policies": "PolicySet",
}


@dataclass
class OntologyPackage:
    root: Path
    manifest: OntologyResource
    resources: list[AnyResource] = field(default_factory=list)
    # apiName -> source file path (for diff/merge by the evolution promoter)
    files: dict[tuple[str, str], Path] = field(default_factory=dict)
    # inline sidecar contents (kind/name -> text), e.g. .cedar policy bodies.
    # Persisted alongside metadata so a registry rebuilt from the database does
    # not silently lose policy rules (functions still need the package on disk).
    source_texts: dict[tuple[str, str], str] = field(default_factory=dict)

    def sidecar_text(self, kind: str, name: str, relative: str) -> str:
        """Text of a sidecar file: inline copy first, then the package on disk."""
        inline = self.source_texts.get((kind, name))
        if inline is not None:
            return inline
        path = Path(self.root) / _SIDECAR_DIRS.get(kind, "") / relative
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    # -- typed accessors -----------------------------------------------------

    def by_kind(self, kind: str) -> list[AnyResource]:
        return [r for r in self.resources if r.kind == kind]

    def find(self, kind: str, name: str) -> AnyResource | None:
        for r in self.resources:
            if r.kind == kind and r.metadata.name == name:
                return r
        return None

    def stores(self) -> list[StoreResource]:
        return [r for r in self.resources if isinstance(r, StoreResource)]  # type: ignore[list-item]

    def objects(self) -> list[ObjectTypeResource]:
        return [r for r in self.resources if isinstance(r, ObjectTypeResource)]  # type: ignore[list-item]

    def links(self) -> list[LinkTypeResource]:
        return [r for r in self.resources if isinstance(r, LinkTypeResource)]  # type: ignore[list-item]

    def actions(self) -> list[ActionResource]:
        return [r for r in self.resources if isinstance(r, ActionResource)]  # type: ignore[list-item]

    def functions(self) -> list[FunctionResource]:
        return [r for r in self.resources if isinstance(r, FunctionResource)]  # type: ignore[list-item]

    def policies(self) -> list[PolicySetResource]:
        return [r for r in self.resources if isinstance(r, PolicySetResource)]  # type: ignore[list-item]

    def projections(self) -> list[ProjectionResource]:
        return [r for r in self.resources if isinstance(r, ProjectionResource)]  # type: ignore[list-item]

    def agent_plugins(self) -> list[AgentPluginResource]:
        return [r for r in self.resources if isinstance(r, AgentPluginResource)]  # type: ignore[list-item]

    def eval_suites(self) -> list[EvalSuiteResource]:
        return [r for r in self.resources if isinstance(r, EvalSuiteResource)]  # type: ignore[list-item]

    def evolution_policy(self) -> EvolutionPolicyResource | None:
        for r in self.resources:
            if isinstance(r, EvolutionPolicyResource):
                return r  # type: ignore[return-value]
        return None


def _parse_file(path: Path, expected_kind: str | None = None) -> AnyResource:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DSLValidationError(f"YAML parse error in {path.name}: {exc}", details={"file": str(path)}) from exc
    if not isinstance(raw, dict):
        raise DSLValidationError(f"{path.name}: resource must be a mapping", details={"file": str(path)})
    kind = raw.get("kind")
    if expected_kind and kind != expected_kind:
        raise DSLValidationError(
            f"{path.name}: expected kind {expected_kind}, got {kind}",
            details={"file": str(path), "kind": str(kind)},
        )
    cls = RESOURCE_BY_KIND.get(str(kind))
    if cls is None:
        raise DSLValidationError(
            f"{path.name}: unknown kind {kind!r}", details={"file": str(path), "kind": str(kind)}
        )
    try:
        return cls.model_validate(raw)
    except Exception as exc:
        raise DSLValidationError(
            f"{path.name}: invalid {kind} resource: {exc}", details={"file": str(path)}
        ) from exc


def load_package(root: str | Path) -> OntologyPackage:
    root = Path(root)
    manifest_path = root / "ontology.yaml"
    if not manifest_path.is_file():
        raise DSLValidationError(f"no ontology.yaml under {root}", details={"root": str(root)})
    manifest = _parse_file(manifest_path, expected_kind="Ontology")

    resources: list[AnyResource] = []
    files: dict[tuple[str, str], Path] = {}

    for dirname, kind in _DIR_KINDS.items():
        d = root / dirname
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.yaml")):
            res = _parse_file(f, expected_kind=kind)
            resources.append(res)
            files[(res.kind, res.metadata.name)] = f

    evo_path = root / "evolution.yaml"
    if evo_path.is_file():
        res = _parse_file(evo_path, expected_kind="EvolutionPolicy")
        resources.append(res)
        files[(res.kind, res.metadata.name)] = evo_path

    return OntologyPackage(root=root, manifest=manifest, resources=resources, files=files)
