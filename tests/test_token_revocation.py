"""Sign-out and a password change revoke tokens: stateless JWTs, remembered in Redis for as long as they could still be valid."""
import asyncio
import time
from types import SimpleNamespace

import jwt
import pytest

from src.config import settings
from src.shared import auth
from tests.test_registration import gateway, sign_up  # noqa: F401  (fixture reused)


class FakeRedis:
    def __init__(self):
        self.client, self.store, self.down = self, {}, False

    async def set(self, key, value, ex=None):
        if self.down:
            raise ConnectionError("redis down")
        self.store[key] = value

    async def mget(self, keys):
        if self.down:
            raise ConnectionError("redis down")
        return [self.store.get(k) for k in keys]


def call(token, redis):
    request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"}, app=SimpleNamespace(state=SimpleNamespace(redis_client=redis)))
    return asyncio.run(auth.authenticate(request))


def token_for(user="carol", **extra):
    now = int(time.time())
    claims = {"sub": user, "iat": now, "exp": now + 600, **extra}
    return jwt.encode(claims, settings.AUTH_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def world(gateway, monkeypatch):  # noqa: F811
    fake = FakeRedis()
    monkeypatch.setattr(gateway, "redis_client", fake)
    return gateway, fake


def test_every_sign_in_token_carries_its_own_id(world):
    main, _ = world
    first, _ = auth.issue_login_token({"username": "carol"})
    second, _ = auth.issue_login_token({"username": "carol"})
    ids = {jwt.decode(t, settings.AUTH_JWT_SECRET, algorithms=["HS256"])["jti"] for t in (first, second)}
    assert len(ids) == 2


def test_signing_out_revokes_that_token_and_only_that_one(world):
    main, fake = world
    mine, other = auth.issue_login_token({"username": "carol"})[0], auth.issue_login_token({"username": "carol"})[0]
    principal = call(mine, fake)
    assert principal.token_id
    assert asyncio.run(main.logout(principal)) == {"ok": True}
    with pytest.raises(main.HTTPException) as refused:
        call(mine, fake)
    assert refused.value.status_code == 401
    assert call(other, fake).user_id == "carol"  # a second device stays signed in


def test_a_password_change_ends_every_older_session_but_not_the_new_one(world):
    main, fake = world
    sign_up(main)
    old = token_for("carol", iat=int(time.time()) - 30)
    assert call(old, fake).user_id == "carol"
    carol = main.Principal("carol", settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID, frozenset(), authenticated=True)
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"), headers={})
    done = asyncio.run(main.change_password(main.ChangePasswordRequest(current_password="a long enough password", new_password="another long password"), request, carol))
    assert done["ok"] and done["access_token"]
    with pytest.raises(main.HTTPException) as refused:
        call(old, fake)
    assert refused.value.status_code == 401
    assert call(done["access_token"], fake).user_id == "carol"  # the caller keeps working with the fresh token


def test_one_users_revocation_does_not_touch_another(world):
    main, fake = world
    asyncio.run(auth.revoke_user_sessions(fake, "carol"))
    stale = token_for("carol", iat=int(time.time()) - 30)
    with pytest.raises(main.HTTPException):
        call(stale, fake)
    assert call(token_for("dave", iat=int(time.time()) - 30), fake).user_id == "dave"


def test_when_redis_cannot_be_asked_the_token_is_accepted(world):
    main, fake = world
    fake.down = True
    assert call(token_for("carol"), fake).user_id == "carol"
    assert asyncio.run(auth.revoke_user_sessions(fake, "carol")) is False  # reported, not raised


def test_a_token_without_an_id_works_and_cannot_be_revoked_one_by_one(world):
    main, fake = world
    principal = call(token_for("carol"), fake)  # what an identity provider's token may look like
    assert principal.token_id == ""
    assert asyncio.run(auth.revoke_token(fake, principal)) is False


def test_without_a_redis_client_nothing_is_checked(world):
    main, _ = world
    assert call(token_for("carol"), None).user_id == "carol"
