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

"""Corpus discovery: which files belong to a document store, and their hashes.

Relative paths resolve against the package root, never the process CWD: a
container and a test must see the same corpus.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ..core.models import DocumentCfg, StoreResource
from ..errors import StoreError

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log", ".sql", ".xml", ".html", ".htm"}


@dataclass
class ScannedDocument:
    doc_id: str
    path: Path
    rel: str
    size: int
    media_type: str


def resolve_root(store: StoreResource, package_root: str | None) -> Path:
    raw = Path(store.spec.connection).expanduser()
    if not raw.is_absolute():
        if not package_root:
            raise StoreError(
                f"document store {store.metadata.name!r} uses a relative path but no package root is configured"
            )
        raw = Path(package_root) / raw
    root = raw.resolve()
    if not root.exists():
        raise StoreError(f"document corpus does not exist: {root}")
    if not root.is_dir():
        raise StoreError(f"document corpus is not a directory: {root}")
    return root


def _match(rel: str, cfg: DocumentCfg) -> bool:
    name = Path(rel).name

    def hit(pattern: str) -> bool:
        # ``**/*.md`` must also match a file at the corpus root, which
        # fnmatch alone does not (it has no "zero directories" reading)
        variants = {pattern}
        if pattern.startswith("**/"):
            variants.add(pattern[3:])
        return any(fnmatch(rel, pat) or fnmatch(name, pat) for pat in variants)

    if any(hit(pat) for pat in cfg.exclude):
        return False
    return any(hit(pat) for pat in cfg.include)


def _selector_root(root: Path, selector: str | None) -> Path:
    """``source.table`` selects a subdirectory (or a glob under the root)."""
    if not selector:
        return root
    candidate = root / selector
    if candidate.is_dir():
        return candidate.resolve()
    if candidate.is_file():
        return candidate.parent.resolve()
    return root


def scan(root: Path, cfg: DocumentCfg, selector: str | None = None) -> list[ScannedDocument]:
    base = _selector_root(root, selector)
    globs = [selector] if selector and any(ch in selector for ch in "*?[") else None
    out: list[ScannedDocument] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if globs is not None:
            if not any(fnmatch(rel, g) or fnmatch(path.name, g) for g in globs):
                continue
        elif not _match(rel, cfg):
            continue
        data = path.read_bytes()
        # identity is (path, content): two identical files are two documents,
        # and a file that moves is a different document (its old row retracts)
        doc_id = hashlib.sha256(rel.encode("utf-8") + b"\0" + data).hexdigest()
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        out.append(ScannedDocument(doc_id, path, rel, len(data), media))
    return out


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def read_for_agent(path: Path) -> tuple[str, str | None]:
    """Return ``(text, content_b64)`` for an external agent.

    Binary documents are shipped as base64 so a remote agent can parse them
    with its own toolchain; no parser dependency enters the platform.
    """
    if is_text(path):
        return path.read_text(encoding="utf-8-sig", errors="replace"), None
    return "", base64.b64encode(path.read_bytes()).decode("ascii")


async def read_text(path: Path, extractor: Any | None = None) -> str:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    if extractor is not None and hasattr(extractor, "read"):
        return await extractor.read(path)
    raise StoreError(
        f"no text reader for {path.suffix or path.name}; send it to an external agent "
        "(content_b64) or convert it to text/markdown"
    )


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
