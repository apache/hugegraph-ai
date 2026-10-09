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
"""Sandbox child process: loads the user function and proxies capability
requests (``ontogeny.query``, ``ontogeny.llm``) to the parent over stdio JSON lines.

Protocol (one JSON object per line):
  parent->child : {"type":"invoke", "params": {...}}                 single call
                | {"type":"map", "rows": [...], "params": {...},
                   "object_param": "obj"}                            batch (derivation)
  child->parent : {"type":"rpc", "id": n, "method": "query"|"llm", "params": {...}}
  parent->child : {"id": n, "result": ...} | {"id": n, "error": "..."}
  child->parent : {"type":"result", "value": ...}
                | {"type":"values", "values": [...]}                 (map mode)
                | {"type":"error", "error": "..."}
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


class _OO:
    """Capability shim injected as ``ontogeny``. Every method crosses the sandbox
    boundary as an RPC; the parent enforces the declared capabilities."""

    def __init__(self) -> None:
        self._id = 0

    def _rpc(self, method: str, params: dict):
        self._id += 1
        sys.stdout.write(json.dumps({"type": "rpc", "id": self._id, "method": method, "params": params}) + "\n")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            raise RuntimeError("sandbox parent closed the pipe")
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp.get("result")

    def query(self, object_type: str, filter: dict | None = None, **kwargs):
        params = {"object_type": object_type, "filter": filter}
        params.update({k: v for k, v in kwargs.items() if k in ("limit", "sort")})
        return self._rpc("query", params)

    def llm(self, prompt: str | None = None, messages: list | None = None, system: str | None = None):
        """Registered language model, routed through the platform gateway.

        Returns {"content": str, "thinking": str|None}. Requires the function
        to declare the ``llm`` capability; the parent enforces the call budget.
        """
        if not prompt and not messages:
            raise ValueError("llm() needs a prompt or messages")
        return self._rpc("llm", {"prompt": prompt, "messages": messages, "system": system})


def _load(module_path: str, func_name: str):
    spec = importlib.util.spec_from_file_location("ontogeny_user_function", module_path)
    if spec is None or spec.loader is None:
        return None, None, f"cannot load {module_path}"
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 -- surface user import errors
        return None, None, f"import failed: {exc}"
    fn = getattr(mod, func_name, None)
    if fn is None:
        return None, None, f"function {func_name!r} not found in {Path(module_path).name}"
    mod.__dict__.setdefault("ontogeny", _OO())
    return mod, fn, None


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def main() -> None:
    module_path, func_name = sys.argv[1], sys.argv[2]
    _mod, fn, err = _load(module_path, func_name)
    if err is not None:
        _emit({"type": "error", "error": err})
        return

    init = json.loads(sys.stdin.readline() or "{}")
    try:
        mode = init.get("type", "invoke")
        if mode == "invoke":
            _emit({"type": "result", "value": fn(**(init.get("params") or {}))})
        elif mode == "map":
            # derivation batch: the runner loops per row inside this process
            # (one spawn for the whole batch); ontogeny.query stays available per row
            object_param = init.get("object_param") or "obj"
            params = dict(init.get("params") or {})
            values = [fn(**{**params, object_param: row}) for row in (init.get("rows") or [])]
            _emit({"type": "values", "values": values})
        else:
            _emit({"type": "error", "error": f"unknown mode {mode!r}"})
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
