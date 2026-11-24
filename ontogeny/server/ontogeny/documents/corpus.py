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
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from fnmatch import fnmatch
from pathlib import Path
from stat import S_ISDIR
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
    legacy_id: str | None = None
    selector_ids: tuple[str, ...] = ()


ScanCache = dict[str, tuple[tuple[int, int, int, int, int], ScannedDocument]]


class SelectorUnavailableError(Exception):
    """The selected filesystem path could not be verified."""


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


def _is_glob(selector: str) -> bool:
    return any(ch in selector for ch in "*?[")


def resolve_selector(root: Path, selector: str | None, registered_paths: Iterable[str] = ()) -> str | None:
    """Keep legacy logical table names while honoring paths known to the catalog."""
    if not selector or not selector.replace("-", "_").isidentifier():
        return selector
    candidate = root / selector
    try:
        # A dangling link is still an explicit filesystem selector.
        candidate.lstat()
    except FileNotFoundError:
        if not any(Path(path).is_relative_to(candidate) for path in registered_paths):
            return None
    except OSError:
        # An unreadable selector is not known to be missing.
        pass
    return selector


def _literal_path(root: Path, selector: str) -> Path:
    candidate = root / selector
    try:
        is_dir = S_ISDIR(candidate.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        is_dir = False
    # Resolve a symlinked directory or parent while retaining file names.
    path = candidate.resolve() if is_dir else candidate.parent.resolve() / candidate.name
    if not path.is_relative_to(root):
        raise StoreError("document selector escapes the corpus root")
    return path


def _glob_matches(root: Path, path: Path, selector: str) -> bool:
    return fnmatch(path.relative_to(root).as_posix(), selector) or fnmatch(path.name, selector)


def selector_covers(root: Path, path: Path, selector: str | None) -> bool:
    """Test selector membership even when the document has been removed."""
    if not path.is_relative_to(root):
        return False
    if not selector:
        return True
    if _is_glob(selector):
        return _glob_matches(root, path, selector)
    try:
        literal = _literal_path(root, selector)
        if path.is_relative_to(literal):
            return True
        if not literal.is_symlink():
            return False
    except OSError:
        return False
    # Directory symlinks register the resolved path. After the target is
    # deleted, limit recovery to its descendants and never follow it outside
    # the corpus. A file symlink registers the link's own path.
    try:
        target = literal.resolve()
    except (OSError, RuntimeError):
        return False
    if target.is_relative_to(root) and target in path.parents:
        try:
            target.stat()
        except (FileNotFoundError, NotADirectoryError):
            return True
        except OSError:
            pass
    return False


def _selected_paths(root: Path, cfg: DocumentCfg, selector: str | None) -> Iterator[tuple[Path, str]]:
    glob = selector if selector and _is_glob(selector) else None

    def fail_walk(error: OSError) -> None:
        # rglob can silently skip an unreadable directory, but reconciliation
        # requires a verified inventory before retiring any previous entries.
        raise error

    try:
        literal = _literal_path(root, selector) if selector and glob is None else root
        if literal.is_file():
            base, paths = literal.parent, [literal]
        elif literal.is_dir():
            base = literal
            paths = sorted(folder / name for folder, _, names in literal.walk(on_error=fail_walk) for name in names)
        else:
            # A missing literal file or directory selects nothing.
            return
    except OSError as exc:
        # Unreadable selectors must never widen discovery to the corpus root.
        raise SelectorUnavailableError from exc
    for path in paths:
        if glob is not None and not _glob_matches(root, path, glob):
            continue
        if not _match(path.relative_to(root).as_posix(), cfg):
            continue
        if path.is_file():
            yield path, path.relative_to(base).as_posix()


def _document_ids(rel: str, data: bytes, store_name: str) -> tuple[str, str]:
    digest = hashlib.sha256(rel.encode("utf-8") + b"\0")
    digest.update(data)
    legacy_id = digest.hexdigest()
    doc_id = hashlib.sha256(
        b"ontogeny-document-v2\0" + store_name.encode("utf-8") + b"\0" + bytes.fromhex(legacy_id)
    ).hexdigest()
    return doc_id, legacy_id


def _scanned_document(
    root: Path, path: Path, rel: str, store_name: str, existing_ids: set[str] | None = None
) -> ScannedDocument:
    data = path.read_bytes()
    root_rel = path.relative_to(root)
    doc_id, legacy_id = _document_ids(root_rel.as_posix(), data, store_name)
    # Older scans used the path relative to a selected directory. A suffix
    # is eligible for reuse only if the registry also records this exact path.
    selector_ids = (
        tuple(
            prior_id
            for offset in range(1, len(root_rel.parts))
            for prior_id in _document_ids("/".join(root_rel.parts[offset:]), data, store_name)
            if prior_id in existing_ids
        )
        if existing_ids and doc_id not in existing_ids and legacy_id not in existing_ids
        else ()
    )
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return ScannedDocument(doc_id, path, rel, len(data), media, legacy_id, selector_ids)


def scan(root: Path, cfg: DocumentCfg, selector: str | None = None, *, store_name: str) -> list[ScannedDocument]:
    root = root.resolve()
    selector = resolve_selector(root, selector)
    try:
        return [_scanned_document(root, path, rel, store_name) for path, rel in _selected_paths(root, cfg, selector)]
    except SelectorUnavailableError:
        return []


def scan_incremental(
    root: Path,
    cfg: DocumentCfg,
    selector: str | None = None,
    *,
    store_name: str,
    previous: ScanCache | None = None,
    existing_ids_by_path: dict[str, set[str]] | None = None,
) -> tuple[list[ScannedDocument], ScanCache]:
    """Discover selected files, reusing hashes when file identity and metadata match."""
    root = root.resolve()
    previous = previous or {}
    existing_ids_by_path = existing_ids_by_path or {}
    current: ScanCache = {}
    for path, rel in _selected_paths(root, cfg, selector):
        stat = path.stat()
        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        key = path.relative_to(root).as_posix()
        cached = previous.get(key)
        if cached is not None and cached[0] == signature:
            item = replace(cached[1], path=path, rel=rel)
        else:
            item = _scanned_document(root, path, rel, store_name, existing_ids_by_path.get(str(path)))
        current[key] = (signature, item)
    return [item for _, item in current.values()], current


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
