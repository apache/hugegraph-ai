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
"""Extension host: discovery + supervised loading of optional extensions.

The core is a constitution: registry, policy, actions, governance. Everything
that is one *implementation choice* among many -- an LLM adapter, an agent
engine, a graph store -- lives OUTSIDE the core in an ``extensions/``
directory and plugs in through contracts the core defines:

- ``capability:llm``        -> sets ``sc.llm`` (a ``ontogeny.llm.ChatClient``)
- ``capability:graph-store``-> sets ``sc.graph_store_factory`` (``GraphStore`` factory)
- agent engines             -> register factories into ``sc.agent_engines``

Layout of one extension (a directory, self-declared)::

    extensions/
      llm-ollama/
        extension.yaml      # manifest: name/kind/provides/requires/entry
        ontogeny_ext_ollama/      # a plain importable Python package
          __init__.py       #   register(sc, host) entrypoint
          adapter.py

Loading rules (deliberately boring):

- discovery directories: ``ONTOGENY_EXTENSIONS_DIR`` (colon-separated) replaces the
  default ``<repo>/extensions``;
- ``ONTOGENY_EXTENSIONS`` (comma list) selects; unset = all enabled, empty = none;
- a broken extension is recorded as ``error`` and skipped -- it must never
  take down the core boot;
- ``requires`` names capabilities; an unsatisfied require skips the extension
  with a recorded reason (e.g. an engine that hard-needs an LLM provider);
- core code NEVER imports an extension module; extension code may import core.
"""
from __future__ import annotations

import importlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("ontogeny.ext")

#: kinds loaded before others (providers before consumers, so a consumer that
#: eagerly reads a capability at register time usually finds it in place)
_PROVIDER_KINDS = ("llm-provider", "graph-projection")

DEFAULT_KINDS = ("llm-provider", "agent-engine", "graph-projection", "generic")


@dataclass
class ExtensionRecord:
    name: str
    path: str
    kind: str = "generic"
    display: str = ""
    description: str = ""
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    entry: str = ""
    status: str = "discovered"   # discovered|disabled|loaded|error|skipped
    error: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_meta(self) -> dict[str, Any]:
        return {
            "name": self.name, "kind": self.kind, "display": self.display,
            "description": self.description, "provides": self.provides,
            "requires": self.requires, "entry": self.entry,
            "status": self.status, "error": self.error, "path": self.path,
        }


def default_extensions_dir() -> Path:
    """``<repo>/extensions`` next to the ``server/`` tree (works for editable
    installs, tests and the console script run from a checkout)."""
    return Path(__file__).resolve().parents[2] / "extensions"


def discovery_dirs(settings) -> list[Path]:
    override = getattr(settings, "extensions_dir", None)
    if override:
        return [Path(p).expanduser() for p in override.split(":") if p.strip()]
    return [default_extensions_dir()]


