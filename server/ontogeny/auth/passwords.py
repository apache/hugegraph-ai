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
"""Password hashing with the standard library only.

``hashlib.scrypt`` is a memory-hard KDF and is part of CPython, so the platform
gains real password storage without taking on passlib/bcrypt/argon2 as
dependencies (the project deliberately keeps its dependency surface small: the
whole backend is pydantic + SQLAlchemy + FastAPI).

The stored format is self-describing so the cost parameters can be raised later
without invalidating existing hashes::

    scrypt$<n>$<r>$<p>$<salt-hex>$<hash-hex>

Verification is constant-time and never raises on a malformed row — a corrupt
hash is a failed login, not a 500.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

# ~32 MB of working memory, tens of ms per hash: enough that an offline attack
# on a stolen database is expensive, cheap enough that login stays interactive.
# `maxmem` must be passed explicitly -- OpenSSL caps scrypt at 32 MB by default,
# and 128*N*r for these parameters lands just above it, so omitting it fails with
# "memory limit exceeded" rather than silently weakening the hash.
_N, _R, _P = 2 ** 15, 8, 1
_DKLEN = 32
_MAXMEM = 128 * _N * _R * 2  # headroom over the algorithm's own requirement


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P,
                        dklen=_DKLEN, maxmem=_MAXMEM)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_hex, want_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        want = bytes.fromhex(want_hex)
        got = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
            dklen=len(want), maxmem=max(_MAXMEM, 128 * int(n) * int(r) * 2),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def new_token() -> str:
    """A bearer token for one session (URL-safe, 256 bits)."""
    return secrets.token_urlsafe(32)


def token_fingerprint(token: str) -> str:
    """What we actually store: the token is a bearer secret, so the database
    keeps only a digest that cannot be replayed."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
