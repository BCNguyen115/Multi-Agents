"""Built-in sign-in: password hashing, the token it issues, and the /api/auth routes."""
import asyncio
from types import SimpleNamespace

import jwt
import pytest

from src.config import settings
from src.shared import auth
from src.shared.auth import authenticate_user, hash_password, issue_login_token, login_enabled, validate_auth_config, verify_password

SECRET = "x" * 40


@pytest.fixture
def users(monkeypatch):
    entries = [
        {"username": "alice", "password_hash": hash_password("correct horse battery"), "roles": ["admin"], "tenant_id": "acme", "department_id": "legal"},
        {"username": "bob", "password_hash": hash_password("another long password"), "roles": []},
    ]
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
    monkeypatch.setattr(settings, "SANDBOX_URL", "http://python-sandbox:8000")
    monkeypatch.setattr(settings, "SANDBOX_SECRET", "a-sandbox-secret-0123456789")
    monkeypatch.setattr(settings, "AUTH_USERS", entries)
    return entries


def test_password_hashes_are_salted_and_verified_in_constant_time_form():
    first, second = hash_password("s3cret-password"), hash_password("s3cret-password")
    assert first != second and first.startswith("scrypt$")  # a fresh salt each time
    assert verify_password("s3cret-password", first) and verify_password("s3cret-password", second)
    assert not verify_password("S3cret-password", first)


@pytest.mark.parametrize("stored", ["", "plaintext", "scrypt$1$2", "bcrypt$1$2$3$ab$cd", "scrypt$x$8$1$zz$zz", "scrypt$16384$8$1$00$"])
def test_malformed_stored_hashes_never_verify_and_never_raise(stored):
    assert verify_password("anything", stored) is False


def test_only_the_right_user_with_the_right_password_gets_in(users):
    assert authenticate_user("alice", "correct horse battery")["username"] == "alice"
    assert authenticate_user("alice", "wrong") is None
    assert authenticate_user("bob", "correct horse battery") is None  # someone else's password
    assert authenticate_user("mallory", "correct horse battery") is None
    assert authenticate_user("", "") is None


def test_issued_token_is_accepted_by_the_same_checks_every_api_call_uses(users):
    token, ttl = issue_login_token(users[0])
    assert ttl == settings.AUTH_TOKEN_TTL_MINUTES * 60
    principal = auth._principal_from_claims(auth._decode(token))
    assert (principal.user_id, principal.tenant_id, principal.department_id) == ("alice", "acme", "legal")
    assert principal.roles == {"admin"} and principal.authenticated and principal.can_approve and principal.can_manage_knowledge
    bob, _ = issue_login_token(users[1])
    plain = auth._principal_from_claims(auth._decode(bob))
    assert plain.tenant_id == settings.RLS_TENANT_ID and not plain.can_approve and not plain.can_manage_knowledge


def test_tokens_expire(users, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_TOKEN_TTL_MINUTES", -1)
    token, _ = issue_login_token(users[0])
    with pytest.raises(jwt.ExpiredSignatureError):
        auth._decode(token)


def test_login_needs_jwt_mode_a_shared_secret_and_users(users, monkeypatch):
    assert login_enabled()
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "https://idp.example/jwks")
    assert not login_enabled()  # tokens then come from the identity provider
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
    monkeypatch.setattr(settings, "AUTH_MODE", "off")
    assert not login_enabled()
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_USERS", [])
    assert not login_enabled()


def test_startup_refuses_a_user_list_with_plain_text_passwords(users, monkeypatch):
    validate_auth_config()
    monkeypatch.setattr(settings, "AUTH_USERS", [{"username": "eve", "password_hash": "hunter2"}])
    with pytest.raises(RuntimeError, match="make_user"):
        validate_auth_config()


# ------------------------------------------------------------------ routes
@pytest.fixture
def gateway(monkeypatch, users):
    from src.gateway import main

    monkeypatch.setattr(main, "redis_client", None)  # rate limiting fails open without Redis
    return main


def request():
    return SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"), headers={})


def sign_in(main, username, password):
    return asyncio.run(main.login(main.LoginRequest(username=username, password=password), request()))


def test_login_route_returns_a_working_token_and_who_it_is_for(gateway):
    response = sign_in(gateway, "alice", "correct horse battery")
    assert response.token_type == "bearer" and response.expires_in > 0
    assert response.user["user"] == "alice" and response.user["roles"] == ["admin"] and response.user["can_manage_knowledge"]
    assert "password" not in str(response.user)
    assert auth._decode(response.access_token)["sub"] == "alice"


def test_login_route_gives_the_same_answer_for_a_wrong_password_and_an_unknown_user(gateway):
    wrong = pytest.raises(gateway.HTTPException, sign_in, gateway, "alice", "nope")
    unknown = pytest.raises(gateway.HTTPException, sign_in, gateway, "nobody", "nope")
    assert wrong.value.status_code == unknown.value.status_code == 401
    assert wrong.value.detail == unknown.value.detail  # no hint about which usernames exist


def test_login_route_is_off_without_a_user_list(gateway, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_USERS", [])
    with pytest.raises(gateway.HTTPException) as off:
        sign_in(gateway, "alice", "correct horse battery")
    assert off.value.status_code == 404


def test_whoami_describes_the_caller(gateway):
    caller = gateway.Principal("amy", "acme", "legal", frozenset({"approver"}), authenticated=True)
    me = asyncio.run(gateway.whoami(caller))
    assert me["authenticated"] and me["user"] == "amy" and me["can_approve"] and not me["can_manage_knowledge"]
