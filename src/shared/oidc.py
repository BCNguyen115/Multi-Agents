"""OpenID Connect sign-in (authorization code flow with PKCE) against any standards-following identity provider.

The provider only proves WHO the user is. The gateway then issues its own token (``auth.issue_login_token``), so cookies,
sign-out, revocation and every role check stay as they are; tenant, department and roles of a new account are granted by an
administrator in ``/admin`` (the account starts in the pending tenant, like a self-registration).

Checks on the ``id_token``: signature against the provider's JWKS (RS256/ES256 only), ``iss``, ``aud`` = our client id, ``exp``,
``nonce`` = the one we sent, and ``email_verified`` is not explicitly false. ``state`` is single use and lives 10 minutes in Redis.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import time
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import jwt

from src.config import settings

_ALGORITHMS = ["RS256", "ES256"]
STATE_TTL_SECONDS = 600
_DISCOVERY_TTL_SECONDS = 3600
_discovery_cache: tuple[float, dict[str, Any]] | None = None


def sso_enabled() -> bool:
    """SSO needs the gateway's own tokens (HS256 secret, no external JWKS) and the provider's issuer, client id and secret."""
    return bool(
        settings.AUTH_MODE == "jwt" and settings.AUTH_JWT_SECRET and not settings.AUTH_JWKS_URL
        and settings.OIDC_ISSUER and settings.OIDC_CLIENT_ID and settings.OIDC_CLIENT_SECRET and settings.OIDC_REDIRECT_URI
    )


def new_login() -> tuple[str, str, str]:
    """``(state, nonce, pkce verifier)``: three unguessable values for one sign-in attempt."""
    return secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


async def discovery() -> dict[str, Any]:
    """The provider's metadata (``/.well-known/openid-configuration``), cached for an hour."""
    global _discovery_cache
    now = time.monotonic()
    if _discovery_cache and now - _discovery_cache[0] < _DISCOVERY_TTL_SECONDS:
        return _discovery_cache[1]
    url = settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url)
        response.raise_for_status()
        meta = response.json()
    for key in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not meta.get(key):
            raise ValueError(f"identity provider metadata lacks {key}")
    _discovery_cache = (now, meta)
    return meta


def authorize_url(meta: dict[str, Any], state: str, nonce: str, verifier: str) -> str:
    query = urlencode({
        "response_type": "code", "client_id": settings.OIDC_CLIENT_ID, "redirect_uri": settings.OIDC_REDIRECT_URI,
        "scope": settings.OIDC_SCOPES, "state": state, "nonce": nonce,
        "code_challenge": pkce_challenge(verifier), "code_challenge_method": "S256",
    })
    return f"{meta['authorization_endpoint']}?{query}"


async def exchange_code(meta: dict[str, Any], code: str, verifier: str) -> dict[str, Any]:
    """Trade the one-time ``code`` for the provider's tokens (client secret in the body, PKCE verifier proves it is the same client)."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": settings.OIDC_REDIRECT_URI,
                "client_id": settings.OIDC_CLIENT_ID, "client_secret": settings.OIDC_CLIENT_SECRET, "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


def _signing_key(id_token: str, jwks_uri: str) -> Any:
    return jwt.PyJWKClient(jwks_uri, cache_keys=True).get_signing_key_from_jwt(id_token).key


async def verify_id_token(id_token: str, meta: dict[str, Any], nonce: str) -> dict[str, Any]:
    """The verified claims, or ``jwt.InvalidTokenError`` for anything that is not exactly the sign-in we started."""
    key = await asyncio.to_thread(_signing_key, id_token, meta["jwks_uri"])
    claims = jwt.decode(
        id_token, key, algorithms=_ALGORITHMS, audience=settings.OIDC_CLIENT_ID, issuer=meta["issuer"],
        options={"require": ["exp", "iat", "sub"]},
    )
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise jwt.InvalidTokenError("nonce mismatch")
    if claims.get("email_verified") is False:
        raise jwt.InvalidTokenError("email not verified")
    return claims


def account_name(claims: dict[str, Any]) -> str:
    """`sso:<email or preferred_username or sub>`: the prefix keeps these accounts apart from password accounts of the same name."""
    value: Optional[Any] = claims.get(settings.OIDC_USERNAME_CLAIM) or claims.get("preferred_username") or claims.get("sub")
    return "sso:" + str(value).strip().lower()[:58]
