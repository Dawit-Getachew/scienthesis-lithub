"""Token validation: Identity-issued RS256 user tokens (via JWKS) + HS256 service tokens."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import jwt
import structlog
from jwt import algorithms

from src.core.config import Settings, get_settings
from src.core.exceptions import (
    AuthenticationError,
    JWKSUnavailableError,
    ServiceTokenError,
)

logger = structlog.get_logger(__name__)

_USER_TOKEN_ALG = "RS256"
_SERVICE_TOKEN_ALG = "HS256"


# ── JWKS cache ──────────────────────────────────────────────────────


class _JWKSCache:
    """Async-safe JWKS cache shared across the process."""

    def __init__(self) -> None:
        self._keys_by_kid: dict[str, Any] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    def _is_fresh(self, ttl: int) -> bool:
        return bool(self._keys_by_kid) and (time.time() - self._fetched_at) < ttl

    async def fetch(self, http_client: httpx.AsyncClient, settings: Settings) -> dict[str, Any]:
        if self._is_fresh(settings.JWKS_CACHE_TTL_SECONDS):
            return self._keys_by_kid
        async with self._lock:
            if self._is_fresh(settings.JWKS_CACHE_TTL_SECONDS):
                return self._keys_by_kid
            url = settings.resolve_jwks_url()
            try:
                resp = await http_client.get(url, timeout=8.0)
                resp.raise_for_status()
                body = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.error("jwks_fetch_failed", url=url, error=str(exc))
                return self._keys_by_kid
            self._keys_by_kid = {
                k["kid"]: k for k in body.get("keys", []) if "kid" in k
            }
            self._fetched_at = time.time()
            return self._keys_by_kid

    def clear(self) -> None:
        self._keys_by_kid = {}
        self._fetched_at = 0.0


_jwks_cache = _JWKSCache()


def reset_jwks_cache() -> None:
    """Clear the cached JWKS (test helper)."""
    _jwks_cache.clear()


# ── User access token validation ────────────────────────────────────


async def validate_access_token(
    token: str,
    *,
    http_client: httpx.AsyncClient,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Verify *token* against the Identity Service's JWKS.

    Raises :class:`AuthenticationError` on any failure.
    """
    settings = settings or get_settings()

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Malformed access token.") from exc

    if header.get("alg") != _USER_TOKEN_ALG:
        raise AuthenticationError(f"Unexpected token algorithm: {header.get('alg')}.")
    kid = header.get("kid")
    if not kid:
        raise AuthenticationError("Access token missing 'kid' header.")

    keys = await _jwks_cache.fetch(http_client, settings)
    key_dict = keys.get(kid)
    if key_dict is None:
        # Force a refresh in case keys were rotated. Single retry only.
        _jwks_cache.clear()
        keys = await _jwks_cache.fetch(http_client, settings)
        key_dict = keys.get(kid)
        if key_dict is None:
            raise AuthenticationError("Unknown signing key for access token.")

    if not keys:
        raise JWKSUnavailableError("Identity JWKS endpoint returned no keys.")

    public_key = algorithms.RSAAlgorithm.from_jwk(key_dict)

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[_USER_TOKEN_ALG],
            audience=settings.IDENTITY_JWT_AUDIENCE,
            issuer=settings.IDENTITY_JWT_ISSUER,
        )
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError(f"Invalid access token: {exc}.") from exc

    if payload.get("type") != "access":
        raise AuthenticationError("Token type is not 'access'.")
    if not payload.get("sub"):
        raise AuthenticationError("Token missing 'sub' claim.")
    return payload


# ── Service token validation (X-Service-Token) ─────────────────────


def validate_service_token(
    token: str,
    settings: Settings,
    expected_audience: str = "scienthesis-lithub",
) -> dict[str, Any]:
    """Verify an inbound ``X-Service-Token`` HS256 JWT.

    Raises :class:`ServiceTokenError` on any failure.
    """
    if not settings.SERVICE_TOKEN_SECRET:
        raise ServiceTokenError("LitHub internal API is not configured (no SERVICE_TOKEN_SECRET).")
    try:
        payload = jwt.decode(
            token,
            settings.SERVICE_TOKEN_SECRET,
            algorithms=[_SERVICE_TOKEN_ALG],
            audience=expected_audience,
        )
    except jwt.InvalidTokenError as exc:
        raise ServiceTokenError("Invalid service token.") from exc

    if payload.get("type") != "service":
        raise ServiceTokenError("Token type is not 'service'.")

    issuer = payload.get("iss")
    if issuer not in settings.service_token_allowed_issuers_list:
        raise ServiceTokenError(f"Service token issuer '{issuer}' is not allowed.")

    return payload
