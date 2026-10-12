"""AUTH_MODE=off makes every caller an anonymous administrator, so it only serves local addresses: a public internet caller gets 403."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.config import settings
from src.shared.auth import authenticate


def call(host):
    request = SimpleNamespace(client=SimpleNamespace(host=host) if host is not None else None, headers={}, app=SimpleNamespace(state=SimpleNamespace()))
    return asyncio.run(authenticate(request))


@pytest.fixture(autouse=True)
def anonymous_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "off")
    monkeypatch.setattr(settings, "ALLOW_ANONYMOUS_REMOTE", False)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "10.0.0.5", "172.18.0.3", "192.168.1.20", "169.254.1.1", "testclient", None])
def test_local_callers_are_served(host):
    assert call(host).user_id == "anonymous"


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
def test_a_public_caller_is_refused_unless_the_operator_allows_it(host, monkeypatch):
    with pytest.raises(HTTPException) as refused:
        call(host)
    assert refused.value.status_code == 403
    monkeypatch.setattr(settings, "ALLOW_ANONYMOUS_REMOTE", True)
    assert call(host).user_id == "anonymous"
