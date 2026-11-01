# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""The DSL kind registry: the single source of truth for *what a kind is*.

Eleven kinds, but three different questions are asked about them and they used
to be answered in three hand-maintained places that drifted apart:

* **Where does it live?** -> :data:`DIR_KINDS` / :data:`FLAT_FILE_KINDS`
  (previously duplicated in ``loader`` and ``builder_ops``).
* **Is it a platform resource?** -> :attr:`KindSpec.platform` (previously only
  a frontend array in ``ArchBoard.tsx``; the backend had 9/10/11 nowhere
  agreed).
* **What does it mean?** -> :attr:`KindSpec.group` + :attr:`KindSpec.layer`,
  the vocabulary the docs and the dashboard share.

The split, and why it is not negotiable:

``core`` (4)          object, link, action, policy -- without them there is no
                      model and no write gate.
``extension`` (3)     function, agent, eval -- real decision surfaces, but a
                      package can run without ever declaring one.
``adapter`` (1)       projection -- derived and optional; a configuration of
                      the graph, not a governance decision.
``baseline`` (1)      evolution policy -- the RSI rulebook, human-only, and
                      deliberately kept apart from the eval suites it governs.
``manifest`` (2)      store, ontology -- binding and package manifest; they
                      travel with the package but are not platform resources.

Nine platform resources + two manifest resources = eleven kinds. That is the
only count allowed in code, docs, and UI; ``/meta/ontology.kinds`` publishes
this table.

This module is metadata-only on purpose: it imports nothing from ``models`` so
``models`` can import *it* and assert registry/model parity at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Group = Literal["core", "extension", "adapter", "baseline", "manifest"]
Layer = Literal[
    "semantic",
    "kinetic",
    "governance",
    "agent",
    "derived",
    "evolution",
    "binding",
    "manifest",
]


@dataclass(frozen=True)
class KindSpec:
    """One DSL kind, answered once."""

    kind: str
    group: Group
    layer: Layer
    #: directory that carries this kind ("objects/" ...); ``None`` = flat file
    directory: str | None = None
    #: flat manifest-style file ("ontology.yaml", "evolution.yaml"); else None
    file: str | None = None
    #: the two CORE tags on the architecture board: the only write gate and the
    #: selection box. Purely descriptive -- the behaviour lives in the runtime.
    core: bool = False
    #: whether ``compile_package`` puts it into ``CompiledOntology``
    compiled: bool = True

    @property
    def platform(self) -> bool:
        """A platform resource, as opposed to a package-level manifest."""
        return self.group != "manifest"

    def as_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "group": self.group,
            "layer": self.layer,
            "core": self.core,
            "platform": self.platform,
        }


#: Display/document order: semantic -> kinetic -> governance -> agent -> derived
#: -> evolution -> baseline -> binding -> manifest. Platform resources first
#: so a `[k for k in KINDS if k.platform]` slice is also the board order.
KINDS: tuple[KindSpec, ...] = (
    KindSpec("ObjectType", "core", "semantic", directory="objects"),
    KindSpec("LinkType", "core", "semantic", directory="links"),
    KindSpec("Action", "core", "kinetic", directory="actions", core=True),
    KindSpec("Function", "extension", "kinetic", directory="functions"),
    KindSpec("PolicySet", "core", "governance", directory="policies"),
    KindSpec("AgentPlugin", "extension", "agent", directory="agents"),
    KindSpec("Projection", "adapter", "derived", directory="projections"),
    KindSpec("EvalSuite", "extension", "evolution", directory="evals", core=True),
    KindSpec("EvolutionPolicy", "baseline", "evolution", file="evolution.yaml"),
    KindSpec("Store", "manifest", "binding", directory="stores"),
    KindSpec("Ontology", "manifest", "manifest", file="ontology.yaml", compiled=False),
)

BY_KIND: dict[str, KindSpec] = {k.kind: k for k in KINDS}

#: directory name -> kind ("objects" -> "ObjectType")
DIR_KINDS: dict[str, str] = {k.directory: k.kind for k in KINDS if k.directory}

#: flat file name -> kind ("evolution.yaml" -> "EvolutionPolicy"); the package
#: manifest (ontology.yaml) is loaded explicitly and is therefore included.
FLAT_FILE_KINDS: dict[str, str] = {k.file: k.kind for k in KINDS if k.file}

PLATFORM_KINDS: tuple[KindSpec, ...] = tuple(k for k in KINDS if k.platform)

#: kind -> directory (``None`` for flat files), what the builder writes with
KIND_DIRS: dict[str, str | None] = {k.kind: k.directory for k in KINDS}


def as_payload() -> list[dict[str, object]]:
    """Public shape for ``/meta/ontology.kinds`` -- the UI and docs read this."""
    return [k.as_payload() for k in KINDS]
