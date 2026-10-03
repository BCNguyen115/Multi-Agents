"""Gateway authentication: who is calling, and which tenant / department / roles they carry.

``AUTH_MODE=off`` (default, local dev): every caller is the same anonymous user and nothing changes.
``AUTH_MODE=jwt``: every protected route needs ``Authorization: Bearer <JWT>``, verified either with a shared HS256
secret (``AUTH_JWT_SECRET``) or against an identity provider's JWKS (``AUTH_JWKS_URL``, RS256/ES256). The token's
``sub`` becomes the user; ``tenant_id`` / ``department_id`` / ``roles`` claims (names configurable) carry the scope.

What the identity is used for:
  * sessions: ``Principal.session()`` prefixes the client's session id with the user id, so two users can never share,
    read or approve each other's conversations, cached files or pending Human-in-the-Loop actions;
  * Row-Level Security: ``current_scope()`` gives the SQL layer the caller's tenant and department;
  * approvals: only ``HITL_APPROVER_ROLES`` may approve a sensitive action, and the approver is logged.

Signing in from the browser: with ``AUTH_JWT_SECRET`` and a user list in ``AUTH_USERS`` the gateway offers
``POST /api/auth/login`` (scrypt password check, rate limited per IP) and returns a short-lived token; the frontend keeps it in
an httpOnly cookie and forwards it as the Bearer header. With an identity provider (``AUTH_JWKS_URL``) put an
identity-aware proxy (oauth2-proxy, an API gateway, ...) in front instead. ``scripts/make_token.py`` mints tokens for tests,
``scripts/make_user.py`` makes an ``AUTH_USERS`` entry.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Optional

import jwt
from fastapi import HTTPException, Request

from src.config import settings
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

_PLACEHOLDER_MARKERS: tuple[str, ...] = ("change-me", "changeme", "your-", "example", "secret-key")
_MIN_HS256_SECRET_CHARS: int = 32
_MIN_SANDBOX_SECRET_CHARS: int = 16
_ASYMMETRIC_ALGORITHMS: list[str] = ["RS256", "ES256"]


@dataclass(frozen=True)
class Principal:
    """The authenticated caller (or the anonymous dev user when authentication is off)."""

    user_id: str
    tenant_id: str
    department_id: str
    roles: frozenset[str] = frozenset()
    authenticated: bool = False
    display_name: str = ""  # shown in the UI; the ``name`` claim of a built-in sign-in token, empty otherwise
    token_id: str = ""      # the token's ``jti`` (what a sign-out revokes); empty for a token without one
    token_exp: int = 0      # the token's ``exp``: how long a revocation has to be remembered

    def session(self, client_session_id: str) -> str:
        """The session key used everywhere behind the gateway: bound to the user when authenticated."""
        return f"{self.user_id}:{client_session_id}" if self.authenticated else client_session_id

    @property
    def can_approve(self) -> bool:
        """Anonymous dev mode may approve; with authentication only the configured roles may."""
        return not self.authenticated or bool(self.roles & set(settings.HITL_APPROVER_ROLES))

    @property
    def unassigned(self) -> bool:
        """A signed-in account nobody has moved out of the pending tenant yet (a fresh self-registration): it may chat,
        but sees no document of the knowledge base and no database row."""
        return self.authenticated and self.tenant_id == settings.REGISTRATION_TENANT_ID

    @property
    def can_manage_knowledge(self) -> bool:
        """Anonymous dev mode may change the knowledge base; with authentication only ``KNOWLEDGE_UPLOAD_ROLES`` may."""
        return not self.authenticated or bool(self.roles & set(settings.KNOWLEDGE_UPLOAD_ROLES))


_current: ContextVar[Optional[Principal]] = ContextVar("current_principal", default=None)
_jwks_client: Optional[jwt.PyJWKClient] = None


def current_scope() -> tuple[str, str]:
    """(tenant id, department id) of the request being served; the configured defaults outside a request."""
    principal = _current.get()
    return (principal.tenant_id, principal.department_id) if principal else (settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID)


def current_principal() -> Optional[Principal]:
    """The caller of the request being served (``None`` outside a request)."""
    return _current.get()


def knowledge_tenants() -> Optional[list[str]]:
    """Tenants whose chunks the caller may retrieve (``None`` = all). An unassigned account gets only its own pending tenant,
    under which no chunk is ever stored."""
    principal = _current.get()
    if principal is not None and principal.unassigned:
        return [principal.tenant_id]
    return settings.RAG_TENANT_IDS


def memory_user_id(session_id: str) -> str:
    """Who long-term memory belongs to: the authenticated user (so it follows them across conversations), else the session.

    Prefixed with the tenant so two tenants that happen to share a user id never share memories.
    """
    principal = _current.get()
    return f"{principal.tenant_id}:{principal.user_id}" if principal and principal.authenticated else session_id


def _looks_like_placeholder(value: str) -> bool:
    return any(marker in value.lower() for marker in _PLACEHOLDER_MARKERS)


def validate_auth_config() -> None:
    """Refuse to start with an unsafe configuration (called once at gateway startup)."""
    mode = settings.AUTH_MODE
    if mode not in ("off", "jwt"):
        raise RuntimeError(f"AUTH_MODE must be 'off' or 'jwt', got {mode!r}")
    if mode == "off":
        if settings.APP_ENV == "production":
            raise RuntimeError("APP_ENV=production refuses AUTH_MODE=off: every caller would be an anonymous administrator")
        if settings.INTERNAL_JWT_SECRET and _looks_like_placeholder(settings.INTERNAL_JWT_SECRET):
            logger.warning("INTERNAL_JWT_SECRET is still a placeholder value; set a real secret before exposing the service")
        logger.warning("AUTH_MODE=off: the gateway accepts anonymous requests (fine for local development only)")
        return
    if not settings.AUTH_JWKS_URL:
        secret = settings.AUTH_JWT_SECRET
        if len(secret) < _MIN_HS256_SECRET_CHARS or _looks_like_placeholder(secret):
            raise RuntimeError(f"AUTH_MODE=jwt needs AUTH_JWKS_URL or an AUTH_JWT_SECRET of at least {_MIN_HS256_SECRET_CHARS} random characters")
    if settings.INTERNAL_JWT_SECRET and _looks_like_placeholder(settings.INTERNAL_JWT_SECRET):
        raise RuntimeError("INTERNAL_JWT_SECRET is still a placeholder value; refusing to start with AUTH_MODE=jwt")
    for entry in settings.AUTH_USERS:
        name = str(entry.get("username", "")).strip()
        stored = str(entry.get("password_hash", ""))
        if not name or not stored.startswith("scrypt$") or stored.count("$") != 5:
            raise RuntimeError("AUTH_USERS entries need a username and a password_hash made by `python -m scripts.make_user`")
    if settings.AUTH_USERS and settings.AUTH_JWKS_URL:
        logger.warning("AUTH_USERS is ignored while AUTH_JWKS_URL is set: tokens come from the identity provider")
    # LLM-written analysis code must not run inside the API process once real users are signed in
    if not settings.SANDBOX_URL or len(settings.SANDBOX_SECRET) < _MIN_SANDBOX_SECRET_CHARS:
        raise RuntimeError(f"AUTH_MODE=jwt needs SANDBOX_URL and a SANDBOX_SECRET of at least {_MIN_SANDBOX_SECRET_CHARS} characters (analysis code would run inside the API process)")


def _decode(token: str) -> dict[str, Any]:
    audience = settings.AUTH_JWT_AUDIENCE or None
    if settings.AUTH_JWKS_URL:
        global _jwks_client
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(settings.AUTH_JWKS_URL, cache_keys=True)
        key: Any = _jwks_client.get_signing_key_from_jwt(token).key
        algorithms = _ASYMMETRIC_ALGORITHMS  # never accept HS256 with a public key as the secret
    else:
        key, algorithms = settings.AUTH_JWT_SECRET, ["HS256"]
    return jwt.decode(
        token,
        key,
        algorithms=algorithms,
        audience=audience,
        issuer=settings.AUTH_JWT_ISSUER or None,
        options={"require": ["exp", "sub"], "verify_aud": audience is not None},
    )


def _principal_from_claims(claims: dict[str, Any]) -> Principal:
    roles = claims.get(settings.AUTH_ROLES_CLAIM) or []
    return Principal(
        user_id=str(claims["sub"]),
        tenant_id=str(claims.get(settings.AUTH_TENANT_CLAIM) or settings.RLS_TENANT_ID),
        department_id=str(claims.get(settings.AUTH_DEPARTMENT_CLAIM) or settings.RLS_DEPARTMENT_ID),
        roles=frozenset(str(r) for r in ([roles] if isinstance(roles, str) else roles)),
        authenticated=True,
        display_name=str(claims.get("name") or "")[:64],
        token_id=str(claims.get("jti") or ""),
        token_exp=int(claims.get("exp") or 0),
    )


# ---------------------------------------------------------------------------
# Built-in sign-in (the browser login screen): users from AUTH_USERS, scrypt password hashes, HS256 tokens
# ---------------------------------------------------------------------------

_SCRYPT_R, _SCRYPT_P = 8, 2
_SCRYPT_MAXMEM = 256 * 1024 * 1024  # hashlib's default (32 MiB) is below what N=2**16 needs
_SCRYPT_MAX_LOG2_N = 20  # a stored hash asking for more than this is refused, not computed


def _scrypt_n() -> int:
    return 1 << settings.AUTH_SCRYPT_LOG2_N
_DUMMY_HASH: str = ""  # verified against when the user is unknown, so a miss costs as much as a wrong password (no user enumeration)


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """``scrypt$N$r$p$<salt hex>$<hash hex>``: the format stored in ``AUTH_USERS[].password_hash``."""
    salt = salt or secrets.token_bytes(16)
    n = _scrypt_n()
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32, maxmem=_SCRYPT_MAXMEM)
    return f"scrypt${n}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a ``hash_password`` string; ``False`` for any malformed value."""
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        if int(n) > (1 << _SCRYPT_MAX_LOG2_N):
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2, maxmem=_SCRYPT_MAXMEM)
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def needs_rehash(stored: str) -> bool:
    """Was this hash made with a lower cost than today's setting? (it is then replaced after a successful sign-in)"""
    try:
        _, n, r, p, _, _ = stored.split("$")
        return int(n) < _scrypt_n() or int(r) < _SCRYPT_R or int(p) < _SCRYPT_P
    except ValueError:
        return False


