"""Self-service sign-up: off by default, no roles for new accounts, one account per username, usable at the next sign-in."""
import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.config import settings
from src.shared import auth
from src.shared.auth import hash_password

SECRET = "x" * 40


class FakePG:
    """The two statements user_store sends, over a dict."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def fetch(self, sql, *args, **kw):
        if sql.startswith("INSERT"):
            username, display_name, password_hash, recovery_hash, tenant, dept = args
            if username in self.rows:
                return []
            self.rows[username] = {"username": username, "display_name": display_name, "password_hash": password_hash,
                                   "recovery_hash": recovery_hash, "roles": [], "tenant_id": tenant, "department_id": dept}
            return [{"username": username}]
        if sql.startswith("UPDATE"):
            username, password_hash, *rest = args
            if username not in self.rows:
                return []
            self.rows[username]["password_hash"] = password_hash
            if rest:
                self.rows[username]["recovery_hash"] = rest[0]
            return [{"username": username}]
        return [self.rows[args[0]]] if args[0] in self.rows else []


@pytest.fixture
def gateway(monkeypatch):
    from src.gateway import main

    for key, value in {"AUTH_MODE": "jwt", "AUTH_JWT_SECRET": SECRET, "AUTH_JWKS_URL": "", "AUTH_ALLOW_REGISTRATION": True,
                       "AUTH_USERS": [{"username": "admin", "password_hash": hash_password("admin password 123"), "roles": ["admin"]}]}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(main, "redis_client", None)
    monkeypatch.setattr(main, "pg_client", FakePG())
    return main


def request():
    return SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"), headers={})


def sign_up(main, username="Carol", password="a long enough password", name=" Carol C. "):
    return asyncio.run(main.register(main.RegisterRequest(username=username, password=password, display_name=name), request()))


def sign_in(main, username, password):
    return asyncio.run(main.login(main.LoginRequest(username=username, password=password), request()))


def test_sign_up_is_off_unless_the_switch_is_on(gateway, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOW_REGISTRATION", False)
    with pytest.raises(gateway.HTTPException) as off:
        sign_up(gateway)
    assert off.value.status_code == 404 and not auth.registration_enabled()


def test_a_new_account_gets_a_token_a_name_and_no_roles(gateway):
    response = sign_up(gateway)
    assert response.user["user"] == "carol" and response.user["name"] == "Carol C."
    assert response.user["roles"] == [] and not response.user["can_manage_knowledge"] and not response.user["can_approve"]
    claims = auth._decode(response.access_token)
    assert claims["sub"] == "carol" and claims["name"] == "Carol C." and claims[settings.AUTH_ROLES_CLAIM] == []


def test_the_new_account_can_sign_in_later_and_a_wrong_password_cannot(gateway):
    sign_up(gateway)
    assert sign_in(gateway, "CAROL", "a long enough password").user["user"] == "carol"
    with pytest.raises(gateway.HTTPException) as refused:
        sign_in(gateway, "carol", "not the password")
    assert refused.value.status_code == 401


def test_a_username_is_taken_once_also_against_the_administrator_list(gateway):
    sign_up(gateway)
    for taken in ("carol", "CAROL", "Admin"):
        with pytest.raises(gateway.HTTPException) as exc:
            sign_up(gateway, username=taken)
        assert exc.value.status_code == 409


def test_roles_cannot_be_asked_for_and_weak_input_is_refused(gateway):
    assert "roles" not in gateway.RegisterRequest.model_fields
    for bad in ({"username": "ab", "password": "a long enough password"}, {"username": "ok name", "password": "a long enough password"},
                {"username": "carol", "password": "short"}):
        with pytest.raises(ValidationError):
            gateway.RegisterRequest(**bad)


def test_the_sign_in_screen_learns_what_it_may_offer(gateway):
    assert asyncio.run(gateway.auth_config()) == {"login_enabled": True, "registration_enabled": True}


# ------------------------------------------------------------------ recovery key, reset and change of the password
def reset(main, username, key, new_password="a brand new password"):
    return asyncio.run(main.reset_password(main.ResetPasswordRequest(username=username, recovery_key=key, new_password=new_password), request()))


def change(main, principal, current, new):
    return asyncio.run(main.change_password(main.ChangePasswordRequest(current_password=current, new_password=new), request(), principal))


def test_sign_up_shows_a_recovery_key_once_and_stores_only_its_hash(gateway):
    response = sign_up(gateway)
    key = response.recovery_key
    assert key and len(key.replace("-", "")) == 24
    stored = gateway.pg_client.rows["carol"]["recovery_hash"]
    assert stored.startswith("scrypt$") and key not in stored and key.replace("-", "") not in stored
    assert sign_in(gateway, "carol", "a long enough password").recovery_key is None  # a sign-in never repeats it


def test_the_recovery_key_resets_the_password_once_and_hands_out_a_new_key(gateway):
    key = sign_up(gateway).recovery_key
    done = reset(gateway, "Carol", key.upper().replace("-", " "))  # typed back in another case and without dashes
    assert done.user["user"] == "carol" and done.recovery_key and done.recovery_key != key
    assert sign_in(gateway, "carol", "a brand new password").user["user"] == "carol"
    with pytest.raises(gateway.HTTPException):
        sign_in(gateway, "carol", "a long enough password")  # the old password is gone
    with pytest.raises(gateway.HTTPException) as spent:
        reset(gateway, "carol", key)  # the old key is spent
    assert spent.value.status_code == 400


def test_a_wrong_key_and_an_unknown_user_get_the_same_answer(gateway):
    sign_up(gateway)
    wrong = pytest.raises(gateway.HTTPException, reset, gateway, "carol", "0000-0000-0000-0000-0000-0000")
    unknown = pytest.raises(gateway.HTTPException, reset, gateway, "nobody", "0000-0000-0000-0000-0000-0000")
    assert wrong.value.status_code == unknown.value.status_code == 400 and wrong.value.detail == unknown.value.detail


def test_reset_is_off_with_the_switch_off(gateway, monkeypatch):
    key = sign_up(gateway).recovery_key
    monkeypatch.setattr(settings, "AUTH_ALLOW_REGISTRATION", False)
    with pytest.raises(gateway.HTTPException) as off:
        reset(gateway, "carol", key)
    assert off.value.status_code == 404


def test_change_password_needs_the_current_one_and_the_new_one_works_afterwards(gateway):
    sign_up(gateway)
    carol = gateway.Principal("carol", settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID, frozenset(), authenticated=True)
    with pytest.raises(gateway.HTTPException) as wrong:
        change(gateway, carol, "not my password", "another long password")
    assert wrong.value.status_code == 400
    with pytest.raises(gateway.HTTPException):
        change(gateway, carol, "a long enough password", "a long enough password")  # the same password again
    changed = change(gateway, carol, "a long enough password", "another long password")
    assert changed["ok"] and changed["access_token"]  # a fresh token: this session carries on, the older ones are revoked
    assert sign_in(gateway, "carol", "another long password").user["user"] == "carol"
    with pytest.raises(gateway.HTTPException):
        sign_in(gateway, "carol", "a long enough password")


def test_an_administrator_account_cannot_change_its_password_here(gateway):
    admin = gateway.Principal("admin", settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID, frozenset({"admin"}), authenticated=True)
    with pytest.raises(gateway.HTTPException) as managed:
        change(gateway, admin, "admin password 123", "a brand new password")
    assert managed.value.status_code == 400
