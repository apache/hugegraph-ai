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

from __future__ import annotations

import asyncio
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from hugegraph_mcp.oauth_verifier import OAuthBearerVerifier
from hugegraph_mcp.stores.base import Actor


def _generate_rsa_keypair_and_jwks(kid: str = "test-key-1"):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = kid
    public_jwk["use"] = "sig"
    public_jwk["alg"] = "RS256"
    return private_key, {"keys": [public_jwk]}


def test_oauth_verifier_accepts_valid_jwt_and_extracts_claims() -> None:
    private_key, jwks = _generate_rsa_keypair_and_jwks()
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://auth.example.com",
            "aud": "hugegraph-mcp",
            "sub": "alice",
            "tenant": "acme",
            "scope": "mcp:read mcp:write",
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )
    verifier = OAuthBearerVerifier(
        issuer="https://auth.example.com",
        audience="hugegraph-mcp",
        jwks_payload=jwks,
        required_scopes=("mcp:read",),
    )

    claims = asyncio.run(verifier.verify(token))
    assert claims is not None
    assert claims.issuer == "https://auth.example.com"
    assert claims.tenant == "acme"
    assert claims.subject == "alice"
    assert claims.scopes == frozenset({"mcp:read", "mcp:write"})


def test_oauth_verifier_rejects_bad_issuer_audience_expired_or_missing_scope() -> None:
    private_key, jwks = _generate_rsa_keypair_and_jwks()
    now = int(time.time())
    verifier = OAuthBearerVerifier(
        issuer="https://auth.example.com",
        audience="hugegraph-mcp",
        jwks_payload=jwks,
        required_scopes=("mcp:write",),
        leeway_seconds=0,
    )

    bad_iss = jwt.encode(
        {
            "iss": "https://evil.example.com",
            "aud": "hugegraph-mcp",
            "sub": "alice",
            "scope": "mcp:write",
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )
    bad_aud = jwt.encode(
        {
            "iss": "https://auth.example.com",
            "aud": "other-api",
            "sub": "alice",
            "scope": "mcp:write",
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )
    expired = jwt.encode(
        {
            "iss": "https://auth.example.com",
            "aud": "hugegraph-mcp",
            "sub": "alice",
            "scope": "mcp:write",
            "exp": now - 60,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )
    missing_scope = jwt.encode(
        {
            "iss": "https://auth.example.com",
            "aud": "hugegraph-mcp",
            "sub": "alice",
            "scope": "mcp:read",
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )

    assert asyncio.run(verifier.verify(bad_iss)) is None
    assert asyncio.run(verifier.verify(bad_aud)) is None
    assert asyncio.run(verifier.verify(expired)) is None
    assert asyncio.run(verifier.verify(missing_scope)) is None


def test_actor_principal_key_namespaces_by_issuer() -> None:
    a1 = Actor(issuer="https://idp-a.example", tenant="acme", subject="alice")
    a2 = Actor(issuer="https://idp-b.example", tenant="acme", subject="alice")
    assert a1.principal_key != a2.principal_key
