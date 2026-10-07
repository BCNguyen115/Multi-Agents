"""Gateway authentication: bearer JWT verification, per-user sessions, approver roles, unsafe-config refusal, upload cap."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.config import settings
from src.shared.auth import Principal, authenticate, current_scope, validate_auth_config

SECRET = "0123456789abcdef0123456789abcdef-test-secret"


def token(secret=SECRET, alg="HS256", **claims):
    base = {"sub": "alice", "exp": int(time.time()) + 300, "tenant_id": "acme", "department_id": "legal", "roles": ["analyst"]}
    return jwt.encode({**base, **claims}, secret, algorithm=alg)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
    monkeypatch.setattr(settings, "AUTH_JWT_AUDIENCE", "")
    monkeypatch.setattr(settings, "AUTH_JWT_ISSUER", "")
    app = FastAPI()

    @app.get("/who")
    async def who(principal: Principal = Depends(authenticate)):
        tenant, dept = current_scope()
        return {"user": principal.user_id, "session": principal.session("s1"), "scope": [tenant, dept],
                "approve": principal.can_approve, "authenticated": principal.authenticated}

    return TestClient(app)


def get(client, tok=None, **headers):
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return client.get("/who", headers=headers)


# ---------------------------------------------------------------- off mode
def test_authentication_off_keeps_the_single_anonymous_user(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "off")
    app = FastAPI()

    @app.get("/who")
    async def who(principal: Principal = Depends(authenticate)):
        return {"session": principal.session("s1"), "approve": principal.can_approve, "scope": list(current_scope())}

    body = TestClient(app).get("/who").json()
    assert body == {"session": "s1", "approve": True, "scope": [settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID]}


# ---------------------------------------------------------------- jwt mode
def test_a_valid_token_identifies_the_user_and_scopes_the_session_and_sql(client):
    body = get(client, token()).json()
    assert body["user"] == "alice" and body["session"] == "alice:s1" and body["scope"] == ["acme", "legal"] and body["authenticated"]


def test_two_users_with_the_same_client_session_id_get_different_sessions(client):
    assert get(client, token(sub="alice")).json()["session"] != get(client, token(sub="bob")).json()["session"]


@pytest.mark.parametrize("bad", [
    None,                                                     # no header
    "garbage",
    token(secret="another-secret-of-similar-length-000000"),  # wrong signature
    token(exp=int(time.time()) - 10),                         # expired
])
def test_missing_bad_or_expired_tokens_are_refused(client, bad):
    response = get(client, bad)
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"


def test_a_token_without_subject_or_expiry_is_refused(client):
    no_sub = jwt.encode({"exp": int(time.time()) + 300}, SECRET, algorithm="HS256")
    no_exp = jwt.encode({"sub": "alice"}, SECRET, algorithm="HS256")
    assert get(client, no_sub).status_code == 401 and get(client, no_exp).status_code == 401


def test_an_unsigned_token_is_refused(client):
    unsigned = jwt.encode({"sub": "alice", "exp": int(time.time()) + 300}, key=None, algorithm="none")
    assert get(client, unsigned).status_code == 401


def test_only_the_configured_algorithm_is_accepted(client):
    hs512 = token(alg="HS512")
    assert get(client, hs512).status_code == 401


def test_audience_and_issuer_are_verified_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_JWT_AUDIENCE", "agents-api")
    monkeypatch.setattr(settings, "AUTH_JWT_ISSUER", "https://idp.example")
    assert get(client, token(aud="agents-api", iss="https://idp.example")).status_code == 200
    assert get(client, token(aud="other", iss="https://idp.example")).status_code == 401
    assert get(client, token(aud="agents-api", iss="https://evil")).status_code == 401


def test_only_approver_roles_may_approve(client):
    assert get(client, token(roles=["analyst"])).json()["approve"] is False
    assert get(client, token(roles=["approver"])).json()["approve"] is True
    assert get(client, token(roles="admin")).json()["approve"] is True  # a single role given as a string


# ---------------------------------------------------------------- refusing an unsafe configuration
@pytest.mark.parametrize("secret", ["", "short", "your-secret-key-change-me-0123456789abcdef0123"])
def test_jwt_mode_will_not_start_with_a_missing_weak_or_placeholder_secret(monkeypatch, secret):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", secret)
    with pytest.raises(RuntimeError):
        validate_auth_config()


def test_jwt_mode_will_not_start_with_the_placeholder_internal_secret(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "INTERNAL_JWT_SECRET", "your-enterprise-secret-key-change-me")
    with pytest.raises(RuntimeError, match="INTERNAL_JWT_SECRET"):
        validate_auth_config()


@pytest.mark.parametrize("url, secret", [("", "a-sandbox-secret-0123456789"), ("http://python-sandbox:8000", ""), ("http://python-sandbox:8000", "short")])
def test_jwt_mode_will_not_start_without_the_analysis_sandbox(monkeypatch, url, secret):
    monkeypatch.setattr(settings, "INTERNAL_JWT_SECRET", "a-real-internal-secret-value-0123456789")
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "SANDBOX_URL", url)
    monkeypatch.setattr(settings, "SANDBOX_SECRET", secret)
    with pytest.raises(RuntimeError, match="SANDBOX"):
        validate_auth_config()


def test_valid_and_off_configurations_start(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_JWT_SECRET", "a-real-internal-secret-value-0123456789")
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "SANDBOX_URL", "http://python-sandbox:8000")
    monkeypatch.setattr(settings, "SANDBOX_SECRET", "a-sandbox-secret-0123456789")
    validate_auth_config()
    monkeypatch.setattr(settings, "AUTH_MODE", "off")
    validate_auth_config()
    monkeypatch.setattr(settings, "AUTH_MODE", "maybe")
    with pytest.raises(RuntimeError):
        validate_auth_config()


# ---------------------------------------------------------------- the real gateway
def test_the_approve_route_checks_the_role_and_uses_the_users_own_session(monkeypatch):
    from fastapi import HTTPException

    from src.gateway import main

    fake = MagicMock()
    fake.handle_approval_decision = AsyncMock(return_value={"status": "success", "response": "done"})
    monkeypatch.setattr(main, "orchestrator", fake)
    request = main.ApprovalDecisionRequest(session_id="s1", action_id="act_1", decision="approve")
    from src.shared import audit

    audit.configure(MagicMock(execute=AsyncMock()))  # an approval needs its decision row first (see tests/test_audit.py)
    monkeypatch.setattr(audit, "_pg", audit._pg)  # restored by monkeypatch after the test

    analyst = Principal("alice", "acme", "legal", frozenset({"analyst"}), authenticated=True)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(main.chat_approve(request, analyst))
    assert refused.value.status_code == 403 and not fake.handle_approval_decision.await_count

    approver = Principal("carol", "acme", "legal", frozenset({"approver"}), authenticated=True)
    asyncio.run(main.chat_approve(request, approver))
    assert fake.handle_approval_decision.await_args.kwargs["session_id"] == "carol:s1"  # cannot approve alice's action


def test_an_oversized_upload_is_refused_from_the_header_before_the_body_is_read(monkeypatch):
    from src.gateway import main

    monkeypatch.setattr(settings, "DATA_MAX_FILE_MB", 1)
    passed = []

    async def call_next(request):
        passed.append(request)
        return "passed"

    def request(path, length):
        return MagicMock(url=MagicMock(path=path), headers={"content-length": str(length)})

    refused = asyncio.run(main.reject_oversized_uploads(request("/api/analyze", 5 * 1024 * 1024), call_next))
    assert refused.status_code == 413 and not passed
    assert asyncio.run(main.reject_oversized_uploads(request("/api/analyze", 900 * 1024), call_next)) == "passed"  # under the limit
    assert asyncio.run(main.reject_oversized_uploads(request("/api/chat", 50 * 1024 * 1024), call_next)) == "passed"  # other routes are not upload routes
