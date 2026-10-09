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
"""Declarative functions: the DSL body, its guarantees, and its limits.

The feature exists so a prompt can be edited, diffed and versioned as model data
instead of Python. What these tests defend is the part that makes that safe:

* a step may never do more than the function declares (validated at publish AND
  enforced at call time);
* reads go through the same engine path as everything else, so marking masks are
  not bypassed by a second, weaker read route;
* ``http`` needs an allowlist, on both sides;
* the content version moves when the body moves — otherwise pinning a
  declarative function would be theatre.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ontogeny.core.models import (
    Capability, FunctionResource, FunctionSpec, FunctionStep, ParamDef, ResourceMeta,
)
from ontogeny.core.validator import _validate_function_body
from ontogeny.errors import SandboxError
from ontogeny.functions import FunctionRuntime
from ontogeny.functions.declarative import DeclarativeRuntime, _render_text, _Template


def _fn(**kw) -> FunctionResource:
    spec = FunctionSpec(**kw)
    return FunctionResource(apiVersion="ontogeny/v1", kind="Function",
                            metadata=ResourceMeta(name="probe"), spec=spec)


def _codes(fn, rep=None) -> list[str]:
    return [c for c, _ in _validate_function_body(fn)]


class TestValidator:
    def test_a_read_step_must_be_declared(self):
        fn = _fn(runtime="declarative", steps=[FunctionStep(id="a", kind="read", object="work-center")],
                 capabilities=[Capability(**{"read-objects": ["production-order"]})])
        assert "FN-STEP-CAP" in _codes(fn)

    def test_an_llm_step_needs_the_llm_capability(self):
        fn = _fn(runtime="declarative", steps=[FunctionStep(id="a", kind="llm", prompt="hi")])
        assert "FN-STEP-CAP" in _codes(fn)

    def test_an_http_step_needs_the_capability_and_a_host_on_the_list(self):
        undeclared = _fn(runtime="declarative",
                         steps=[FunctionStep(id="a", kind="http", url="https://x.test/y")])
        assert "FN-STEP-CAP" in _codes(undeclared)

        off_list = _fn(runtime="declarative",
                       steps=[FunctionStep(id="a", kind="http", url="https://evil.test/y")],
                       capabilities=[Capability(**{"http": {"allow": ["good.test"]}})])
        assert "FN-STEP-CAP" in _codes(off_list)

        ok = _fn(runtime="declarative",
                 steps=[FunctionStep(id="a", kind="http", url="https://good.test/y")],
                 capabilities=[Capability(**{"http": {"allow": ["good.test"]}})])
        assert _codes(ok) == []

    def test_a_reference_must_exist_before_it_is_used(self):
        forward = _fn(runtime="declarative",
                      steps=[FunctionStep(id="a", kind="llm", prompt="see ${b}"),
                             FunctionStep(id="b", kind="llm", prompt="x")],
                      capabilities=[Capability(**{"llm": True})])
        assert "FN-REF" in _codes(forward)

        later = _fn(runtime="declarative",
                    steps=[FunctionStep(id="a", kind="llm", prompt="x"),
                           FunctionStep(id="b", kind="llm", prompt="see ${a}")],
                    capabilities=[Capability(**{"llm": True})])
        assert _codes(later) == []

    def test_parameters_are_valid_references(self):
        fn = _fn(runtime="declarative",
                 parameters={"who": ParamDef(type="string")},
                 steps=[FunctionStep(id="a", kind="llm", prompt="hi ${who}")],
                 capabilities=[Capability(**{"llm": True})])
        assert _codes(fn) == []

    def test_returns_step_must_name_a_step(self):
        fn = _fn(runtime="declarative", returns_step="nope",
                 steps=[FunctionStep(id="a", kind="llm", prompt="x")],
                 capabilities=[Capability(**{"llm": True})])
        assert "FN-RETURNS" in _codes(fn)

    def test_duplicate_step_ids_are_refused(self):
        fn = _fn(runtime="declarative",
                 steps=[FunctionStep(id="a", kind="llm", prompt="x"),
                        FunctionStep(id="a", kind="llm", prompt="y")],
                 capabilities=[Capability(**{"llm": True})])
        assert "FN-STEP-ID" in _codes(fn)

    def test_a_code_function_keeps_its_entry_contract(self):
        assert _codes(_fn(runtime="python", entry="")) == ["FN-ENTRY"]
        assert _codes(_fn(runtime="python", entry="a.py:main")) == []
        assert "FN-BODY" in _codes(_fn(runtime="python", entry="a.py:main",
                                       steps=[FunctionStep(id="a", kind="llm", prompt="x")]))

    def test_a_declarative_function_has_no_file(self):
        assert "FN-ENTRY" in _codes(_fn(runtime="declarative", entry="a.py:main",
                                        steps=[FunctionStep(id="a", kind="llm", prompt="x")],
                                        capabilities=[Capability(**{"llm": True})]))
        assert "FN-STEPS" in _codes(_fn(runtime="declarative"))


class TestTemplate:
    def test_a_bare_reference_keeps_its_type(self):
        t = _Template({"n": 3}, {"rows": [{"a": 1}, {"a": 2}]})
        assert t.render("${n}") == 3
        assert t.render("${rows}") == [{"a": 1}, {"a": 2}]

    def test_a_surrounded_reference_becomes_text(self):
        t = _Template({"who": "ops"}, {})
        assert t.render("hello ${who}!") == "hello ops!"

    def test_field_lookup_projects_over_rows(self):
        t = _Template({}, {"rows": [{"a": 1}, {"a": 2}]})
        assert t.render("${rows.a}") == [1, 2]

    def test_rows_read_as_lines_not_json(self):
        # a model reasoning about records wants lines; a JSON blob makes it
        # parse before it can think
        text = _render_text([{"work_center_id": "WC-1", "status": "ACTIVE"}])
        assert text == "- work_center_id=WC-1, status=ACTIVE"
        assert _render_text([]) == "(none)"

    def test_unknown_reference_is_an_error_not_a_silent_blank(self):
        with pytest.raises(SandboxError, match="unknown reference"):
            _Template({}, {}).render_text("${nope}")

    def test_nested_structures_render_recursively(self):
        t = _Template({"q": "x"}, {})
        assert t.render({"filter": {"a": "${q}"}, "list": ["${q}"]}) == {
            "filter": {"a": "x"}, "list": ["x"],
        }


class _FakeLLM:
    """Records the prompts it was given; the runtime's contract is 'hand the
    gateway the rendered prompt', so that is what we assert on."""

    def __init__(self, reply="ok"):
        self.reply, self.seen = reply, []
        self.model = "fake"

    async def chat(self, messages):
        self.seen.append(messages)
        return {"content": self.reply}


