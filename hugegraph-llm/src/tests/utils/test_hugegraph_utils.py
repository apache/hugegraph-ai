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

import json
import os
import stat
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import Mock

import pytest

from hugegraph_llm.config import huge_settings
from hugegraph_llm.utils import hugegraph_utils
from hugegraph_llm.utils.hugegraph_utils import get_hg_client


def test_request_connection_passes_canonical_validated_url(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "127.0.0.1:8080")
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr("hugegraph_llm.utils.hugegraph_utils.PyHugeClient", factory)

    result = get_hg_client(
        {
            "url": "http://127.0.0.1:8080/",
            "graph": "hugegraph",
            "user": "admin",
            "pwd": "secret",
            "graphspace": "DEFAULT",
        }
    )

    assert result is client
    assert factory.call_args.kwargs["url"] == "http://127.0.0.1:8080"


@pytest.mark.parametrize("url", ["http://:80", "http://user@127.0.0.1:8080", "http://[::1"])
def test_request_connection_rejects_invalid_url_before_client_construction(monkeypatch, url):
    monkeypatch.setattr(huge_settings, "graph_url", "http://127.0.0.1:8080")
    factory = Mock()
    monkeypatch.setattr("hugegraph_llm.utils.hugegraph_utils.PyHugeClient", factory)

    with pytest.raises(ValueError, match="Graph URL"):
        get_hg_client(
            {
                "url": url,
                "graph": "hugegraph",
                "user": "admin",
                "pwd": "secret",
                "graphspace": None,
            }
        )

    factory.assert_not_called()


@pytest.mark.parametrize("legacy_kind", ["file", "absent", "directory"])
def test_schema_backup_replaces_current_json_before_scoped_legacy_cleanup(tmp_path, legacy_kind):
    current = tmp_path / "current"
    historical = tmp_path / "historical"
    current.mkdir()
    historical.mkdir()
    previous = historical / "schema.groovy"
    previous.write_text("historical schema", encoding="utf-8")
    legacy = current / "schema.groovy"
    if legacy_kind == "file":
        legacy.write_text("stale schema", encoding="utf-8")
    elif legacy_kind == "directory":
        legacy.mkdir()
    target = current / "schema.json"
    target.write_text('{"old": true}', encoding="utf-8")
    schema = {"vertexlabels": [{"name": "人物"}]}

    hugegraph_utils.write_backup_file(None, current, "schema.json", schema, True)

    assert json.loads(target.read_text(encoding="utf-8")) == schema
    assert legacy.exists() == (legacy_kind == "directory")
    assert previous.read_text(encoding="utf-8") == "historical schema"
    assert list(current.glob(".schema.json.*")) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are required")
def test_atomic_backup_preserves_legacy_file_permissions(tmp_path):
    old_umask = os.umask(0o002)
    try:
        target = tmp_path / "schema.json"
        hugegraph_utils.write_backup_file(None, tmp_path, "schema.json", {"version": 1}, True)
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(target.stat().st_mode) == 0o664

    target.chmod(0o640)
    hugegraph_utils.write_backup_file(None, tmp_path, "schema.json", {"version": 2}, True)

    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2}


@pytest.mark.parametrize("failure", ["serialize", "close", "replace"])
def test_schema_backup_failures_preserve_both_previous_files(tmp_path, monkeypatch, failure):
    target = tmp_path / "schema.json"
    target.write_text('{"old": true}', encoding="utf-8")
    legacy = tmp_path / "schema.groovy"
    legacy.write_text("old schema", encoding="utf-8")
    schema = {"vertexlabels": []}
    expected_error = OSError
    if failure == "serialize":
        schema["invalid"] = object()
        expected_error = TypeError
    elif failure == "close":
        original = hugegraph_utils.NamedTemporaryFile

        @contextmanager
        def failed_close(*args, **kwargs):
            with original(*args, **kwargs) as stream:
                yield stream
            raise OSError("close failed")

        monkeypatch.setattr(hugegraph_utils, "NamedTemporaryFile", failed_close)
    else:

        def failed_replace(*_args):
            raise OSError("replace failed")

        monkeypatch.setattr(hugegraph_utils.os, "replace", failed_replace)

    with pytest.raises(expected_error):
        hugegraph_utils.write_backup_file(None, tmp_path, "schema.json", schema, True)

    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
    assert legacy.read_text(encoding="utf-8") == "old schema"
    assert list(tmp_path.glob(".schema.json.*")) == []


def test_backup_flow_writes_native_schema_and_cleans_only_reused_directory(tmp_path, monkeypatch):
    backup = tmp_path / "backups"
    current = backup / "20261102"
    historical = backup / "20261101"
    current.mkdir(parents=True)
    historical.mkdir()
    (current / "schema.groovy").write_text("stale", encoding="utf-8")
    (historical / "schema.groovy").write_text("historic", encoding="utf-8")
    schema = {"vertexlabels": [{"name": "person", "id_strategy": "PRIMARY_KEY"}]}
    client = Mock()
    client.schema.return_value.get_schema.return_value = schema
    client.gremlin.return_value.exec.side_effect = [
        {"data": [{"vertices": [{"id": "alice", "label": "person", "properties": {"name": "Alice"}}]}]},
        {"data": [{"edges": [{"id": "edge", "outV": "alice", "inV": "bob"}]}]},
    ]
    monkeypatch.setattr(hugegraph_utils, "get_hg_client", lambda: client)
    monkeypatch.setattr(hugegraph_utils, "BACKUP_DIR", str(backup))
    monkeypatch.setattr(hugegraph_utils, "resource_path", str(tmp_path))
    monkeypatch.setattr(hugegraph_utils, "datetime", Mock(now=Mock(return_value=datetime(2026, 11, 2))))

    assert "Backup successfully" in hugegraph_utils.backup_data()

    client.schema.return_value.get_schema.assert_called_once_with()
    assert json.loads((current / "schema.json").read_text(encoding="utf-8")) == schema
    assert json.loads((current / "vertices.json").read_text(encoding="utf-8")) == [
        {"label": "person", "properties": {"name": "Alice"}}
    ]
    assert json.loads((current / "edges.json").read_text(encoding="utf-8"))[0]["outV"] == "alice"
    assert not (current / "schema.groovy").exists()
    assert (historical / "schema.groovy").read_text(encoding="utf-8") == "historic"
