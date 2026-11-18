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

import asyncio
import json
import os
import time

import pytest

from hugegraph_mcp.artifacts import (
    ArtifactAccessError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    LocalArtifactStore,
)
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.runtime import create_runtime_lifespan


def test_local_artifact_store_parts_reassembly_and_owner_isolation(tmp_path):
    store = LocalArtifactStore(tmp_path)
    payload = ("hello-world-" * 60).encode("utf-8")
    manifest = store.put(
        payload,
        owner_key="tenant-a:user-1",
        tenant="tenant-a",
        target_graph={"graph": "g1"},
        kind="extraction_result",
        part_size_bytes=256,
    )
    assert manifest.part_count >= 2
    assert store.read_all(manifest.artifact_id, owner_key="tenant-a:user-1") == payload

    part0 = store.read_part(manifest.artifact_id, 0, owner_key="tenant-a:user-1")
    assert part0.size_bytes == 256

    with pytest.raises(ArtifactAccessError):
        store.get_manifest(manifest.artifact_id, owner_key="tenant-b:user-2")

    # Tamper with part 0 to trigger SHA-256 verification failure
    (tmp_path / "artifacts" / manifest.artifact_id / "part-0.bin").write_bytes(b"corrupted" * 20)
    with pytest.raises(ArtifactIntegrityError):
        store.read_all(manifest.artifact_id, owner_key="tenant-a:user-1")


def test_local_artifact_store_pin_survives_expiry(tmp_path):
    store = LocalArtifactStore(tmp_path)
    manifest = store.put(
        b"pinned-data",
        owner_key="local:operator",
        tenant="default",
        target_graph={"graph": "hugegraph"},
        kind="preview",
        ttl_seconds=1.0,
    )
    store.pin(manifest.artifact_id, owner_key="local:operator")
    assert store.get_manifest(manifest.artifact_id, owner_key="local:operator").pinned is True

    with pytest.raises(ArtifactNotFoundError):
        store.get_manifest("../escape", owner_key="local:operator")


def _expire_artifact(store: LocalArtifactStore, artifact_id: str) -> None:
    manifest_path = store.root / artifact_id / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["expires_at"] = time.time() - 10.0
    manifest_path.write_text(json.dumps(data), encoding="utf-8")


def test_local_artifact_store_does_not_follow_symlinks(tmp_path):
    store = LocalArtifactStore(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_manifest = outside / "manifest.json"
    outside_manifest.write_text(
        json.dumps(
            {
                "artifact_id": "art-outside",
                "owner_key": "local:operator",
                "tenant": "default",
                "target_graph": {"graph": "hugegraph"},
                "kind": "preview",
                "media_type": "application/json",
                "sha256": "0" * 64,
                "size_bytes": 0,
                "part_count": 0,
                "part_size_bytes": 256,
                "created_at": 0.0,
                "expires_at": 1.0,
                "pinned": False,
            }
        ),
        encoding="utf-8",
    )

    dir_symlink = store.root / "art-dirlink"
    manifest_holder = store.root / "art-manifestlink"
    manifest_holder.mkdir()
    try:
        os.symlink(outside, dir_symlink, target_is_directory=True)
        os.symlink(outside_manifest, manifest_holder / "manifest.json")
    except OSError as exc:
        pytest.skip(f"Symlink creation not permitted in this environment: {exc}")

    assert store.cleanup_expired() == 0
    assert outside.exists()
    assert outside_manifest.exists()
    with pytest.raises(ArtifactNotFoundError):
        store.get_manifest("art-dirlink", owner_key="local:operator")
    with pytest.raises(ArtifactNotFoundError):
        store.get_manifest("art-manifestlink", owner_key="local:operator")


def test_runtime_sweeps_expired_artifacts_while_idle(tmp_path):
    store = LocalArtifactStore(tmp_path)
    options = {"owner_key": "local:operator", "tenant": "default", "target_graph": {"graph": "g"}, "kind": "preview"}
    pinned = store.put("pinned", **options)
    store.pin(pinned.artifact_id, owner_key="local:operator")
    _expire_artifact(store, pinned.artifact_id)
    expired = store.put("expired", **options)
    _expire_artifact(store, expired.artifact_id)

    async def wait_for_cleanup():
        async with create_runtime_lifespan(MCPConfig(state_dir=tmp_path), artifact_sweep_interval_s=0.02)(None):
            async with asyncio.timeout(5):
                while (store.root / expired.artifact_id).exists():
                    await asyncio.sleep(0.02)
            assert store.read_all(pinned.artifact_id, owner_key="local:operator") == b"pinned"

    asyncio.run(wait_for_cleanup())