class ExtensionHost:
    def __init__(self, sc) -> None:
        self.sc = sc
        self.records: list[ExtensionRecord] = []
        self.capabilities: dict[str, dict[str, Any]] = {}
        self._loading: ExtensionRecord | None = None
        # entry.module -> extension name: sys.path stacking makes a duplicate
        # module name a silent time bomb (whichever extension's directory was
        # inserted first wins), so duplicates are refused loudly instead
        self._modules: dict[str, str] = {}

    # ------------------------------------------------------------------ api

    def discover(self) -> None:
        """Scan the extension directories and parse every manifest."""
        import os

        allow = os.environ.get("ONTOGENY_EXTENSIONS")
        selected = None if allow is None else {s.strip() for s in allow.split(",") if s.strip()}
        for root in discovery_dirs(self.sc.settings):
            if not root.is_dir():
                continue
            for manifest_path in sorted(root.glob("*/extension.yaml")):
                rec = self._parse(manifest_path, root)
                if rec is None:
                    continue
                if not rec.manifest.get("enabled", True):
                    rec.status = "disabled"
                elif selected is not None and rec.name not in selected:
                    rec.status = "disabled"
                self.records.append(rec)
        for rec in self.records:
            log.debug("extension %s: %s", rec.name, rec.status)

    def load(self) -> None:
        """Import + register every enabled extension (providers first).

        Each extension is isolated: an import or register failure is recorded
        on its row and loading continues -- one bad extension cannot take down
        the platform boot.
        """
        ordered = sorted(
            self.records,
            key=lambda r: (0 if r.kind in _PROVIDER_KINDS else 1, r.name),
        )
        for rec in ordered:
            if rec.status != "discovered":
                continue
            missing = [r for r in rec.requires if r not in self.capabilities]
            if missing:
                rec.status = "skipped"
                rec.error = f"missing required capabilities: {', '.join(missing)}"
                log.warning("extension %s skipped: %s", rec.name, rec.error)
                continue
            try:
                self._load_one(rec)
                rec.status = "loaded"
                # NOTE: capabilities are recorded only when the extension calls
                # host.provide() -- a provider may legitimately register without
                # providing (e.g. llm-ollama with no ONTOGENY_LLM_BASE_URL), and the
                # requires check must see what is actually there, not promises.
            except Exception as exc:  # noqa: BLE001 -- isolation is the point
                rec.status = "error"
                rec.error = f"{type(exc).__name__}: {exc}"
                log.exception("extension %s failed to load", rec.name)

    def reload_providers(self) -> None:
        """Re-register loaded providers after runtime settings changed.

        Only provider kinds are re-run; consumers (agent engines) capture the
        provider through sc, so they do not need to be rebuilt here.
        """
        for name in list(self.capabilities):
            self.capabilities.pop(name, None)
        for rec in sorted(self.records, key=lambda r: (0 if r.kind in _PROVIDER_KINDS else 1, r.name)):
            if rec.status != "loaded" or rec.kind not in _PROVIDER_KINDS:
                continue
            try:
                self._load_one(rec)
            except Exception as exc:  # noqa: BLE001 -- keep the old provider state
                rec.status = "error"
                rec.error = f"{type(exc).__name__}: {exc}"
                log.exception("extension %s failed to reload", rec.name)

    def provide(self, name: str, meta: dict[str, Any] | None = None) -> None:
        """Called by an extension at register time to publish a capability.
        The calling extension's name is stamped automatically."""
        ext = self._loading.name if self._loading else "?"
        self.capabilities[name] = {"extension": ext, **(meta or {})}

    def records_meta(self) -> dict[str, Any]:
        return {
            "extensions": [r.to_meta() for r in sorted(self.records, key=lambda r: r.name)],
            "capabilities": self.capabilities,
            "dirs": [str(p) for p in discovery_dirs(self.sc.settings)],
        }

    # ------------------------------------------------------------- internals

    def _parse(self, manifest_path: Path, root: Path) -> ExtensionRecord | None:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        name = str(raw.get("name") or manifest_path.parent.name)
        entry = raw.get("entry") or {}
        rec = ExtensionRecord(
            name=name,
            path=str(manifest_path.parent),
            kind=str(raw.get("kind") or "generic"),
            display=str(raw.get("display") or name),
            description=str(raw.get("description") or ""),
            provides=[str(x) for x in raw.get("provides") or []],
            requires=[str(x) for x in raw.get("requires") or []],
            entry=f"{entry.get('module', '')}:{entry.get('function', 'register')}",
            manifest=raw,
        )
        if not entry.get("module"):
            rec.status = "skipped"
            rec.error = "manifest has no entry.module"
        return rec

    def _load_one(self, rec: ExtensionRecord) -> None:
        module_name = rec.manifest["entry"]["module"]
        # a module name already claimed by another extension would silently
        # import the FIRST extension's package here (sys.path order), i.e. run
        # the wrong code under the right manifest -- refuse instead
        owner = self._modules.get(module_name)
        if owner is not None and owner != rec.name:
            raise ImportError(
                f"entry.module {module_name!r} is already provided by extension "
                f"{owner!r}; rename one of the packages")
        # the extension's own directory goes on sys.path: its Python package
        # (entry.module) lives directly inside it
        if rec.path not in sys.path:
            sys.path.insert(0, rec.path)
        importlib.invalidate_caches()
        module = importlib.import_module(module_name)
        self._modules[module_name] = rec.name
        function_name = rec.manifest["entry"].get("function") or "register"
        register = getattr(module, function_name)
        self._loading = rec
        try:
            register(self.sc, self)
        finally:
            self._loading = None
