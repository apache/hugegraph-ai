# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Local filesystem implementation of ArtifactStore."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hugegraph_mcp.artifact_models import ArtifactManifest, ArtifactPart
from hugegraph_mcp.artifacts.base import (
    ArtifactAccessError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStore,
)
from hugegraph_mcp.config import MCPConfig, get_effective_config

_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _split_utf8_chunks(text: str, max_bytes: int) -> list[bytes]:
    if not text:
        return [b""]
    chunks: list[bytes] = []
    current = bytearray()
    for ch in text:
        encoded = ch.encode("utf-8")
        if current and len(current) + len(encoded) > max_bytes:
            chunks.append(bytes(current))
            current.clear()
        current.extend(encoded)
    if current:
        chunks.append(bytes(current))
    return chunks


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


class LocalArtifactStore(ArtifactStore):
    """Stores immutable artifact manifests and bounded part files under state_dir."""

    def __init__(self, state_dir: Path) -> None:
        self.root = Path(state_dir) / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def _artifact_dir(self, artifact_id: str) -> Path:
        if not artifact_id or not _ARTIFACT_ID_RE.fullmatch(artifact_id):
            raise ArtifactNotFoundError(f"Invalid artifact_id: {artifact_id!r}")
        candidate = self.root / artifact_id
        if candidate.is_symlink():
            raise ArtifactNotFoundError(f"Invalid artifact_id: {artifact_id!r}")
        if not candidate.resolve().is_relative_to(self.root.resolve()):
            raise ArtifactNotFoundError(f"Invalid artifact_id: {artifact_id!r}")
        return candidate

    def put(
        self,
        payload: bytes | str,
        *,
        owner_key: str,
        tenant: str,
        target_graph: dict[str, Any],
        kind: str,
        media_type: str = "application/json",
        schema_fingerprint: str | None = None,
        request_id: str | None = None,
        ttl_seconds: float = 3600.0,
        part_size_bytes: int = 65_536,
    ) -> ArtifactManifest:
        raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        chunk_size = max(256, int(part_size_bytes))
        artifact_id = f"art-{secrets.token_urlsafe(12)}"
        art_dir = self._artifact_dir(artifact_id)
        art_dir.mkdir(parents=True, exist_ok=False)
        try:
            if isinstance(payload, str):
                parts = _split_utf8_chunks(payload, chunk_size)
            else:
                parts = [raw[i : i + chunk_size] for i in range(0, len(raw), chunk_size)] or [b""]
            part_hashes: list[str] = []
            for idx, chunk in enumerate(parts):
                (art_dir / f"part-{idx}.bin").write_bytes(chunk)
                part_hashes.append(hashlib.sha256(chunk).hexdigest())

            now = time.time()
            manifest = ArtifactManifest(
                artifact_id=artifact_id,
                owner_key=owner_key,
                tenant=tenant,
                target_graph=dict(target_graph),
                kind=kind,
                media_type=media_type,
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
                part_count=len(parts),
                part_size_bytes=chunk_size,
                created_at=now,
                expires_at=now + max(1.0, float(ttl_seconds)),
                pinned=False,
                schema_fingerprint=schema_fingerprint,
                request_id=request_id,
                part_sha256s=tuple(part_hashes),
            )
            _atomic_write_text(
                art_dir / "manifest.json",
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            )
            return manifest
        except BaseException:
            shutil.rmtree(art_dir, ignore_errors=True)
            raise

    def get_manifest(
        self,
        artifact_id: str,
        *,
        owner_key: str,
        tenant: str | None = None,
        target_graph: Mapping[str, Any] | None = None,
    ) -> ArtifactManifest:
        art_dir = self._artifact_dir(artifact_id)
        manifest_path = art_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")
        manifest = ArtifactManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        if manifest.owner_key != owner_key:
            raise ArtifactAccessError(f"Actor is not authorized to read artifact {artifact_id}")
        if tenant is not None and manifest.tenant != tenant:
            raise ArtifactAccessError(f"Actor tenant is not authorized to read artifact {artifact_id}")
        if target_graph is not None and manifest.target_graph != dict(target_graph):
            raise ArtifactAccessError(f"Artifact {artifact_id} does not belong to target graph")
        if not manifest.pinned and manifest.expires_at <= time.time():
            shutil.rmtree(art_dir, ignore_errors=True)
            raise ArtifactNotFoundError(f"Artifact has expired: {artifact_id}")
        return manifest

    def cleanup_expired(self, *, now: float | None = None) -> int:
        cutoff = time.time() if now is None else float(now)
        removed = 0
        if self.root.is_symlink() or not self.root.is_dir():
            return 0
        with os.scandir(self.root) as entries:
            for entry in entries:
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    continue
                child = Path(entry.path)
                manifest_path = child / "manifest.json"
                if manifest_path.is_symlink() or not manifest_path.is_file():
                    continue
                try:
                    manifest = ArtifactManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
                except Exception:
                    continue
                if not manifest.pinned and manifest.expires_at <= cutoff:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
        return removed

    def read_part(self, artifact_id: str, part_id: int, *, owner_key: str) -> ArtifactPart:
        manifest = self.get_manifest(artifact_id, owner_key=owner_key)
        if part_id < 0 or part_id >= manifest.part_count:
            raise ArtifactNotFoundError(f"Part {part_id} out of range for artifact {artifact_id}")
        part_path = self._artifact_dir(artifact_id) / f"part-{part_id}.bin"
        if part_path.is_symlink() or not part_path.is_file():
            raise ArtifactNotFoundError(f"Missing part file {part_id} for artifact {artifact_id}")
        raw = part_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if manifest.part_sha256s and part_id < len(manifest.part_sha256s) and digest != manifest.part_sha256s[part_id]:
            raise ArtifactIntegrityError(f"SHA-256 verification failed for artifact {artifact_id} part {part_id}")
        return ArtifactPart(
            artifact_id=artifact_id,
            part_id=part_id,
            content=raw.decode("utf-8", errors="replace"),
            sha256=digest,
            size_bytes=len(raw),
        )

    def read_all(self, artifact_id: str, *, owner_key: str) -> bytes:
        manifest = self.get_manifest(artifact_id, owner_key=owner_key)
        art_dir = self._artifact_dir(artifact_id)
        chunks: list[bytes] = []
        for idx in range(manifest.part_count):
            part_path = art_dir / f"part-{idx}.bin"
            if part_path.is_symlink() or not part_path.is_file():
                raise ArtifactNotFoundError(f"Missing part file {idx} for artifact {artifact_id}")
            chunks.append(part_path.read_bytes())
        raw = b"".join(chunks)
        if hashlib.sha256(raw).hexdigest() != manifest.sha256:
            raise ArtifactIntegrityError(f"SHA-256 verification failed for artifact {artifact_id}")
        return raw

    def pin(self, artifact_id: str, *, owner_key: str) -> ArtifactManifest:
        manifest = self.get_manifest(artifact_id, owner_key=owner_key)
        pinned = ArtifactManifest(
            **{**manifest.to_dict(), "pinned": True},
        )
        _atomic_write_text(
            self._artifact_dir(artifact_id) / "manifest.json",
            json.dumps(pinned.to_dict(), ensure_ascii=False, indent=2),
        )
        return pinned


def get_default_artifact_store(cfg: MCPConfig | None = None) -> LocalArtifactStore:
    effective = cfg or get_effective_config()
    return LocalArtifactStore(effective.state_dir)
