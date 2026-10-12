"""Single sign-on routes (``/api/auth/oidc``): the browser is sent to the identity provider and comes back with a one-time code.

``GET /login`` answers with the provider URL (the frontend route redirects the browser there); ``POST /callback`` is called by the
frontend route the provider redirects to: it spends the single-use ``state``, exchanges the code, verifies the ``id_token`` and returns
the gateway's own token, which the frontend keeps in its httpOnly cookie exactly like a password sign-in.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.config import settings
from src.shared import audit, oidc
from src.shared.auth import Principal, issue_login_token
from src.shared.logger import get_logger
from src.shared.messages import msg
from src.shared.rate_limit import enforce as enforce_rate_limit
from src.shared.user_store import upsert_sso_user

logger: logging.Logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth/oidc", tags=["sso"])
_STATE_KEY = "oidc:state:"


class CallbackIn(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=200)


def _guest() -> Principal:
    return Principal("anonymous", settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID)


@router.get("/login", summary="Where to send the browser to sign in at the identity provider")
async def login(request: Request) -> dict[str, str]:
    if not oidc.sso_enabled():
        raise HTTPException(status_code=404, detail=msg("sso.disabled"))
    redis = request.app.state.redis_client
    await enforce_rate_limit(redis, _guest(), request, "login", settings.RATE_LIMIT_LOGIN_PER_MINUTE)
    try:
        meta = await oidc.discovery()
    except Exception as exc:  # noqa: BLE001 - the provider being unreachable is a 502, not a crash
        logger.warning("OIDC discovery failed: %s", exc or type(exc).__name__)
        raise HTTPException(status_code=502, detail=msg("sso.exchange_failed")) from exc
    state, nonce, verifier = oidc.new_login()
    await redis.set_value(_STATE_KEY + state, json.dumps({"nonce": nonce, "verifier": verifier}), ttl=oidc.STATE_TTL_SECONDS)
    return {"url": oidc.authorize_url(meta, state, nonce, verifier)}


@router.post("/callback", summary="Finish the sign-in: spend the state, exchange the code, return the gateway's token")
async def callback(body: CallbackIn, request: Request) -> dict[str, Any]:
    if not oidc.sso_enabled():
        raise HTTPException(status_code=404, detail=msg("sso.disabled"))
    redis = request.app.state.redis_client
    await enforce_rate_limit(redis, _guest(), request, "login", settings.RATE_LIMIT_LOGIN_PER_MINUTE)
    raw = await redis.take_value(_STATE_KEY + body.state)  # single use: a replayed callback finds nothing
    if not raw:
        raise HTTPException(status_code=400, detail=msg("sso.bad_state"))
    pending = json.loads(raw)
    try:
        meta = await oidc.discovery()
        tokens = await oidc.exchange_code(meta, body.code, pending["verifier"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("OIDC code exchange failed: %s", exc or type(exc).__name__)
        raise HTTPException(status_code=502, detail=msg("sso.exchange_failed")) from exc
    try:
        claims = await oidc.verify_id_token(str(tokens.get("id_token", "")), meta, pending["nonce"])
    except (jwt.InvalidTokenError, KeyError) as exc:
        logger.warning("OIDC id_token refused: %s", exc)
        raise HTTPException(status_code=401, detail=msg("sso.invalid_token")) from exc
    pg = getattr(request.app.state, "pg_client", None)
    if pg is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    name = oidc.account_name(claims)
    display = str(claims.get("name") or claims.get("preferred_username") or claims.get("email") or "")
    user = await upsert_sso_user(pg, name, display, settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID)
    if user is None:
        raise HTTPException(status_code=409, detail=msg("sso.conflict"))
    if user["disabled"]:
        raise HTTPException(status_code=403, detail=msg("sso.locked"))
    token, expires_in = issue_login_token(user)
    await audit.record("auth.sso_login", user["username"], principal=Principal(user["username"], user["tenant_id"], user["department_id"], authenticated=True))
    logger.info("SSO sign-in: user=%s tenant=%s", user["username"], user["tenant_id"])
    return {"access_token": token, "expires_in": expires_in}
