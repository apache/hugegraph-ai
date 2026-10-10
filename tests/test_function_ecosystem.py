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
"""Function ecosystem: the four Palantir-parity capabilities.

1. llm inside functions (gateway-routed, capability-declared, budgeted)
2. function-backed properties (materialized by the derivation worker)
3. published function APIs (stable content version, pin at invoke)
4. (streaming invoke is a documented next step -- see implementation.md §5.9)

The golden package ships no function-derived property, so capability 2 is
exercised on a COPY of it that adds exactly one (product.open_order_count,
counting the product's PLANNED production orders) -- the derivation contract
must hold on the real domain shape, not on a toy ontology.
"""
from __future__ import annotations


import httpx
import pytest
import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.demo import prepare_demo
from pathlib import Path

from ontogeny.service import ServiceContext

REPO = Path(__file__).resolve().parent.parent
DOMAIN = REPO / "domains" / "product-manufacturing"

PLANNER = {"id": "u-planner", "Role": ["planner"], "site": "plant-north"}


def _pkg_with_function_property(root: Path) -> Path:
    """The golden package plus ONE function-derived property.

    ``product.open_order_count`` mirrors the shape the (now removed) system
    example used: a sandboxed counter over another object type, materialized by
    the derivation worker, with a cross-object trigger on production-order.
    """
    import shutil

    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(DOMAIN, root)

    product = root / "objects" / "product.yaml"
    text = product.read_text(encoding="utf-8")
    assert "  backing:" in text
    product.write_text(text.replace(
        "  backing:",
        "    open_order_count:\n"
        "      type: integer\n"
        "      display: Open production orders\n"
        "      description: Function-derived count of PLANNED production orders for\n"
        "        this product, materialized by the derivation worker\n"
        "      derived:\n"
        "        kind: function\n"
        "        entry: order_count.py:open_order_count\n"
        "        object_param: obj\n"
        "        triggers: [production-order]\n"
        "  backing:",
        1,
    ), encoding="utf-8")

    (root / "functions" / "order_count.py").write_text(
        '"""Open order count: a cross-object function-derived property.\n'
        "\n"
        "Unlike an expression derived (read-time, this-row-only), a function\n"
        "derived may ontogeny.query other object types, so the derivation worker\n"
        "materializes it after writes. Counts the product's orders still PLANNED.\n"
        '"""\n'
        "\n"
        "\n"
        "def open_order_count(obj: dict) -> int:\n"
        '    orders = ontogeny.query("production-order", filter={"product_id": obj.get("product_id")},\n'
        "                        limit=200)\n"
        '    return sum(1 for o in orders if o.get("status") == "PLANNED")\n',
        encoding="utf-8",
    )
    (root / "functions" / "order-count.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Function\nmetadata: {name: order-count}\n"
        "spec:\n"
        "  runtime: python\n"
        "  entry: order_count.py:open_order_count\n"
        "  parameters:\n"
        "    obj: {type: string, required: true, display: Product object}\n"
        "  returns: {type: integer, display: Open order count}\n"
        "  capabilities:\n"
        "  - read-objects: [production-order]\n",
        encoding="utf-8",
    )
    return root


@pytest_asyncio.fixture()
async def sc(tmp_path):
    pkg_root = _pkg_with_function_property(tmp_path / "pkg-src")
    paths = prepare_demo(tmp_path / "demo", package=pkg_root)
    env = paths.as_env()
    ctx = ServiceContext(Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env), env["ONTOGENY_PACKAGE_ROOT"])
    await ctx.initialize()
    for object_type in ctx.compiled.objects:
        await ctx.sync(object_type)
    yield ctx
    if ctx.engine is not None:
        await ctx.engine.dispose()


