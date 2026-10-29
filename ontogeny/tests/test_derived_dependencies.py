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

"""Read-time derived properties may depend on other derived properties."""

from pathlib import Path

from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, PropertyDef, ResourceMeta
from ontogeny.engine.service import assemble_row


def add_chain(sc):
    props = sc.compiled.objects["work-center"].spec.properties
    # Reverse dependency order exercises both explicit target and bare-name
    # references. Each result has a marking; query masks after assembly.
    props["octuple"] = PropertyDef(type="integer", derived="target.quadruple * 2", marking="internal")
    props["quadruple"] = PropertyDef(type="integer", derived="double * 2", marking="internal")
    props["double"] = PropertyDef(type="integer", derived="target.capacity_per_shift * 2", marking="internal")


async def test_query_and_get_follow_dependency_order_and_mask_at_end(client):
    _, sc = client
    await sc.sync("work-center")
    add_chain(sc)
    async with sc.sessionmaker() as session:
        public = await sc.query.get(session, "work-center", "WC-01", {"id": "public"})
        visible = await sc.query.get(session, "work-center", "WC-01", {"id": "internal", "markings": ["internal"]})
        result = await sc.query.query(
            session,
            "work-center",
            {"id": "internal", "markings": ["internal"]},
            filt={"work_center_id": "WC-01"},
        )
    assert (visible["double"], visible["quadruple"], visible["octuple"]) == (800, 1600, 3200)
    assert result["objects"][0]["octuple"] == 3200
    assert all(public[name] == "__masked__" for name in ("double", "quadruple", "octuple"))


async def test_function_sandbox_reads_the_assembled_dependency_chain(client):
    _, sc = client
    await sc.sync("work-center")
    add_chain(sc)
    src = Path(sc.package_root) / "functions" / "read_derived_chain.py"
    src.write_text(
        "def main():\n    return ontogeny.query('work-center', filter={'work_center_id': 'WC-01'}, limit=1)[0]\n",
        encoding="utf-8",
    )
    fn = FunctionResource(
        apiVersion="ontogeny/v1",
        kind="Function",
        metadata=ResourceMeta(name="read-derived-chain"),
        spec=FunctionSpec(
            runtime="python",
            entry="read_derived_chain.py:main",
            capabilities=[Capability(**{"read-objects": ["work-center"]})],
        ),
    )
    async with sc.sessionmaker() as session:
        row = await sc.functions.run(session, fn, {})
    assert (row["double"], row["quadruple"], row["octuple"]) == (800, 1600, 3200)


def test_cycle_and_its_dependants_fail_closed_but_independent_values_work(client, caplog):
    _, sc = client
    props = sc.compiled.objects["work-center"].spec.properties
    props["cyclic_a"] = PropertyDef(type="integer", derived="target.cyclic_b + 1")
    props["cyclic_b"] = PropertyDef(type="integer", derived="target.cyclic_a + 1")
    props["blocked"] = PropertyDef(type="integer", derived="target.cyclic_a * 2")
    props["independent"] = PropertyDef(type="integer", derived="target.capacity_per_shift * 2")
    result = assemble_row(
        sc.compiled,
        "work-center",
        {"capacity_per_shift": 5, "cyclic_a": 999, "cyclic_b": 999, "blocked": 999},
    )
    assert [result[key] for key in ("cyclic_a", "cyclic_b", "blocked")] == [None, None, None]
    assert result["independent"] == 10
    assert "cyclic derived properties" in caplog.text


def test_expression_can_read_materialized_function_value(client):
    _, sc = client
    props = sc.compiled.objects["work-center"].spec.properties
    props["derived_from_materialized"] = PropertyDef(type="integer", derived="target.materialized * 2")
    props["materialized"] = PropertyDef(type="integer", derived={"kind": "function", "entry": "x.py:f"})
    result = assemble_row(sc.compiled, "work-center", {"materialized": 7})
    assert result["derived_from_materialized"] == 14