class TestRuntime:
    @pytest.fixture()
    async def runtime(self, client):
        _, sc = client
        # the object tables start empty: the fixture seeds a SOURCE database, so
        # a read step has nothing to read until a sync has run
        for object_type in ("work-center", "production-order", "material"):
            await sc.sync(object_type)
        return DeclarativeRuntime(llm=_FakeLLM("ADVICE"), repo=sc.repo,
                                  compiled=sc.compiled)

    async def _run(self, client, runtime, fn, params):
        _, sc = client
        async with sc.sessionmaker() as session:
            return await runtime.run(session, fn, params)

    async def test_a_read_step_returns_engine_assembled_rows(self, client, runtime):
        fn = _fn(runtime="declarative", returns_step="rows",
                 steps=[FunctionStep(id="rows", kind="read", object="work-center", limit=3)],
                 capabilities=[Capability(**{"read-objects": ["work-center"]})])
        rows = await self._run(client, runtime, fn, {})
        assert isinstance(rows, list) and rows
        # the same assembly every other read uses (derived props computed,
        # masks applied) rather than a raw table dump
        assert "site" in rows[0]

    async def test_reads_come_back_whole_including_marked_properties(self, client, runtime):
        """A function body is trusted server-side logic, not a reader.

        Pinned deliberately, because the platform's own authorization pattern
        depends on it: ``material.unit_cost`` is marked ``internal``, and
        server-side logic may need that row-level attribute from the
        authoritative record rather than from the caller. Masking is a
        reader-surface control (REST/MCP/graph preview); ``read-objects`` is the
        control at this boundary. Applying masks here would break that pattern
        *silently* — as a policy denial several steps later, which is how it was
        noticed.
        """
        fn = _fn(runtime="declarative", returns_step="rows",
                 steps=[FunctionStep(id="rows", kind="read", object="material", limit=3)],
                 capabilities=[Capability(**{"read-objects": ["material"]})])
        rows = await self._run(client, runtime, fn, {})
        # the marked property arrives REAL: masking must not leak into functions
        assert rows and all(isinstance(r.get("unit_cost"), float) and r["unit_cost"] > 0
                            for r in rows)

    async def test_the_prompt_sees_rendered_facts(self, client, runtime):
        fn = _fn(runtime="declarative", returns_step="advice",
                 parameters={"work_center_id": ParamDef(type="string")},
                 steps=[FunctionStep(id="rows", kind="read", object="work-center",
                                     filter={"work_center_id": "${work_center_id}"}, limit=1),
                        FunctionStep(id="advice", kind="llm",
                                     prompt="facts:\n${rows}\nfocus: ${work_center_id}")],
                 capabilities=[Capability(**{"read-objects": ["work-center"]}),
                               Capability(**{"llm": {"max-calls": 1}})])
        out = await self._run(client, runtime, fn, {"work_center_id": "WC-01"})
        assert out == "ADVICE"
        prompt = runtime.llm.seen[-1][-1]["content"]
        assert "WC-01" in prompt               # the parameter rendered
        assert "- work_center_id=" in prompt   # rows rendered as lines, not JSON

    async def test_llm_budget_is_enforced(self, client, runtime):
        fn = _fn(runtime="declarative",
                 steps=[FunctionStep(id="a", kind="llm", prompt="1"),
                        FunctionStep(id="b", kind="llm", prompt="2")],
                 capabilities=[Capability(**{"llm": {"max-calls": 1}})])
        with pytest.raises(SandboxError, match="budget exhausted"):
            await self._run(client, runtime, fn, {})

    async def test_without_returns_step_every_step_comes_back(self, client, runtime):
        fn = _fn(runtime="declarative",
                 steps=[FunctionStep(id="a", kind="read", object="work-center", limit=1),
                        FunctionStep(id="b", kind="llm", prompt="x")],
                 capabilities=[Capability(**{"read-objects": ["work-center"]}),
                               Capability(**{"llm": True})])
        out = await self._run(client, runtime, fn, {})
        assert set(out) == {"a", "b"} and out["b"] == "ADVICE"