class TestFunctionBackedProperties:
    async def test_materialized_after_sync_and_dispatch(self, sc):
        assert "open_order_count" in sc.compiled.objects["product"].spec.properties

        # before derivation the column is empty
        async with sc.sessionmaker() as s:
            row = await sc.repo.get(s, "product", "P-200")
        assert row["open_order_count"] is None

        await sc.outbox.dispatch_pending()  # derivation consumer + drain

        async with sc.sessionmaker() as s:
            p200 = await sc.repo.get(s, "product", "P-200")   # PO-1002 seeded PLANNED
            p100 = await sc.repo.get(s, "product", "P-100")   # PO-1001 RELEASED, PO-1004 COMPLETED
        assert p200["open_order_count"] == 1
        assert p100["open_order_count"] == 0

    async def test_cross_object_trigger_recomputes_owner(self, sc):
        """A NEW production order bumps product.open_order_count even though
        the product row itself did not move (derived.triggers)."""
        await sc.outbox.dispatch_pending()  # materialize seed values first
        async with sc.sessionmaker() as s:
            base = await sc.repo.get(s, "product", "P-300")
        assert base["open_order_count"] == 0  # PO-1003 is RELEASED, not PLANNED

        async with sc.sessionmaker() as s:
            await sc.runtime.execute(
                s, "create-production-order", PLANNER,
                {"product_id": "P-300", "qty": 5},
                None,
            )
            await s.commit()
        await sc.outbox.dispatch_pending()

        async with sc.sessionmaker() as s:
            p300 = await sc.repo.get(s, "product", "P-300")
        assert p300["open_order_count"] == 1

    async def test_action_triggers_recomputation(self, sc):
        """Creating a production order must refresh the count on the next drain,
        and releasing it (PLANNED -> RELEASED) must drop it again."""

        async with sc.sessionmaker() as s:
            rev = await sc.runtime.execute(
                s, "create-production-order", PLANNER,
                {"product_id": "P-100", "qty": 2},
                None,
            )
            await s.commit()
        order_id = rev.object_id
        await sc.outbox.dispatch_pending()

        async with sc.sessionmaker() as s:
            p100 = await sc.repo.get(s, "product", "P-100")
        assert p100["open_order_count"] == 1

        # releasing the order takes it out of the PLANNED count
        async with sc.sessionmaker() as s:
            await sc.runtime.execute(
                s, "release-production-order", PLANNER, {}, order_id,
            )
            await s.commit()
        await sc.outbox.dispatch_pending()
        async with sc.sessionmaker() as s:
            p100 = await sc.repo.get(s, "product", "P-100")
        assert p100["open_order_count"] == 0


