"""Rate limiting: fixed one-minute windows per caller, shared through Redis, counted in-process when Redis is down."""
import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.shared import rate_limit
from src.shared.auth import Principal


class FakePipeline:
    def __init__(self, redis):
        self.redis, self.ops = redis, []

    def incr(self, key):
        self.ops.append(("incr", key))

    def expire(self, key, seconds, nx=False):
        self.ops.append(("expire", key, seconds, nx))

    async def execute(self):
        if self.redis.down:
            raise ConnectionError("redis down")
        results = []
        for op in self.ops:
            if op[0] == "incr":
                self.redis.counts[op[1]] = self.redis.counts.get(op[1], 0) + 1
                results.append(self.redis.counts[op[1]])
            else:
                self.redis.ttls[op[1]] = op[2]
                results.append(True)
        return results


class FakeRedis:
    def __init__(self):
        self.client, self.counts, self.ttls, self.down = self, {}, {}, False

    def pipeline(self):
        return FakePipeline(self)


def request(ip="10.0.0.1"):
    return MagicMock(client=MagicMock(host=ip))


def call(redis, principal, req, limit=3, group="chat"):
    return asyncio.run(rate_limit.enforce(redis, principal, req, group, limit))


ANON = Principal("anonymous", "t", "d")
ALICE = Principal("alice", "t", "d", frozenset(), authenticated=True)
BOB = Principal("bob", "t", "d", frozenset(), authenticated=True)


def test_calls_up_to_the_limit_pass_and_the_next_is_refused_with_retry_after():
    redis = FakeRedis()
    for _ in range(3):
        call(redis, ALICE, request())
    with pytest.raises(HTTPException) as refused:
        call(redis, ALICE, request())
    assert refused.value.status_code == 429 and 1 <= int(refused.value.headers["Retry-After"]) <= 60


def test_each_user_and_each_route_group_has_its_own_budget():
    redis = FakeRedis()
    for _ in range(3):
        call(redis, ALICE, request())
    call(redis, BOB, request())                       # another user
    call(redis, ALICE, request(), group="analyze")    # another route group
    with pytest.raises(HTTPException):
        call(redis, ALICE, request())


def test_anonymous_callers_are_told_apart_by_ip():
    redis = FakeRedis()
    for _ in range(3):
        call(redis, ANON, request("10.0.0.1"))
    call(redis, ANON, request("10.0.0.2"))
    with pytest.raises(HTTPException):
        call(redis, ANON, request("10.0.0.1"))


def test_the_counter_expires_by_itself():
    redis = FakeRedis()
    call(redis, ALICE, request())
    assert list(redis.ttls.values()) == [rate_limit.WINDOW_SECONDS + 5]


def test_a_limit_of_zero_or_a_missing_redis_means_unlimited():
    redis = FakeRedis()
    for _ in range(50):
        call(redis, ALICE, request(), limit=0)
        call(None, ALICE, request(), limit=1)
    assert redis.counts == {}


def test_when_redis_is_down_the_limit_still_holds_in_process():
    rate_limit._local.clear()
    redis = FakeRedis()
    redis.down = True
    for _ in range(3):
        call(redis, ALICE, request())
    call(redis, BOB, request())  # another caller keeps its own budget
    with pytest.raises(HTTPException) as refused:
        call(redis, ALICE, request())
    assert refused.value.status_code == 429