class TestHttpStep:
    def _router(self, calls, status=200, payload=None):
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(status, json=payload if payload is not None else {"ok": True})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return http

    async def _run(self, client, http, steps, caps, params=None):
        _, sc = client
        rt = DeclarativeRuntime(repo=sc.repo, compiled=sc.compiled, http=http)
        fn = _fn(runtime="declarative", steps=steps, capabilities=caps)
        async with sc.sessionmaker() as session:
            return await rt.run(session, fn, params or {})

    async def test_an_allowed_host_is_called_and_parsed(self, client):
        calls: list[httpx.Request] = []
        http = self._router(calls, payload={"delivered": True})
        out = await self._run(
            client, http,
            [FunctionStep(id="post", kind="http", method="POST", url="https://hooks.test/x",
                          body={"text": "hi"})],
            [Capability(**{"http": {"allow": ["hooks.test"]}})],
        )
        assert out["post"]["json"] == {"delivered": True} and calls[0].method == "POST"

    async def test_an_unlisted_host_is_refused_without_calling_it(self, client):
        calls: list[httpx.Request] = []
        http = self._router(calls)
        with pytest.raises(SandboxError, match="not in the http allowlist"):
            await self._run(
                client, http,
                [FunctionStep(id="post", kind="http", url="https://evil.test/x")],
                [Capability(**{"http": {"allow": ["hooks.test"]}})],
            )
        assert calls == []

    async def test_a_deployment_allowlist_can_only_narrow(self, client):
        calls: list[httpx.Request] = []
        http = self._router(calls)
        _, sc = client
        rt = DeclarativeRuntime(repo=sc.repo, compiled=sc.compiled, http=http,
                                http_allowlist=["corp.test"])
        fn = _fn(runtime="declarative",
                 steps=[FunctionStep(id="post", kind="http", url="https://hooks.test/x")],
                 capabilities=[Capability(**{"http": {"allow": ["hooks.test"]}})])
        async with sc.sessionmaker() as session:
            with pytest.raises(SandboxError, match="deployment allowlist"):
                await rt.run(session, fn, {})

    async def test_no_allowlist_means_no_calls(self, client):
        calls: list[httpx.Request] = []
        http = self._router(calls)
        with pytest.raises(SandboxError, match="no allowed hosts"):
            await self._run(client, http,
                            [FunctionStep(id="post", kind="http", url="https://x.test/y")],
                            [Capability(**{"http": {}})])
        assert calls == []

    async def test_credentials_may_not_ride_in_the_url(self, client):
        calls: list[httpx.Request] = []
        http = self._router(calls)
        with pytest.raises(SandboxError, match="must not embed credentials"):
            await self._run(client, http,
                            [FunctionStep(id="post", kind="http", url="https://u:p@hooks.test/x")],
                            [Capability(**{"http": {"allow": ["hooks.test"]}})])
        assert calls == []

    async def test_a_non_http_scheme_is_refused(self, client):
        calls: list[httpx.Request] = []
        http = self._router(calls)
        with pytest.raises(SandboxError, match="must use http"):
            await self._run(client, http,
                            [FunctionStep(id="post", kind="http", url="file:///etc/passwd")],
                            [Capability(**{"http": {"allow": ["hooks.test"]}})])


