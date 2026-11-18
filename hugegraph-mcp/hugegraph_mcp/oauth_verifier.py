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

"""OAuth 2.1 / OIDC JWT Bearer token verifier."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from typing import Any

import jwt
from jwt import PyJWK, PyJWKClient, PyJWKSet

from hugegraph_mcp.runtime import VerifiedClaims

DEFAULT_ALLOWED_ALGORITHMS: tuple[str, ...] = ("RS256", "ES256", "EdDSA")
ALLOWED_ASYMMETRIC_ALGORITHMS: frozenset[str] = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512", "EdDSA"}
)


def _extract_scopes(claims: Mapping[str, Any]) -> frozenset[str]:
    scopes: set[str] = set()
    for claim_name in ("scope", "scp"):
        raw = claims.get(claim_name)
        if isinstance(raw, str):
            scopes.update(item.strip() for item in raw.split() if item.strip())
        elif isinstance(raw, Iterable):
            scopes.update(str(item).strip() for item in raw if str(item).strip())
    return frozenset(scopes)


class OAuthBearerVerifier:
    """Fail-closed JWT Bearer verifier using JWKS URL or static JWKS payload."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str | None = None,
        jwks_url: str | None = None,
        jwks_payload: Mapping[str, Any] | str | None = None,
        algorithms: tuple[str, ...] = DEFAULT_ALLOWED_ALGORITHMS,
        tenant_claim: str = "tenant",
        default_tenant: str = "default",
        subject_claim: str = "sub",
        required_scopes: Iterable[str] = (),
        leeway_seconds: int = 30,
        allow_missing_audience: bool = False,
    ) -> None:
        if not issuer.strip():
            raise ValueError("OAuth issuer must not be empty")
        if issuer.strip() == "local-stdio":
            raise ValueError("OAuth issuer 'local-stdio' is reserved for local stdio transport")
        if not audience and not allow_missing_audience:
            raise ValueError("OAuth audience must be configured for fail-closed verification")
        if not jwks_url and not jwks_payload:
            raise ValueError("Either jwks_url or jwks_payload must be configured")
        safe_algos = tuple(alg for alg in algorithms if alg in ALLOWED_ASYMMETRIC_ALGORITHMS)
        if not safe_algos:
            raise ValueError("At least one asymmetric signing algorithm must be allowed")

        self._issuer = issuer.strip()
        self._audience = audience.strip() if audience else None
        self._algorithms = list(safe_algos)
        self._tenant_claim = tenant_claim
        self._default_tenant = default_tenant
        self._subject_claim = subject_claim
        self._required_scopes = frozenset(s.strip() for s in required_scopes if s and s.strip())
        self._leeway_seconds = max(0, int(leeway_seconds))

        self._jwk_client: PyJWKClient | None = PyJWKClient(jwks_url) if jwks_url else None
        self._jwk_set: PyJWKSet | None = None
        if jwks_payload is not None:
            parsed = json.loads(jwks_payload) if isinstance(jwks_payload, str) else dict(jwks_payload)
            self._jwk_set = PyJWKSet.from_dict(parsed)

    def _resolve_signing_key(self, token: str) -> Any:
        header = jwt.get_unverified_header(token)
        alg = str(header.get("alg") or "")
        if alg not in self._algorithms:
            raise jwt.InvalidAlgorithmError(f"Algorithm {alg!r} is not allowed")
        kid = header.get("kid")
        if self._jwk_set is not None:
            keys = self._jwk_set.keys
            if kid is not None:
                for jwk in keys:
                    if jwk.key_id == kid:
                        return jwk.key
                raise jwt.InvalidTokenError(f"Unknown key id: {kid!r}")
            if len(keys) == 1 and isinstance(keys[0], PyJWK):
                return keys[0].key
            raise jwt.InvalidTokenError("Token header missing kid for multi-key JWKS")
        assert self._jwk_client is not None
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def _verify_sync(self, token: str) -> VerifiedClaims | None:
        if not token or not token.strip():
            return None
        try:
            signing_key = self._resolve_signing_key(token)
            options = {
                "require": ["exp", "iss", self._subject_claim],
                "verify_aud": self._audience is not None,
            }
            decode_kwargs: dict[str, Any] = {
                "algorithms": self._algorithms,
                "issuer": self._issuer,
                "leeway": self._leeway_seconds,
                "options": options,
            }
            if self._audience is not None:
                decode_kwargs["audience"] = self._audience
            payload = jwt.decode(token, signing_key, **decode_kwargs)
        except Exception:
            return None

        subject = str(payload.get(self._subject_claim) or "").strip()
        if not subject:
            return None
        raw_tenant = payload.get(self._tenant_claim)
        tenant = str(raw_tenant).strip() if raw_tenant is not None else ""
        if not tenant:
            tenant = self._default_tenant
        scopes = _extract_scopes(payload)
        if self._required_scopes and not self._required_scopes.issubset(scopes):
            return None

        return VerifiedClaims(
            issuer=str(payload.get("iss") or self._issuer),
            tenant=tenant,
            subject=subject,
            scopes=scopes,
        )

    async def verify(self, token: str) -> VerifiedClaims | None:
        return await asyncio.to_thread(self._verify_sync, token)
