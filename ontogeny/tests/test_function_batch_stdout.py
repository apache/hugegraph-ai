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

from pathlib import Path

from test_function_ecosystem import sc as _derivation_sc

from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, ResourceMeta

derivation_sc = _derivation_sc


async def test_batch_user_prints_do_not_corrupt_protocol_or_query_rpc(client):
    _, sc = client
    await sc.sync("work-center")
    source = Path(sc.package_root) / "functions" / "printing_batch.py"
    source.write_text(
        "def compute(obj):\n"
        "    print('working on', obj['name'])\n"
        "    rows = ontogeny.query('work-center', filter={'work_center_id': 'WC-01'})\n"
        "    print('query complete')\n"
        "    return {'name': obj['name'], 'found': len(rows)}\n",
        encoding="utf-8",
    )
    fn = FunctionResource(
        apiVersion="ontogeny/v1",
        kind="Function",
        metadata=ResourceMeta(name="printing-batch"),
        spec=FunctionSpec(
            runtime="python",
            entry="printing_batch.py:compute",
            capabilities=[Capability(**{"read-objects": ["work-center"]})],
        ),
    )
    async with sc.sessionmaker() as session:
        values = await sc.sandbox.map_rows(session, fn, [{"name": "first"}, {"name": "second"}])
    assert values == [{"name": "first", "found": 1}, {"name": "second", "found": 1}]


async def test_derivation_batch_function_may_print_while_reading_objects(derivation_sc):
    sc = derivation_sc
    source = Path(sc.package_root) / "functions" / "order_count.py"
    text = source.read_text(encoding="utf-8")
    source.write_text(
        text.replace(
            "def open_order_count(obj: dict) -> int:\n",
            "def open_order_count(obj: dict) -> int:\n    print('deriving')\n",
        ),
        encoding="utf-8",
    )
    await sc.outbox.dispatch_pending()
    async with sc.sessionmaker() as session:
        product = await sc.repo.get(session, "product", "P-200")
    assert product["open_order_count"] == 1
