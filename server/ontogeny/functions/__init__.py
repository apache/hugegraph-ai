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
"""ontogeny.functions -- the two ways a function can have a body, behind one door.

A function is either *code* (a Python file the sandbox runs in a child process
with capability-scoped RPC) or *declarative* (a pipeline the platform runs
itself). Callers must not care which: every entry point — the REST API, MCP, the
agent's ``call_<fn>`` tool, the derivation worker, the demo runner — goes through
``FunctionRuntime``, so a new runtime is added here rather than at six call
sites, and the two kinds cannot drift in how they are budgeted or reported.
"""
from __future__ import annotations

from typing import Any

from .declarative import DeclarativeRuntime
from .derivation import DerivationWorker
from .sandbox import FunctionSandbox


class FunctionRuntime:
    """Dispatch ``run``/``map_rows`` on ``spec.runtime``."""

    def __init__(self, sandbox: FunctionSandbox, declarative: DeclarativeRuntime) -> None:
        self.sandbox = sandbox
        self.declarative = declarative

    @staticmethod
    def is_declarative(fn) -> bool:
        return fn.spec.runtime == "declarative"

    async def run(self, session, fn, params: dict[str, Any]) -> Any:
        if self.is_declarative(fn):
            return await self.declarative.run(session, fn, params)
        return await self.sandbox.run(session, fn, params)

    async def run_source(self, session, fn, source: str, params: dict[str, Any]) -> Any:
        """One throwaway run of editor text — code runtime only.

        A declarative function's body IS the DSL, so there is no editor text to
        try and nothing to run here; callers gate on ``is_declarative`` first.
        """
        if self.is_declarative(fn):
            raise NotImplementedError("a declarative function has no code to test-run")
        return await self.sandbox.run_source(session, fn, source, params)

    async def map_rows(self, session, fn, rows: list[dict[str, Any]],
                       params: dict[str, Any] | None = None, *,
                       object_param: str = "obj") -> list[Any]:
        """Batch mode for the derivation worker.

        A declarative function gets the same treatment as a code one: evaluated
        once per row, values in row order. It is slower than the sandbox's
        single-spawn-per-batch map, but derivation batches are small and the
        alternative (a second batch protocol) is more machinery than the feature
        earns.
        """
        if self.is_declarative(fn):
            out: list[Any] = []
            for row in rows:
                out.append(await self.declarative.run(
                    session, fn, {**(params or {}), object_param: row}))
            return out
        return await self.sandbox.map_rows(session, fn, rows, params,
                                           object_param=object_param)

    async def aclose(self) -> None:
        await self.declarative.aclose()


__all__ = ["FunctionSandbox", "DeclarativeRuntime", "FunctionRuntime", "DerivationWorker"]
