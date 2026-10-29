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

"""Required asynchronous derived fields may be empty until calculation."""

from pathlib import Path

import pytest_asyncio
import yaml
from sqlalchemy import select
from test_function_ecosystem import PLANNER, _pkg_with_function_property

from ontogeny.action.models import OutboxRow
from ontogeny.config import Settings
from ontogeny.demo import prepare_demo
from ontogeny.functions.derivation import DerivationPendingRow
from ontogeny.service import ServiceContext


@pytest_asyncio.fixture()
async def required_sc(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", "fixture-password")
    pkg_root = _pkg_with_function_property(tmp_path / "pkg-src")
    product_path = pkg_root / "objects" / "product.yaml"
    product = yaml.safe_load(product_path.read_text())
    product["spec"]["properties"]["open_order_count"]["required"] = True
    product_path.write_text(yaml.safe_dump(product, sort_keys=False))
    paths = prepare_demo(tmp_path / "demo", package=pkg_root)
    env = paths.as_env()
    sc = ServiceContext(Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env), env["ONTOGENY_PACKAGE_ROOT"])
    await sc.initialize()
    try:
        yield sc
    finally:
        await sc.engine.dispose()


async def test_sync_and_action_create_before_real_worker_materializes(required_sc):
    from sqlalchemy import inspect

    sc = required_sc
    async with sc.engine.connect() as connection:
        cols = await connection.run_sync(lambda c: inspect(c).get_columns("ontogeny_obj_product"))
    nullability = {column["name"]: column["nullable"] for column in cols}
    assert nullability["open_order_count"] is True
    assert nullability["name"] is False
    assert (await sc.sync("product"))["inserted"] > 0
    await sc.sync("production-order")
    async with sc.sessionmaker() as session:
        product = await sc.repo.get(session, "product", "P-200")
        assert product["open_order_count"] is None
        revision = await sc.runtime.execute(session, "introduce-product", PLANNER, {"name": "New product"})
        await session.commit()
        new_id = revision.object_id
        assert (await sc.repo.get(session, "product", new_id))["open_order_count"] is None
    await sc.outbox.dispatch_pending()
    async with sc.sessionmaker() as session:
        assert (await sc.repo.get(session, "product", "P-200"))["open_order_count"] == 1
        assert (await sc.repo.get(session, "product", new_id))["open_order_count"] == 0


async def test_required_none_result_keeps_previous_value_and_pending_retry(required_sc):
    sc = required_sc
    await sc.sync("product")
    await sc.sync("production-order")
    await sc.outbox.dispatch_pending()
    async with sc.sessionmaker() as session:
        assert (await sc.repo.get(session, "product", "P-200"))["open_order_count"] == 1
    source = Path(sc.compiled.package_root) / "functions" / "order_count.py"
    source.write_text("def open_order_count(obj):\n    return None\n", encoding="utf-8")
    await sc.derivation.handle_event(OutboxRow(object_type="product", object_id="P-200", op="upsert"))
    await sc.derivation.drain()
    async with sc.sessionmaker() as session:
        assert (await sc.repo.get(session, "product", "P-200"))["open_order_count"] == 1
        queued = (await session.scalars(select(DerivationPendingRow))).all()
        assert any(row.object_type == "product" and row.object_id == "P-200" for row in queued)


async def test_function_derived_primary_key_remains_non_nullable(required_sc):
    from dataclasses import replace

    from ontogeny.stores.ddl import object_table

    sc = required_sc
    product = sc.compiled.objects["product"].model_copy(deep=True)
    product.spec.properties["product_id"].derived = {"kind": "function", "entry": "order_count.py:open_order_count"}
    compiled = replace(
        sc.compiled, content_hash="derived-primary-key-test", objects={**sc.compiled.objects, "product": product}
    )
    key = object_table(compiled, "product").c.product_id
    assert key.primary_key and not key.nullable