class TestDispatcher:
    async def test_it_routes_by_runtime(self, client):
        _, sc = client
        assert isinstance(sc.functions, FunctionRuntime)
        assert FunctionRuntime.is_declarative(_fn(runtime="declarative")) is True
        assert FunctionRuntime.is_declarative(_fn(runtime="python", entry="a.py:main")) is False

    async def test_a_declarative_function_can_be_a_derived_property_source(self, client):
        """map_rows is how derived properties work; a declarative function must be
        usable there too, not only from the API."""
        _, sc = client
        fn = _fn(runtime="declarative", returns_step="rows",
                 steps=[FunctionStep(id="rows", kind="read", object="work-center", limit=1)],
                 capabilities=[Capability(**{"read-objects": ["work-center"]})])
        async with sc.sessionmaker() as session:
            values = await sc.functions.map_rows(session, fn, [{"obj": 1}, {"obj": 2}])
        assert len(values) == 2 and all(isinstance(v, list) for v in values)


class TestContentVersion:
    def test_editing_the_body_moves_the_version(self, golden_pkg_path, tmp_path):
        """Pinning is only real if the version follows the body: a declarative
        function that kept a constant version would let a caller pin logic that
        silently changed under it."""
        import shutil

        from ontogeny.core import load_package
        from ontogeny.registry.compiled import compile_package

        root = tmp_path / "pkg"
        shutil.copytree(golden_pkg_path, root)
        (root / "functions" / "prompt-fn.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Function\nmetadata: {name: prompt-fn}\n"
            "spec:\n  runtime: declarative\n  steps:\n"
            "  - {id: a, kind: llm, prompt: 'first'}\n"
            "  capabilities:\n  - llm: {max-calls: 1}\n",
            encoding="utf-8",
        )
        v1 = compile_package(load_package(str(root))).function_versions["prompt-fn"]
        assert v1  # not the empty-string hash

        (root / "functions" / "prompt-fn.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Function\nmetadata: {name: prompt-fn}\n"
            "spec:\n  runtime: declarative\n  steps:\n"
            "  - {id: a, kind: llm, prompt: 'second'}\n"
            "  capabilities:\n  - llm: {max-calls: 1}\n",
            encoding="utf-8",
        )
        v2 = compile_package(load_package(str(root))).function_versions["prompt-fn"]
        assert v1 != v2


