# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Persistent, atomic ledger for single-use write confirmations."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.plan_hash import DEFAULT_PLAN_TTL_SECONDS
from hugegraph_mcp.write_plan import PlanStatus


class ConfirmationAlreadyUsedError(Exception):
    """The nonce has already authorized a write attempt."""


class ConfirmationStoreUnavailableError(Exception):
    """The durable confirmation ledger cannot safely record a write."""


class ConfirmationNotIssuedError(Exception):
    """The submitted plan was not issued by a server-side dry-run."""


class ConfirmationPlanMismatchError(Exception):
    """The submitted confirmation does not match the issued plan."""


class ConfirmationPlanExpiredError(Exception):
    """The server-issued plan is expired or exceeds the allowed TTL."""


class ConfirmationStore:
    """SQLite-backed confirmation ledger with a globally unique nonce digest."""

    DATABASE_NAME = "confirmations.sqlite3"

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.database_path = self.state_dir / self.DATABASE_NAME

    @classmethod
    def from_config(cls) -> ConfirmationStore:
        return cls(MCPConfig.from_env().state_dir)

    def has_consumed(self, nonce: str | None) -> bool:
        """Check whether a nonce was consumed without creating persistent state."""
        if not nonce or not self.database_path.exists():
            return False
        nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        try:
            with sqlite3.connect(self.database_path, timeout=30) as connection:
                row = connection.execute(
                    """
                    SELECT 1 FROM consumed_confirmations
                    WHERE nonce_digest = ? LIMIT 1
                    """,
                    (nonce_digest,),
                ).fetchone()
        except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
            raise ConfirmationStoreUnavailableError from exc
        return row is not None

    def operation_for_nonce(self, nonce: str | None) -> dict[str, Any] | None:
        """Return durable execution state for a consumed nonce."""
        if not nonce or not self.database_path.exists():
            return None
        nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        return self._operation_row("nonce_digest", nonce_digest)

    def operation_for_plan(self, plan_hash: str | None) -> dict[str, Any] | None:
        """Return durable execution state for a plan hash."""
        if not plan_hash or not self.database_path.exists():
            return None
        return self._operation_row("plan_hash", plan_hash)

    def record_outcome(
        self,
        *,
        plan_hash: str,
        status: PlanStatus,
        receipt: dict[str, Any],
    ) -> None:
        """Persist a final or reconcilable outcome after execution."""
        try:
            receipt_json = json.dumps(
                receipt,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            self._prepare_storage()
            with sqlite3.connect(self.database_path, timeout=30) as connection:
                connection.execute("PRAGMA synchronous = FULL")
                self._ensure_schema(connection)
                updated = connection.execute(
                    """
                    UPDATE write_operations
                    SET status = ?, receipt_json = ?, updated_at = ?
                    WHERE plan_hash = ?
                    """,
                    (status.value, receipt_json, int(time.time()), plan_hash),
                )
                if updated.rowcount != 1:
                    raise ConfirmationNotIssuedError
                connection.commit()
        except ConfirmationNotIssuedError:
            raise
        except (OSError, sqlite3.Error, TypeError) as exc:
            raise ConfirmationStoreUnavailableError from exc

    def issue(
        self,
        *,
        nonce: str,
        plan_hash: str,
        expires_at: int,
        plan_payload: Any | None = None,
    ) -> None:
        """Persist a server-issued dry-run plan before returning it to the caller."""
        nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        issued_at = int(time.time())
        expires_at = int(expires_at)
        payload_json = (
            json.dumps(
                plan_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if plan_payload is not None
            else None
        )
        if expires_at <= issued_at or expires_at > issued_at + DEFAULT_PLAN_TTL_SECONDS:
            raise ConfirmationPlanExpiredError

        try:
            self._prepare_storage()
            with sqlite3.connect(self.database_path, timeout=30) as connection:
                connection.execute("PRAGMA synchronous = FULL")
                self._ensure_schema(connection)
                self._cleanup_expired(connection, issued_at)
                connection.execute(
                    """
                    INSERT INTO issued_confirmations (
                        nonce_digest, plan_hash, expires_at, issued_at, plan_payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(nonce_digest) DO UPDATE SET
                        plan_hash = excluded.plan_hash,
                        expires_at = excluded.expires_at,
                        issued_at = excluded.issued_at,
                        plan_payload_json = excluded.plan_payload_json
                    WHERE issued_confirmations.plan_hash = excluded.plan_hash
                    """,
                    (nonce_digest, plan_hash, expires_at, issued_at, payload_json),
                )
                row = connection.execute(
                    """
                    SELECT plan_hash, expires_at, plan_payload_json
                    FROM issued_confirmations
                    WHERE nonce_digest = ?
                    """,
                    (nonce_digest,),
                ).fetchone()
                if row != (plan_hash, expires_at, payload_json):
                    raise ConfirmationPlanMismatchError
        except (ConfirmationPlanExpiredError, ConfirmationPlanMismatchError):
            raise
        except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
            raise ConfirmationStoreUnavailableError from exc

    def issued_payload(self, *, nonce: str, plan_hash: str, expires_at: int) -> Any | None:
        """Load the immutable server-side payload bound to an issued plan."""
        nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        current_time = int(time.time())
        try:
            if not self.database_path.exists():
                raise ConfirmationNotIssuedError
            with sqlite3.connect(self.database_path, timeout=30) as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    """
                    SELECT plan_hash, expires_at, issued_at, plan_payload_json
                    FROM issued_confirmations WHERE nonce_digest = ?
                    """,
                    (nonce_digest,),
                ).fetchone()
            if row is None:
                raise ConfirmationNotIssuedError
            issued_hash, issued_expires_at, issued_at, payload_json = row
            if issued_hash != plan_hash or issued_expires_at != int(expires_at):
                raise ConfirmationPlanMismatchError
            if current_time > issued_expires_at or issued_expires_at > issued_at + DEFAULT_PLAN_TTL_SECONDS:
                raise ConfirmationPlanExpiredError
            return json.loads(payload_json) if payload_json is not None else None
        except (
            ConfirmationNotIssuedError,
            ConfirmationPlanMismatchError,
            ConfirmationPlanExpiredError,
        ):
            raise
        except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
            raise ConfirmationStoreUnavailableError from exc

    def consume(self, *, nonce: str, plan_hash: str, expires_at: int) -> Any | None:
        """Atomically validate and consume a server-issued dry-run plan."""
        nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        consumed_at = int(time.time())

        try:
            self._prepare_storage()
            with sqlite3.connect(self.database_path, timeout=30) as connection:
                connection.execute("PRAGMA synchronous = FULL")
                self._ensure_schema(connection)
                try:
                    self._cleanup_expired(connection, consumed_at)
                except sqlite3.Error:
                    connection.rollback()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    consumed = connection.execute(
                        """
                        SELECT 1 FROM consumed_confirmations
                        WHERE nonce_digest = ? LIMIT 1
                        """,
                        (nonce_digest,),
                    ).fetchone()
                    if consumed is not None:
                        raise ConfirmationAlreadyUsedError
                    issued = connection.execute(
                        """
                        SELECT plan_hash, expires_at, issued_at, plan_payload_json
                        FROM issued_confirmations WHERE nonce_digest = ?
                        """,
                        (nonce_digest,),
                    ).fetchone()
                    if issued is None:
                        raise ConfirmationNotIssuedError
                    issued_hash, issued_expires_at, issued_at, payload_json = issued
                    if issued_hash != plan_hash or issued_expires_at != int(expires_at):
                        raise ConfirmationPlanMismatchError
                    if consumed_at > issued_expires_at or issued_expires_at > issued_at + DEFAULT_PLAN_TTL_SECONDS:
                        raise ConfirmationPlanExpiredError
                    connection.execute(
                        """
                        INSERT INTO consumed_confirmations (
                            nonce_digest, plan_hash, expires_at, consumed_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (nonce_digest, plan_hash, int(expires_at), consumed_at),
                    )
                    connection.execute(
                        """
                        INSERT INTO write_operations (
                            plan_hash, nonce_digest, plan_payload_json,
                            status, receipt_json, updated_at
                        ) VALUES (?, ?, ?, ?, NULL, ?)
                        """,
                        (
                            plan_hash,
                            nonce_digest,
                            payload_json,
                            PlanStatus.EXECUTING.value,
                            consumed_at,
                        ),
                    )
                    connection.execute(
                        "DELETE FROM issued_confirmations WHERE nonce_digest = ?",
                        (nonce_digest,),
                    )
                    connection.commit()
                    return json.loads(payload_json) if payload_json is not None else None
                except sqlite3.IntegrityError as exc:
                    raise ConfirmationAlreadyUsedError from exc
        except (
            ConfirmationAlreadyUsedError,
            ConfirmationNotIssuedError,
            ConfirmationPlanMismatchError,
            ConfirmationPlanExpiredError,
        ):
            raise
        except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
            raise ConfirmationStoreUnavailableError from exc

    def _cleanup_expired(self, connection: sqlite3.Connection, current_time: int) -> None:
        """Best-effort cleanup that never authorizes or blocks a current plan."""
        connection.execute(
            "DELETE FROM consumed_confirmations WHERE expires_at < ?",
            (current_time,),
        )
        connection.execute(
            "DELETE FROM issued_confirmations WHERE expires_at < ?",
            (current_time,),
        )
        connection.commit()

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        """Create additive tables so existing confirmation databases remain valid."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS consumed_confirmations (
                nonce_digest TEXT PRIMARY KEY,
                plan_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS issued_confirmations (
                nonce_digest TEXT PRIMARY KEY,
                plan_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                issued_at INTEGER NOT NULL,
                plan_payload_json TEXT
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(issued_confirmations)")}
        if "plan_payload_json" not in columns:
            connection.execute("ALTER TABLE issued_confirmations ADD COLUMN plan_payload_json TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS write_operations (
                plan_hash TEXT PRIMARY KEY,
                nonce_digest TEXT NOT NULL UNIQUE,
                plan_payload_json TEXT,
                status TEXT NOT NULL,
                receipt_json TEXT,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.commit()

    def _operation_row(self, field: str, value: str) -> dict[str, Any] | None:
        if field not in {"nonce_digest", "plan_hash"}:
            raise ValueError("Unsupported operation lookup field")
        query = (
            "SELECT plan_hash, status, plan_payload_json, receipt_json, updated_at "
            f"FROM write_operations WHERE {field} = ?"
        )
        try:
            with sqlite3.connect(self.database_path, timeout=30) as connection:
                self._ensure_schema(connection)
                row = connection.execute(query, (value,)).fetchone()
            if row is None:
                return None
            plan_hash, status, payload_json, receipt_json, updated_at = row
            return {
                "plan_hash": plan_hash,
                "status": status,
                "plan": json.loads(payload_json) if payload_json else None,
                "receipt": json.loads(receipt_json) if receipt_json else None,
                "updated_at": updated_at,
            }
        except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
            raise ConfirmationStoreUnavailableError from exc

    def _prepare_storage(self) -> None:
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        _restrict_permissions(self.state_dir, 0o700)

        descriptor = os.open(
            self.database_path,
            os.O_CREAT | os.O_APPEND | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        _restrict_permissions(self.database_path, 0o600)


def _restrict_permissions(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except (NotImplementedError, OSError):
        if os.name == "posix":
            raise