def login_enabled() -> bool:
    """The built-in login works with a shared HS256 secret and a user list (not with an external identity provider)."""
    return settings.AUTH_MODE == "jwt" and not settings.AUTH_JWKS_URL and (bool(settings.AUTH_USERS) or settings.AUTH_ALLOW_REGISTRATION)


def registration_enabled() -> bool:
    """Self-service sign-up needs the built-in sign-in and the explicit ``AUTH_ALLOW_REGISTRATION`` switch."""
    return settings.AUTH_MODE == "jwt" and not settings.AUTH_JWKS_URL and settings.AUTH_ALLOW_REGISTRATION


def verify_user_row(password: str, user: Optional[dict[str, Any]]) -> bool:
    """Password check against a stored account, or against a dummy hash when there is none (a miss costs as much as a wrong password)."""
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH = hash_password("not-a-real-password")
    ok = verify_password(password, str(user.get("password_hash", "")) if user else _DUMMY_HASH)
    return bool(user) and ok


def new_recovery_key() -> str:
    """24 hex characters in groups of four (96 bits): shown to the user once, only its scrypt hash is stored."""
    raw = secrets.token_hex(12)
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def _normalize_recovery_key(key: str) -> str:
    return "".join(c for c in key.lower() if c in "0123456789abcdef")  # case, dashes and spaces do not matter when it is typed back