class TestFunctionBoundaryRule:
    """The boundary rule for BOTH runtimes, in one place.

    A function declares *which object types* it may read (``read-objects``); it
    does not get property-level masks, because it is not a reader. The domain
    package's own functions (capacity-check, material-availability, order-yield)
    are the proof: they read whole rows by capability. This test exists so the
    rule is a decision someone makes rather than something that drifts.
    """

    async def test_a_code_function_reads_the_same_rows_a_declarative_one_does(
            self, client, tmp_path):
        import textwrap

        from ontogeny.core.models import FunctionResource, FunctionSpec, ResourceMeta

        _, sc = client
        await sc.sync("work-center")
        src = tmp_path / "peek.py"
        src.write_text(textwrap.dedent('''
            def peek() -> dict:
                rows = ontogeny.query("work-center", limit=1)
                return rows[0] if rows else {}
        '''), encoding="utf-8")
        fn = FunctionResource(
            apiVersion="ontogeny/v1", kind="Function", metadata=ResourceMeta(name="peek"),
            spec=FunctionSpec(runtime="python", entry=f"{src}:peek", parameters={},
                              capabilities=[Capability(**{"read-objects": ["work-center"]})]),
        )
        async with sc.sessionmaker() as session:
            row = await sc.functions.run(session, fn, {})
        # identical to the declarative read above: capability-scoped, whole rows
        assert row.get("site") == "plant-north"


class TestLlmBudgetParsing:
    """``max-calls: 0`` means zero.

    The declaration is authoritative, and a falsy-zero bug failed in the one
    direction a budget must never fail in: an explicit 0 became 10 granted calls.
    """

    def test_zero_is_zero_not_the_default(self):
        from ontogeny.functions.declarative import _llm_budget as _d
        from ontogeny.functions.sandbox import _llm_budget as _s

        for parse in (_s, _d):
            assert parse(None) == 10          # undeclared budget: the default
            assert parse({}) == 10            # `llm: true`
            assert parse({"max-calls": 0}) == 0
            assert parse({"max-calls": 3}) == 3
            assert parse({"max-calls": 1}) == 1


