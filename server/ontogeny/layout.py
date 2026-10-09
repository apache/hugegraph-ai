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
"""Canvas layout sidecar (layout.yaml): a pure front-end concern, pure file I/O.

Lived on ServiceContext only because that was the object the HTTP shell could
reach; the context delegates here so domain logic and console cosmetics stop
sharing one god object."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class LayoutStore:
    def __init__(self, package_root: str | None) -> None:
        self.package_root = package_root

    def path(self) -> Path | None:
        root = self.package_root
        if not root:
            return None
        return Path(root) / "layout.yaml"

    def read(self) -> dict[str, Any]:
        """The active package's saved canvas layout ({node_id: {x, y}}), or {}
        when there is none (the canvas falls back to its automatic layout)."""
        p = self.path()
        if p is None or not p.is_file():
            return {}
        try:
            import yaml

            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- a corrupt sidecar must not take the canvas down
            return {}
        layout = doc.get("layout") if isinstance(doc, dict) else None
        return layout if isinstance(layout, dict) else {}

    def write(self, layout: dict[str, Any]) -> None:
        """Persist canvas positions into the active package's layout.yaml.

        Entries that are not {node_id: {x: number, y: number}} are dropped
        (the canvas regenerates them); an empty layout removes the sidecar, so
        packages stay clean unless there is something worth committing.
        """
        p = self.path()
        if p is None:
            raise ValueError("ONTOGENY_PACKAGE_ROOT not configured")
        clean: dict[str, dict[str, float]] = {}
        for node_id, pos in (layout or {}).items():
            if not isinstance(pos, dict):
                continue
            x, y = pos.get("x"), pos.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                clean[str(node_id)] = {"x": float(x), "y": float(y)}
        if not clean:
            if p.exists():
                p.unlink(missing_ok=True)
            return
        import yaml

        payload = yaml.safe_dump({"layout": clean}, allow_unicode=True, sort_keys=False)
        p.write_text(
            "# ontogeny canvas layout: hand-arranged node positions of the ontology\n"
            "# workbench, committed with the model by a builder save. Per package,\n"
            "# travels with zip import/export; safe to delete (auto layout returns).\n"
            + payload,
            encoding="utf-8",
        )