def hash_recovery_key(key: str) -> str:
    return hash_password(_normalize_recovery_key(key))


def verify_recovery_key(key: str, user: Optional[dict[str, Any]]) -> bool:
    """Does ``key`` match the account's recovery key? A miss (no account, no key set, wrong key) costs the same scrypt."""
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH = hash_password("not-a-real-password")
    stored = str((user or {}).get("recovery_hash") or "")
    ok = verify_password(_normalize_recovery_key(key), stored or _DUMMY_HASH)
    return bool(stored) and ok


def authenticate_user(username: str, password: str) -> Optional[dict[str, Any]]:
    """The ``AUTH_USERS`` entry for these credentials, or ``None``. Always costs one scrypt, found or not."""
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH = hash_password("not-a-real-password")
    user = next((u for u in settings.AUTH_USERS if hmac.compare_digest(str(u.get("username", "")), username)), None)
    ok = verify_password(password, str(user.get("password_hash", "")) if user else _DUMMY_HASH)
    return user if (user and ok) else None


def issue_login_token(user: dict[str, Any]) -> tuple[str, int]:
    """``(JWT, seconds until it expires)`` for a user that passed ``authenticate_user``; carries the same claims ``authenticate`` reads."""
    ttl = settings.AUTH_TOKEN_TTL_MINUTES * 60
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(user["username"]),
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_urlsafe(12),  # lets a sign-out revoke exactly this token
        settings.AUTH_TENANT_CLAIM: str(user.get("tenant_id") or settings.RLS_TENANT_ID),
        settings.AUTH_DEPARTMENT_CLAIM: str(user.get("department_id") or settings.RLS_DEPARTMENT_ID),
        settings.AUTH_ROLES_CLAIM: list(user.get("roles") or []),
    }
    if user.get("display_name"):
        claims["name"] = str(user["display_name"])[:64]
    if settings.AUTH_JWT_AUDIENCE:
        claims["aud"] = settings.AUTH_JWT_AUDIENCE
    if settings.AUTH_JWT_ISSUER:
        claims["iss"] = settings.AUTH_JWT_ISSUER
    return jwt.encode(claims, settings.AUTH_JWT_SECRET, algorithm="HS256"), ttl