class TestFunctionSourceEditing:
    """The console's code editor: administrator-only, syntax-checked before it
    lands, audited, and bounded by the same sandbox as any other function."""

    async def _python_fn(self, sc, tmp_path, name="editable"):
        import textwrap


        root = Path(sc.package_root) / "functions"
        root.mkdir(parents=True, exist_ok=True)
        src = root / f"{name}.py"
        src.write_text(textwrap.dedent(f"""
            def {name}() -> dict:
                return {{"version": 1}}
        """).lstrip(), encoding="utf-8")
        (root / f"{name}.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Function\n"
            f"metadata: {{name: {name}}}\n"
            f"spec:\n  runtime: python\n  entry: {name}.py:{name}\n"
            "  capabilities:\n  - read-objects: [work-center]\n",
            encoding="utf-8",
        )
        await sc.publish(str(sc.package_root), created_by="test")
        return sc.compiled.functions[name], src

    async def test_a_syntax_error_never_reaches_the_file(self, client, tmp_path):
        from ontogeny.errors import DSLValidationError

        _, sc = client
        _fn, src = await self._python_fn(sc, tmp_path)
        before = src.read_text(encoding="utf-8")
        with pytest.raises(DSLValidationError, match="syntax error"):
            await sc.save_function_source("editable", "def broken(:\n",
                                          principal={"id": "admin"})
        # nothing written, nothing published, package still importable
        assert src.read_text(encoding="utf-8") == before

    async def test_saving_publishes_and_records_who_changed_it(self, client, tmp_path):
        import textwrap

        _, sc = client
        _fn, src = await self._python_fn(sc, tmp_path)
        old_version = sc.compiled.function_versions["editable"]

        out = await sc.save_function_source("editable", textwrap.dedent("""
            def editable() -> dict:
                return {"version": 2}
        """).lstrip(), principal={"id": "u-admin"})

        assert out["changed"] is True and out["version"] != old_version
        assert "version\": 2" in src.read_text(encoding="utf-8")
        revisions = await sc.function_source_revisions("editable")
        assert revisions and revisions[0]["principal"] == "u-admin"
        assert revisions[0]["version"] == out["version"]

    async def test_a_no_op_save_produces_no_revision(self, client, tmp_path):
        _, sc = client
        _fn, src = await self._python_fn(sc, tmp_path)
        out = await sc.save_function_source("editable", src.read_text(encoding="utf-8"),
                                            principal={"id": "u-admin"})
        assert out["changed"] is False
        assert await sc.function_source_revisions("editable") == []

    async def test_a_declarative_body_has_no_file_to_edit(self, client):
        """The endpoint refuses to write a file for a body that has none: the
        steps are the logic, and they are edited as DSL, not as Python."""
        from ontogeny.errors import DSLValidationError

        _, sc = client
        root = Path(sc.package_root) / "functions"
        (root / "decl-fn.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Function\nmetadata: {name: decl-fn}\n"
            "spec:\n  runtime: declarative\n  steps:\n"
            "  - {id: a, kind: llm, prompt: hi}\n"
            "  capabilities:\n  - llm: {max-calls: 1}\n",
            encoding="utf-8",
        )
        await sc.publish(str(sc.package_root), created_by="test")
        with pytest.raises(DSLValidationError, match="its body IS the DSL"):
            await sc.save_function_source("decl-fn", "...", principal={"id": "admin"})

    async def test_saving_never_runs_the_code(self, client, tmp_path):
        """A save's side effects are exactly the file, the version and the
        revision row — the code itself is never executed on save. Trying it
        first is the separate test endpoint."""
        _, sc = client
        _fn, _src = await self._python_fn(sc, tmp_path)
        out = await sc.save_function_source("editable", "def editable():\n    return {'a': 1}\n",
                                            principal={"id": "admin"})
        assert "smoke" not in out and "value" not in out

    async def test_a_broken_body_restores_the_previous_file(self, client, tmp_path):
        """A publish that fails (here: the capability list no longer covers the
        code's reads is not checkable statically, so we force a validation
        failure) must leave the working copy publishable."""
        from ontogeny.errors import DSLValidationError

        _, sc = client
        _fn, src = await self._python_fn(sc, tmp_path)
        good = src.read_text(encoding="utf-8")
        # a file that parses but points a Function at an entry it cannot resolve
        # is still publishable, so make the PACKAGE invalid instead
        (Path(sc.package_root) / "functions" / "broken.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Function\nmetadata: {name: broken}\n"
            "spec:\n  runtime: python\n  entry: ''\n",
            encoding="utf-8",
        )
        with pytest.raises(DSLValidationError):
            await sc.save_function_source("editable", good + "\n# touched\n",
                                          principal={"id": "admin"})
        # the edit was rolled back, so the package is still publishable
        assert src.read_text(encoding="utf-8") == good
        (Path(sc.package_root) / "functions" / "broken.yaml").unlink()