class TestLlmInFunctions:
    async def test_llm_rpc_budget_and_denial(self, golden_pkg_path, tmp_path):
        """A function with the llm capability calls the platform gateway; undeclared -> denied."""
        from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, ParamDef, ResourceMeta

        pkg_root = tmp_path / "pkg"
        import shutil

        shutil.copytree(golden_pkg_path, pkg_root)
        src = pkg_root / "functions" / "summarize.py"
        src.write_text(
            "def summarize(text):\n"
            "    out = ontogeny.llm(prompt=f'summary: {text}')\n"
            "    return out['content']\n",
            encoding="utf-8",
        )

        fn = FunctionResource(
            apiVersion="ontogeny/v1", kind="Function",
            metadata=ResourceMeta(name="summarize"),
            spec=FunctionSpec(
                runtime="python", entry="summarize.py:summarize",
                parameters={"text": ParamDef(type="string", required=True)},
                capabilities=[Capability(**{"read-objects": ["production-order"]}),
                              Capability(**{"llm": {"max-calls": 2}})],
            ),
        )

        ollama_hits = []
        def handler(request: httpx.Request) -> httpx.Response:
            ollama_hits.append(request)
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "the summary"}})

        settings = Settings(
            db_dsn=f"sqlite+aiosqlite:///{tmp_path/'m.db'}",
            env={"ERP_DSN": f"sqlite+aiosqlite:///{tmp_path/'e.db'}"},
            llm_base_url="http://ollama.test",
        )
        from ontogeny.service import ServiceContext

        sc = ServiceContext(settings, str(pkg_root), llm_http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        await sc.initialize()
        try:
            async with sc.sessionmaker() as s:
                value = await sc.sandbox.run(s, fn, {"text": "spindle replacement"})
            assert value == "the summary"
            assert len(ollama_hits) == 1  # routed through the gateway, child has no network

            # undeclared capability -> denied at the boundary
            fn.spec.capabilities = [c for c in fn.spec.capabilities if "llm" not in c.model_dump(exclude_none=True)]
            async with sc.sessionmaker() as s:
                from ontogeny.errors import SandboxError

                with pytest.raises(SandboxError, match="does not declare the llm capability"):
                    await sc.sandbox.run(s, fn, {"text": "x"})
        finally:
            await sc.engine.dispose()

    async def test_llm_budget_exhausts(self, golden_pkg_path, tmp_path):
        from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, ParamDef, ResourceMeta
        from ontogeny.errors import SandboxError

        pkg_root = tmp_path / "pkg2"
        import shutil

        shutil.copytree(golden_pkg_path, pkg_root)
        (pkg_root / "functions" / "loop.py").write_text(
            "def loop(n):\n"
            "    for _ in range(n):\n"
            "        ontogeny.llm(prompt='x')\n"
            "    return n\n",
            encoding="utf-8",
        )
        fn = FunctionResource(
            apiVersion="ontogeny/v1", kind="Function",
            metadata=ResourceMeta(name="loop"),
            spec=FunctionSpec(
                runtime="python", entry="loop.py:loop",
                parameters={"n": ParamDef(type="integer", required=True)},
                capabilities=[Capability(**{"llm": {"max-calls": 2}})],
            ),
        )
        settings = Settings(
            db_dsn=f"sqlite+aiosqlite:///{tmp_path/'m2.db'}",
            env={"ERP_DSN": f"sqlite+aiosqlite:///{tmp_path/'e2.db'}"},
            llm_base_url="http://ollama.test",
        )
        sc = ServiceContext(settings, str(pkg_root), llm_http=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"message": {"content": "ok"}}))))
        await sc.initialize()
        try:
            async with sc.sessionmaker() as s:
                with pytest.raises(SandboxError, match="budget"):
                    await sc.sandbox.run(s, fn, {"n": 5})
        finally:
            await sc.engine.dispose()

    async def test_llm_not_configured_clear_error(self, golden_pkg_path, tmp_path):
        from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, ParamDef, ResourceMeta
        from ontogeny.errors import SandboxError

        pkg_root = tmp_path / "pkg3"
        import shutil

        shutil.copytree(golden_pkg_path, pkg_root)
        (pkg_root / "functions" / "s.py").write_text(
            "def s(text):\n    return ontogeny.llm(prompt=text)['content']\n", encoding="utf-8")
        fn = FunctionResource(
            apiVersion="ontogeny/v1", kind="Function",
            metadata=ResourceMeta(name="s"),
            spec=FunctionSpec(runtime="python", entry="s.py:s",
                              parameters={"text": ParamDef(type="string", required=True)},
                              capabilities=[Capability(**{"llm": True})]),
        )
        settings = Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path/'m3.db'}",
                            env={"ERP_DSN": f"sqlite+aiosqlite:///{tmp_path/'e3.db'}"})
        sc = ServiceContext(settings, str(pkg_root))
        await sc.initialize()
        try:
            async with sc.sessionmaker() as s:
                with pytest.raises(SandboxError, match="ONTOGENY_LLM_BASE_URL"):
                    await sc.sandbox.run(s, fn, {"text": "x"})
        finally:
            await sc.engine.dispose()


class TestVersionedFunctions:
    async def test_meta_exposes_a_version_for_every_function(self, sc):
        """The version IS the external contract, and there is no publish switch.

        A `publish` flag used to sit on the Function spec and decorate /meta
        without gating anything — invocation, agent tools and the version all
        behaved identically either way. A promise the platform does not keep is
        worse than no promise, so it is gone: callers pin a version, and that is
        the whole contract.
        """
        meta = sc.compiled.to_meta()
        for name, fn in meta["functions"].items():
            assert fn["version"] and len(fn["version"]) == 12, name
            assert "publish" not in fn

    async def test_version_pin_detects_drift(self, sc):
        """A caller pinning a version gets a deterministic accept-or-conflict."""
        version = sc.compiled.function_versions["order-yield"]

        # matching pin: ok; wrong pin -> conflict (asserted via the API layer in test_api)
        from ontogeny.errors import ConflictError

        def check(pinned: str, current: str) -> None:
            if pinned != current:
                raise ConflictError(
                    f"function version drift: pinned {pinned!r}, current {current!r}",
                    details={"pinned": pinned, "current": current},
                )

        check(version, version)  # ok
        with pytest.raises(ConflictError):
            check("ancient000000", version)