# ---------------------------------------------------------------------------
# Revocation: tokens are stateless, so "signed out" and "password changed" are remembered in Redis for as long as a token could
# still be valid. Two kinds of entry: one token (``jti``, sign-out) and everything issued to a user before a moment (password
# change or reset). If Redis cannot be asked the token is accepted (fail open, like the rate limiter: Redis down must not lock
# everybody out); the token's own expiry still applies.
# ---------------------------------------------------------------------------

_REVOKED_KEY = "authrevoked:"
_VALID_AFTER_KEY = "authvalid:"


async def revoke_token(redis_client: Any, principal: Principal) -> bool:
    """Make this one token unusable from now on (sign-out). ``False`` when there was nothing to revoke or Redis failed."""
    client = getattr(redis_client, "client", None)
    if client is None or not principal.token_id:
        return False
    try:
        await client.set(_REVOKED_KEY + principal.token_id, "1", ex=max(principal.token_exp - int(time.time()), 1) + 5)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not revoke a token: %s", exc or type(exc).__name__)
        return False


async def revoke_user_sessions(redis_client: Any, user_id: str) -> bool:
    """Every token issued to ``user_id`` before now stops working (a password change or reset); tokens issued afterwards do."""
    client = getattr(redis_client, "client", None)
    if client is None:
        return False
    try:
        await client.set(_VALID_AFTER_KEY + user_id, str(int(time.time())), ex=settings.AUTH_TOKEN_TTL_MINUTES * 60 + 60)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not revoke the sessions of %s: %s", user_id, exc or type(exc).__name__)
        return False


async def _is_revoked(redis_client: Any, claims: dict[str, Any]) -> bool:
    client = getattr(redis_client, "client", None)
    if client is None:
        return False
    jti = str(claims.get("jti") or "")
    keys = [_VALID_AFTER_KEY + str(claims["sub"])] + ([_REVOKED_KEY + jti] if jti else [])
    try:
        values = await client.mget(keys)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Revocation list unavailable, the token is accepted: %s", exc or type(exc).__name__)
        return False
    if len(values) > 1 and values[1]:
        return True
    return bool(values[0]) and int(claims.get("iat") or 0) < int(values[0])


async def authenticate(request: Request) -> Principal:
    """FastAPI dependency for every protected route."""
    if settings.AUTH_MODE != "jwt":
        principal = Principal("anonymous", settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID, frozenset({"admin"}), authenticated=False)
    else:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail=msg("auth.missing"), headers={"WWW-Authenticate": "Bearer"})
        try:
            claims = _decode(token.strip())
        except jwt.PyJWTError as exc:
            logger.info("Rejected token: %s", type(exc).__name__)
            raise HTTPException(status_code=401, detail=msg("auth.invalid"), headers={"WWW-Authenticate": "Bearer"}) from exc
        if await _is_revoked(getattr(request.app.state, "redis_client", None), claims):
            logger.info("Rejected a revoked token (signed out, or the password changed since)")
            raise HTTPException(status_code=401, detail=msg("auth.invalid"), headers={"WWW-Authenticate": "Bearer"})
        principal = _principal_from_claims(claims)
    _current.set(principal)
    return principal