class TestFunctionSourceTesting:
    """The console's Test run: one throwaway execution of the editor buffer.

    The contract is the mirror of the save endpoint's: a syntax error is a
    returned refusal to run (not a refused save), a real run really runs, and
    afterwards NOTHING has changed — no file, no version, no revision row.
    """

    async def _python_fn(self, sc, tmp_path, name="editable"):
        import textwrap


        root = Path(sc.package_root) / "functions"
        root.mkdir(parents=True, exist_ok=True)
        src = root / f"{name}.py"
        src.write_text(textwrap.dedent(f"""
            def {name}() -> dict:
                return {{"version": 1}}
        """).lstrip(), encoding="utf-8")
        (root / f"{name}.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Function\n"
            f"metadata: {{name: {name}}}\n"
            f"spec:\n  runtime: python\n  entry: {name}.py:{name}\n"
            "  capabilities:\n  - read-objects: [work-center]\n",
            encoding="utf-8",
        )
        await sc.publish(str(sc.package_root), created_by="test")
        return sc.compiled.functions[name], src

    async def test_a_run_persists_nothing(self, client, tmp_path):
        _, sc = client
        _fn, src = await self._python_fn(sc, tmp_path)
        before = src.read_text(encoding="utf-8")

        out = await sc.test_function_source("editable", "def editable():\n    return {'ok': 42}\n")

        assert out["ok"] is True and out["value"] == {"ok": 42}
        # the file on disk is untouched and no revision row was written
        assert src.read_text(encoding="utf-8") == before
        assert await sc.function_source_revisions("editable") == []

    async def test_a_syntax_error_is_refused_before_any_run(self, client, tmp_path):
        from ontogeny.errors import DSLValidationError

        _, sc = client
        _fn, src = await self._python_fn(sc, tmp_path)
        with pytest.raises(DSLValidationError, match="syntax error"):
            await sc.test_function_source("editable", "def broken(:\n")
        assert src.is_file()  # still just the original file, still publishable

    async def test_a_failing_run_reports_the_error_not_an_exception(self, client, tmp_path):
        _, sc = client
        _fn, _src = await self._python_fn(sc, tmp_path)
        out = await sc.test_function_source(
            "editable", "def editable():\n    raise ValueError('boom')\n")
        assert out["ok"] is False
        assert "boom" in out["message"]

    async def test_a_malformed_entry_is_a_readable_400_not_a_500(self, client, tmp_path):
        """Regression: an entry without \'file.py:function\' used to explode as a
        ValueError inside the sandbox spawn (HTTP 500); it must surface as the
        same DSLValidationError the save path has always produced."""
        from ontogeny.core.models import FunctionResource, FunctionSpec, ResourceMeta
        from ontogeny.errors import DSLValidationError

        c, sc = client
        sc.compiled.functions["no-entry"] = FunctionResource(
            apiVersion="ontogeny/v1", kind="Function",
            metadata=ResourceMeta(name="no-entry"),
            spec=FunctionSpec(runtime="python", entry="just_a_filename"),
        )
        with pytest.raises(DSLValidationError, match="entry must be"):
            await sc.test_function_source("no-entry", "def f():\n    return 1\n")
        # the save path carries the same guard (it used to raise SandboxError -> 500)
        with pytest.raises(DSLValidationError, match="entry must be"):
            await sc.save_function_source("no-entry", "def f():\n    return 1\n",
                                          principal={"id": "admin"})

        # and through the HTTP route (admin principal) it is a 400, not a 500
        admin = {"id": "admin", "Role": ["admin"], "is_admin": True}
        r = await c.post("/api/v1/functions/no-entry/test",
                         json={"source": "def f():\n    return 1\n"},
                         headers={"X-Ontogeny-Principal": json.dumps(admin)})
        assert r.status_code == 400, r.text
        assert "entry must be" in r.json()["message"]

    async def test_a_declarative_body_has_nothing_to_test(self, client):
        from ontogeny.errors import DSLValidationError

        _, sc = client
        root = Path(sc.package_root) / "functions"
        (root / "decl-t.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Function\nmetadata: {name: decl-t}\n"
            "spec:\n  runtime: declarative\n  steps:\n"
            "  - {id: a, kind: llm, prompt: hi}\n"
            "  capabilities:\n  - llm: {max-calls: 1}\n",
            encoding="utf-8",
        )
        await sc.publish(str(sc.package_root), created_by="test")
        with pytest.raises(DSLValidationError, match="its body IS the DSL"):
            await sc.test_function_source("decl-t", "...")


