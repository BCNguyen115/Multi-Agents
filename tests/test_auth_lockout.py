"""Wrong credentials are counted per ACCOUNT (the client IP may be shared by everybody behind the frontend)."""
import asyncio

import pytest

from src.config import settings
from src.shared import rate_limit
from tests.test_registration import gateway, request, sign_in  # noqa: F401  (fixture reused)

ADMIN, GOOD, BAD = "admin", "admin password 123", "not the password"


class FakeRedis:
    """What rate_limit uses: get / ttl / delete and a pipeline with incr + expire(nx)."""

    def __init__(self):
        self.client, self.counts, self.ttls, self.down = self, {}, {}, False

    def _check(self):
        if self.down:
            raise ConnectionError("redis down")

    async def get(self, key):
        self._check()
        return self.counts.get(key)

    async def ttl(self, key):
        self._check()
        return self.ttls.get(key, -1)

    async def delete(self, key):
        self._check()
        self.counts.pop(key, None)

    def pipeline(self):
        redis, ops = self, []

        class Pipe:
            def incr(self, key):
                ops.append(("incr", key))

            def expire(self, key, seconds, nx=False):
                ops.append(("expire", key, seconds, nx))

            async def execute(self):
                redis._check()
                for op in ops:
                    if op[0] == "incr":
                        redis.counts[op[1]] = redis.counts.get(op[1], 0) + 1
                    elif not (op[3] and op[1] in redis.ttls):
                        redis.ttls[op[1]] = op[2]

        return Pipe()


@pytest.fixture
def locked_gateway(gateway, monkeypatch):  # noqa: F811
    monkeypatch.setattr(gateway, "redis_client", FakeRedis())
    monkeypatch.setattr(settings, "AUTH_MAX_FAILURES", 3)
    rate_limit._failures_local.clear()
    return gateway


def attempt(main, username, password):
    try:
        sign_in(main, username, password)
        return 200
    except main.HTTPException as exc:
        return exc.status_code


def test_an_account_waits_after_too_many_wrong_passwords_even_for_the_right_one(locked_gateway):
    assert [attempt(locked_gateway, ADMIN, BAD) for _ in range(3)] == [401, 401, 401]
    assert attempt(locked_gateway, ADMIN, GOOD) == 429
    with pytest.raises(locked_gateway.HTTPException) as locked:
        sign_in(locked_gateway, ADMIN, GOOD)
    assert int(locked.value.headers["Retry-After"]) > 0


def test_an_unknown_name_is_locked_exactly_like_a_known_one(locked_gateway):
    known = [attempt(locked_gateway, ADMIN, BAD) for _ in range(4)]
    unknown = [attempt(locked_gateway, "nobody-here", BAD) for _ in range(4)]
    assert known == unknown == [401, 401, 401, 429]  # a lock-out must not tell which accounts exist


def test_one_account_being_locked_does_not_touch_another(locked_gateway):
    for _ in range(3):
        attempt(locked_gateway, ADMIN, BAD)
    assert attempt(locked_gateway, ADMIN, GOOD) == 429
    # a different account (same IP, same process) still gets its own three tries
    assert [attempt(locked_gateway, "someone-else", BAD) for _ in range(3)] == [401, 401, 401]


def test_a_successful_sign_in_clears_the_counter(locked_gateway):
    for _ in range(2):
        attempt(locked_gateway, ADMIN, BAD)
    assert attempt(locked_gateway, ADMIN, GOOD) == 200
    assert [attempt(locked_gateway, ADMIN, BAD) for _ in range(3)] == [401, 401, 401]  # a fresh count, not 2 + 3


def test_the_name_is_case_and_space_insensitive(locked_gateway):
    for name in ("ADMIN", " admin", "Admin "):
        attempt(locked_gateway, name, BAD)
    assert attempt(locked_gateway, "admin", GOOD) == 429


def test_the_lock_out_can_be_switched_off(locked_gateway, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MAX_FAILURES", 0)
    assert [attempt(locked_gateway, ADMIN, BAD) for _ in range(6)] == [401] * 6
    assert attempt(locked_gateway, ADMIN, GOOD) == 200


def test_counting_continues_in_this_process_while_redis_is_down(locked_gateway):
    locked_gateway.redis_client.down = True
    assert [attempt(locked_gateway, ADMIN, BAD) for _ in range(4)] == [401, 401, 401, 429]


def test_without_redis_nothing_is_counted(gateway, monkeypatch):  # noqa: F811  (development: no redis client at all)
    monkeypatch.setattr(settings, "AUTH_MAX_FAILURES", 1)
    assert [attempt(gateway, ADMIN, BAD) for _ in range(3)] == [401, 401, 401]


def test_the_password_recovery_key_failures_share_the_same_rule(locked_gateway):
    redis = locked_gateway.redis_client
    for _ in range(3):
        asyncio.run(rate_limit.record_failure(redis, "reset", "Carol"))
    with pytest.raises(locked_gateway.HTTPException) as locked:
        asyncio.run(rate_limit.check_failures(redis, "reset", "carol", 3))
    assert locked.value.status_code == 429
    asyncio.run(rate_limit.check_failures(redis, "login", "carol", 3))  # another scope: untouched
    assert request().client.host  # the helper still builds a request
