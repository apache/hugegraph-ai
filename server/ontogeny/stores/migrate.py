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
"""Schema migration planner: what stands between the DSL and the live tables.

``ensure_tables`` (ddl.py) only ever ADDS columns -- additive evolution must
just work. Everything else (a renamed property, a type change, a dropped
property, a renamed object leaving an orphan table) silently left data behind:
renames surfaced as all-NULL columns, orphans as data disappearing from the
API. The DDL module's own comment promised ``ontogeny migrate``; this is it.

Deliberately a PLAN generator, not an executor: destructive statements against
authoritative data are printed for a human to review and run. ``--apply`` runs
only the safe class (additive); destructive steps always stay manual.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import inspect, text

from .ddl import object_table


@dataclass
class MigrationStep:
    kind: str  # add-column | type-change | drop-column | drop-table | rename-hint
    table: str
    column: str | None = None
    sql: str | None = None
    note: str = ""

    def render(self) -> str:
        head = f"{self.kind:13} {self.table}" + (f".{self.column}" if self.column else "")
        lines = [head]
        if self.note:
            lines.append(f"              -- {self.note}")
        if self.sql:
            lines.append(f"              {self.sql};")
        return "\n".join(lines)


@dataclass
class MigrationPlan:
    steps: list[MigrationStep] = field(default_factory=list)

    @property
    def safe(self) -> list[MigrationStep]:
        return [s for s in self.steps if s.kind == "add-column"]

    @property
    def destructive(self) -> list[MigrationStep]:
        return [s for s in self.steps if s.kind != "add-column"]

    def render(self) -> str:
        if not self.steps:
            return "schema is in sync with the DSL (nothing to do)"
        out = []
        if self.safe:
            out.append("-- safe (additive; --apply runs these) --")
            out += [s.render() for s in self.safe]
        if self.destructive:
            out.append("-- DESTRUCTIVE (review + run by hand; data loss is permanent) --")
            out += [s.render() for s in self.destructive]
        return "\n".join(out)


def plan_migration(conn, compiled) -> MigrationPlan:
    """Diff the compiled snapshot (the DSL's truth) against the live database."""
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    plan = MigrationPlan()

    live_object_tables = {t for t in existing_tables if t.startswith("ontogeny_obj_")}
    dsl_tables = {compiled.table_name(name): name for name, obj in compiled.objects.items()
                  if obj.spec.backing is not None}

    for table, object_type in sorted(dsl_tables.items()):
        t = object_table(compiled, object_type)
        if table not in existing_tables:
            continue  # ensure_tables will create it; not a migration
        present = {c["name"]: c for c in inspector.get_columns(table)}
        for column in t.columns:
            if column.name in present:
                live_type = present[column.name]["type"].compile(conn.dialect)
                dsl_type = column.type.compile(conn.dialect)
                # cheap textual comparison: same family names (VARCHAR/TEXT
                # spellings differ per dialect) are not a semantic change we
                # can decide here -- flag only clearly different families
                fam_live = _type_family(live_type)
                fam_dsl = _type_family(dsl_type)
                if fam_live and fam_dsl and fam_live != fam_dsl:
                    plan.steps.append(MigrationStep(
                        "type-change", table, column.name,
                        sql=f"-- live {live_type} vs DSL {dsl_type}",
                        note=(f"cannot be applied automatically: back up, convert the "
                              f"column data, then ALTER TABLE {table} ALTER COLUMN "
                              f"{column.name} TYPE {dsl_type}"),
                    ))
            else:
                ddl_type = column.type.compile(conn.dialect)
                plan.steps.append(MigrationStep(
                    "add-column", table, column.name,
                    sql=f"ALTER TABLE {table} ADD COLUMN {column.name} {ddl_type}",
                    note="safe: ensure_tables applies this on next start too",
                ))

    # orphaned object tables: the DSL no longer declares this object (rename or
    # delete). Renames need data movement; deletes need a decision.
    for table in sorted(live_object_tables - set(dsl_tables)):
        note = ("the DSL no longer declares this object: if it was RENAMED, move the "
                "rows to the new table by hand; only DROP when the object is really gone")
        plan.steps.append(MigrationStep("drop-table", table, sql=f"DROP TABLE {table}", note=note))

    # dropped/renamed properties: a column the live table has but the DSL no
    # longer declares. A rename means data stranded in the old column.
    for table, object_type in sorted(dsl_tables.items()):
        if table not in existing_tables:
            continue
        t = object_table(compiled, object_type)
        dsl_cols = {c.name for c in t.columns}
        present = {c["name"] for c in inspector.get_columns(table)}
        for column in sorted(present - dsl_cols):
            plan.steps.append(MigrationStep(
                "drop-column", table, column,
                sql=f"ALTER TABLE {table} DROP COLUMN {column}",
                note=("the DSL no longer declares this property: if it was RENAMED, "
                      "back the value up first (ALTER TABLE ... RENAME COLUMN is the "
                      "data-preserving form)"),
            ))
    return plan


def _type_family(ddl: str) -> str | None:
    """Coarse type family for change detection; None = give up comparing."""
    d = ddl.upper()
    for fam, names in {
        "int": ("BIGINT", "INTEGER", "INT", "SMALLINT"),
        "float": ("DOUBLE", "FLOAT", "REAL", "NUMERIC", "DECIMAL"),
        "text": ("TEXT", "VARCHAR", "CHAR", "STRING", "CLOB"),
        "bool": ("BOOLEAN", "BOOL"),
        "date": ("DATE",),
        "json": ("JSON", "JSONB"),
    }.items():
        if any(n in d for n in names):
            return fam
    return None


def apply_safe(conn, plan: MigrationPlan) -> int:
    """Run the additive steps only. Everything else stays a printed decision."""
    n = 0
    for step in plan.safe:
        if step.sql:
            conn.execute(text(step.sql))
            n += 1
    return n


def summary_payload(plan: MigrationPlan) -> dict[str, Any]:
    """Machine-readable form (tests / future API surface)."""
    return {
        "safe": [{"table": s.table, "column": s.column, "sql": s.sql} for s in plan.safe],
        "destructive": [{"kind": s.kind, "table": s.table, "column": s.column,
                         "note": s.note} for s in plan.destructive],
    }