class TestSmokeParams:
    """A smoke run must have inputs, or it tests nothing.

    Invoking with `{}` made every function that declares required parameters —
    the ones actually worth smoke-testing — fail with "missing 1 required
    positional argument", which says nothing about the code.
    """

    async def test_a_primary_key_parameter_gets_a_real_id(self, client, tmp_path):
        """`work_center_id` is answered with a row that exists, so the function's
        own logic runs instead of bailing out on "not found"."""
        _, sc = client
        await sc.sync("work-center")
        _fn, _src = await TestFunctionSourceEditing()._python_fn(sc, tmp_path, name="pk-probe")

        # a function whose only parameter names the work centre primary key
        (Path(sc.package_root) / "functions" / "pk-probe.yaml").write_text(
            "apiVersion: ontogeny/v1\nkind: Function\nmetadata: {name: pk-probe}\n"
            "spec:\n  runtime: python\n  entry: pk_probe.py:pk_probe\n"
            "  parameters:\n    work_center_id: {type: string, required: true}\n"
            "  capabilities:\n  - read-objects: [work-center]\n",
            encoding="utf-8",
        )
        (Path(sc.package_root) / "functions" / "pk_probe.py").write_text(
            "def pk_probe(work_center_id: str = '') -> dict:\n"
            "    rows = ontogeny.query('work-center', filter={'work_center_id': work_center_id}, limit=1)\n"
            "    return {'found': len(rows), 'id': work_center_id}\n",
            encoding="utf-8",
        )
        await sc.publish(str(sc.package_root), created_by="test")

        code = ("def pk_probe(work_center_id: str = '') -> dict:\n"
                "    rows = ontogeny.query('work-center', filter={'work_center_id': work_center_id}, limit=1)\n"
                "    return {'found': len(rows), 'id': work_center_id}\n")
        out = await sc.test_function_source("pk-probe", code)
        assert out["ok"] is True, out
        assert out["params"]["work_center_id"] == "WC-01"
        assert "real id" in out["param_sources"]["work_center_id"]
        assert out["value"]["found"] == 1, "the function read a row that exists"

    async def test_defaults_and_type_samples_fill_the_rest(self, client, tmp_path):
        from ontogeny.core.models import Capability, FunctionResource, FunctionSpec, ParamDef, ResourceMeta

        _, sc = client
        fn = FunctionResource(
            apiVersion="ontogeny/v1", kind="Function", metadata=ResourceMeta(name="probe"),
            spec=FunctionSpec(runtime="python", entry="probe.py:run", capabilities=[
                Capability(**{"read-objects": ["work-center"]})],
                parameters={
                    "window_days": ParamDef(type="integer", default=30),
                    "kind": ParamDef(type="enum[LOW, HIGH]", required=True),
                    "flag": ParamDef(type="boolean", required=True),
                    "note": ParamDef(type="string", required=True),
                }),
        )
        async with sc.sessionmaker() as session:
            params, sources = await sc._smoke_params(session, fn)
        assert params["window_days"] == 30 and sources["window_days"] == "declared default"
        assert params["kind"] == "LOW" and sources["kind"] == "first enum value"
        assert params["flag"] is True
        assert params["note"] == "sample"
