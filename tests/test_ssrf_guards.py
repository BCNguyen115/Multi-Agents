"""Outbound REST calls (Integration Agent): configurable allow-list, no redirects, no allow-listed name that resolves to a
private address."""
import asyncio
import json
import socket

import httpx
import pytest
from pydantic import ValidationError

from src.config import settings
from src.shared import mcp_client
from src.shared.mcp_client import MCPClient, RESTToolInput, resolves_to_private_address


def fake_dns(monkeypatch, mapping):
    """Make the event loop's getaddrinfo answer from ``mapping`` (name -> address)."""

    async def getaddrinfo(self, host, port, **kw):
        if host not in mapping:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], 0))]

    monkeypatch.setattr(asyncio.base_events.BaseEventLoop, "getaddrinfo", getaddrinfo)


def client_with(handler):
    mcp = MCPClient()
    mcp.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return mcp


def call(mcp, url="https://example.com/x", method="GET"):
    return json.loads(asyncio.run(mcp.execute_rest_request(url=url, method=method)))


# ---------------------------------------------------------------- allow-list
def test_the_allow_list_comes_from_configuration(monkeypatch):
    RESTToolInput(url="https://example.com/a", method="GET")  # the defaults keep the demo hosts
    monkeypatch.setattr(settings, "INTEGRATION_ALLOWED_HOSTS", ["api.corp.example"])
    with pytest.raises(ValidationError):
        RESTToolInput(url="https://example.com/a", method="GET")
    RESTToolInput(url="https://api.corp.example/a", method="GET")
    RESTToolInput(url="https://billing.internal/a", method="GET")  # `.internal` stays allowed


# ---------------------------------------------------------------- redirects
def test_redirects_are_never_followed(monkeypatch):
    fake_dns(monkeypatch, {"example.com": "93.184.216.34"})
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    mcp = client_with(handler)
    assert MCPClient().http_client.follow_redirects is False
    result = call(mcp)
    assert seen == ["https://example.com/x"] and result["status_code"] == 302  # the Location was not visited


# ---------------------------------------------------------------- DNS pointing an allowed name at a private address
@pytest.mark.parametrize("address", ["169.254.169.254", "10.0.0.5", "192.168.1.1", "127.0.0.1", "172.16.0.9", "0.0.0.0"])
def test_an_allowed_name_that_resolves_to_a_private_address_is_refused_without_sending_anything(monkeypatch, address):
    fake_dns(monkeypatch, {"example.com": address})
    sent = []
    mcp = client_with(lambda request: sent.append(request) or httpx.Response(200, json={}))
    result = call(mcp)
    assert result["status"] == "error" and "private" in result["message"] and sent == []


def test_a_public_address_is_let_through(monkeypatch):
    fake_dns(monkeypatch, {"example.com": "93.184.216.34"})
    mcp = client_with(lambda request: httpx.Response(200, json={"ok": True}))
    assert call(mcp)["status_code"] == 200


def test_an_unresolvable_name_is_refused(monkeypatch):
    fake_dns(monkeypatch, {})
    assert asyncio.run(resolves_to_private_address("example.com")) is True


def test_local_and_internal_hosts_are_exempt_from_the_public_address_rule(monkeypatch):
    fake_dns(monkeypatch, {})  # nothing resolves: they must not even be looked up
    for host in ("localhost", "127.0.0.1", "[::1]", "api.enterprise.internal", "billing.internal"):
        assert asyncio.run(resolves_to_private_address(host)) is False
    assert mcp_client._is_internal_host("evil.internal.example.com") is False
