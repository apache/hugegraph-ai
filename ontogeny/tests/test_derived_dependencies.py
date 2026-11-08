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

# LOT-2417 carries 25 wafers: double 50, quadruple 100, octuple 200
LOT = "LOT-2417"


def add_chain(sc):
    props = sc.compiled.objects["wafer-lot"].spec.properties
    # Reverse dependency order exercises both explicit target and bare-name
    # references. Each result has a marking; query masks after assembly.
    props["octuple"] = PropertyDef(type="integer", derived="target.quadruple * 2", marking="internal")
    props["quadruple"] = PropertyDef(type="integer", derived="double * 2", marking="internal")
    props["double"] = PropertyDef(type="integer", derived="target.qty_wafers * 2", marking="internal")


async def test_query_and_get_follow_dependency_order_and_mask_at_end(client):
    _, sc = client
    await sc.sync("wafer-lot")
    add_chain(sc)
    async with sc.sessionmaker() as session:
        public = await sc.query.get(session, "wafer-lot", LOT, {"id": "public"})
        visible = await sc.query.get(session, "wafer-lot", LOT, {"id": "internal", "markings": ["internal"]})
        result = await sc.query.query(
            session,
            "wafer-lot",
            {"id": "internal", "markings": ["internal"]},
            filt={"lot_id": LOT},
        )
    assert (visible["double"], visible["quadruple"], visible["octuple"]) == (50, 100, 200)
    assert result["objects"][0]["octuple"] == 200
    assert all(public[name] == "__masked__" for name in ("double", "quadruple", "octuple"))


async def test_function_sandbox_reads_the_assembled_dependency_chain(client):
    _, sc = client
    await sc.sync("wafer-lot")
    add_chain(sc)
    src = Path(sc.package_root) / "functions" / "read_derived_chain.py"
    src.write_text(
        "def main():\n    return ontogeny.query('wafer-lot', filter={'lot_id': 'LOT-2417'}, limit=1)[0]\n",
        encoding="utf-8",
    )
    fn = FunctionResource(
        apiVersion="ontogeny/v1",
        kind="Function",
        metadata=ResourceMeta(name="read-derived-chain"),
        spec=FunctionSpec(
            runtime="python",
            entry="read_derived_chain.py:main",
            capabilities=[Capability(**{"read-objects": ["wafer-lot"]})],
        ),
    )
    async with sc.sessionmaker() as session:
        row = await sc.functions.run(session, fn, {})
    assert (row["double"], row["quadruple"], row["octuple"]) == (50, 100, 200)


def test_cycle_and_its_dependants_fail_closed_but_independent_values_work(client, caplog):
    _, sc = client
    props = sc.compiled.objects["wafer-lot"].spec.properties
    props["cyclic_a"] = PropertyDef(type="integer", derived="target.cyclic_b + 1")
    props["cyclic_b"] = PropertyDef(type="integer", derived="target.cyclic_a + 1")
    props["blocked"] = PropertyDef(type="integer", derived="target.cyclic_a * 2")
    props["independent"] = PropertyDef(type="integer", derived="target.qty_wafers * 2")
    result = assemble_row(
        sc.compiled,
        "wafer-lot",
        {"qty_wafers": 5, "cyclic_a": 999, "cyclic_b": 999, "blocked": 999},
    )
    assert [result[key] for key in ("cyclic_a", "cyclic_b", "blocked")] == [None, None, None]
    assert result["independent"] == 10
    assert "cyclic derived properties" in caplog.text


def test_expression_can_read_materialized_function_value(client):
    _, sc = client
    props = sc.compiled.objects["wafer-lot"].spec.properties
    props["derived_from_materialized"] = PropertyDef(type="integer", derived="target.materialized * 2")
    props["materialized"] = PropertyDef(type="integer", derived={"kind": "function", "entry": "x.py:f"})
    result = assemble_row(sc.compiled, "wafer-lot", {"materialized": 7})
    assert result["derived_from_materialized"] == 14
