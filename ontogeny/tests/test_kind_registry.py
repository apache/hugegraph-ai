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

"""The kind taxonomy is a single table -- and this file freezes it.

Nine platform resources (4 core + 3 extension + 1 adapter + 1 baseline) plus
two manifest resources (Store, Ontology) = eleven kinds. The numbers used to be
8 / 9 / 10 / 11 / "nine" in five different places; adding or removing a kind
must now be a visible, reviewed edit to ``EXPECTED`` below, not a silent
side-effect of touching a model file.
"""

from __future__ import annotations

from ontogeny.core.kinds import (
    BY_KIND,
    DIR_KINDS,
    FLAT_FILE_KINDS,
    KIND_DIRS,
    KINDS,
    PLATFORM_KINDS,
    as_payload,
)
from ontogeny.core.models import RESOURCE_BY_KIND
from ontogeny.registry.compiled import compile_package

#: (kind, group) in display order. A change here is the taxonomy change.
EXPECTED = [
    ("ObjectType", "core"),
    ("LinkType", "core"),
    ("Action", "core"),
    ("Function", "extension"),
    ("PolicySet", "core"),
    ("AgentPlugin", "extension"),
    ("Projection", "adapter"),
    ("EvalSuite", "extension"),
    ("EvolutionPolicy", "baseline"),
    ("Store", "manifest"),
    ("Ontology", "manifest"),
]


class TestTaxonomy:
    def test_kinds_are_frozen(self):
        assert [(k.kind, k.group) for k in KINDS] == EXPECTED

    def test_nine_platform_resources_and_two_manifest_resources(self):
        assert len(PLATFORM_KINDS) == 9
        assert [k.kind for k in KINDS if k.group == "manifest"] == ["Store", "Ontology"]
        assert {k.layer for k in KINDS} == {
            "semantic",
            "kinetic",
            "governance",
            "agent",
            "derived",
            "evolution",
            "binding",
            "manifest",
        }

    def test_only_the_two_governance_halves_are_core(self):
        # CORE = the only write gate (Action) and the selection box (EvalSuite).
        assert [k.kind for k in KINDS if k.core] == ["Action", "EvalSuite"]

    def test_registry_and_models_agree(self):
        # models.py enforces this at import time too; keep the test so a future
        # refactor cannot quietly drop the guard.
        assert set(RESOURCE_BY_KIND) == set(BY_KIND)

    def test_directories_and_flat_files_are_unique(self):
        dirs = [k.directory for k in KINDS if k.directory]
        assert len(dirs) == len(set(dirs))
        assert {k.directory: k.kind for k in KINDS if k.directory} == DIR_KINDS
        assert {k.file: k.kind for k in KINDS if k.file} == FLAT_FILE_KINDS
        assert set(FLAT_FILE_KINDS) == {"ontology.yaml", "evolution.yaml"}

    def test_builder_writes_every_kind(self):
        assert set(KIND_DIRS) == set(BY_KIND)
        assert {v for v in KIND_DIRS.values() if v} == set(DIR_KINDS)
        assert KIND_DIRS["EvolutionPolicy"] is None and KIND_DIRS["Ontology"] is None

    def test_every_kind_is_compiled_except_the_manifest(self):
        assert {k.kind for k in KINDS if not k.compiled} == {"Ontology"}


class TestGoldenPackage:
    def test_loads_every_compiled_kind(self, golden_pkg):
        assert {r.kind for r in golden_pkg.resources} == {k.kind for k in KINDS if k.compiled}
        assert golden_pkg.manifest.kind == "Ontology"

    def test_meta_publishes_the_taxonomy(self, golden_pkg):
        meta = compile_package(golden_pkg).to_meta()
        assert meta["kinds"] == as_payload()
        assert {k["kind"] for k in meta["kinds"]} == set(BY_KIND)
        assert sum(1 for k in meta["kinds"] if k["platform"]) == 9
        assert {k["kind"] for k in meta["kinds"] if k["core"]} == {"Action", "EvalSuite"}

    async def test_api_meta_exposes_the_same_table(self, client):
        c, _ = client
        body = (await c.get("/api/v1/meta/ontology")).json()
        assert body["kinds"] == as_payload()
