"""OIDC single sign-on against a fake identity provider: PKCE, single-use state, every id_token check, account rules."""
import asyncio
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI

from src.config import settings
from src.gateway import sso
from src.shared import oidc

SECRET = "0123456789abcdef0123456789abcdef-test-secret"
ISSUER = "https://idp.test"
CLIENT_ID = "cid"
META = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/auth", "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks"}
IDP_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def set_value(self, key, value, ttl=0, session_id=""):
        self.values[key] = value

    async def take_value(self, key, session_id=""):
        return self.values.pop(key, None)


class FakePG:
    """Just the upsert the SSO route makes, with the rule that a password account is never taken over."""

    def __init__(self):
        self.accounts = {}

    async def fetch(self, sql, name, display, tenant, department):
        found = self.accounts.get(name)
        if found is None:
            found = self.accounts[name] = {"password_hash": "sso", "roles": [], "tenant_id": tenant, "department_id": department, "disabled": False, "display_name": display}
        elif found["password_hash"] != "sso":
            return []
        else:
            found["display_name"] = display
        return [{"username": name, "display_name": found["display_name"], "roles": found["roles"], "tenant_id": found["tenant_id"],
                 "department_id": found["department_id"], "disabled": found["disabled"]}]


def id_token(nonce, key=IDP_KEY, **overrides):
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "u-1", "email": "Alice@Corp.com", "email_verified": True, "name": "Alice",
              "iat": now, "exp": now + 300, "nonce": nonce, **overrides}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k"})


@pytest.fixture
def idp(monkeypatch):
    for name, value in {"AUTH_MODE": "jwt", "AUTH_JWT_SECRET": SECRET, "AUTH_JWKS_URL": "", "AUTH_JWT_AUDIENCE": "", "AUTH_JWT_ISSUER": "",
                        "OIDC_ISSUER": ISSUER, "OIDC_CLIENT_ID": CLIENT_ID, "OIDC_CLIENT_SECRET": "sec",
                        "OIDC_REDIRECT_URI": "https://app.test/api/auth/oidc/callback", "OIDC_USERNAME_CLAIM": "email"}.items():
        monkeypatch.setattr(settings, name, value)
    state = {"make_token": lambda nonce: id_token(nonce), "exchanged": []}

    async def discovery():
        return META

    async def exchange(meta, code, verifier):
        state["exchanged"].append((code, verifier))
        return {"id_token": state["make_token"](state["nonce"])}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(oidc, "discovery", discovery)
    monkeypatch.setattr(oidc, "exchange_code", exchange)
    monkeypatch.setattr(oidc, "_signing_key", lambda token, uri: IDP_KEY.public_key())
    monkeypatch.setattr(sso, "enforce_rate_limit", noop)
    return state


def client(redis, pg):
    app = FastAPI()
    app.include_router(sso.router)
    app.state.redis_client, app.state.pg_client = redis, pg
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def start(http, idp_state):
    """The first leg: ask for the provider URL; remember the nonce the provider would echo back."""
    url = (await http.get("/api/auth/oidc/login")).json()["url"]
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    idp_state["nonce"] = query["nonce"]
    return url, query


def test_pkce_challenge_matches_the_rfc_7636_example():
    assert oidc.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_account_name_is_namespaced_and_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "OIDC_USERNAME_CLAIM", "email")
    assert oidc.account_name({"email": " Alice@Corp.com ", "sub": "1"}) == "sso:alice@corp.com"
    assert oidc.account_name({"preferred_username": "alice", "sub": "1"}) == "sso:alice"
    assert oidc.account_name({"sub": "9f"}) == "sso:9f"


def test_sso_is_off_unless_fully_configured_and_not_with_an_external_jwks(idp, monkeypatch):
    assert oidc.sso_enabled() is True
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "")
    assert oidc.sso_enabled() is False
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "sec")
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "https://idp.test/jwks")  # then tokens come from the provider, not from this gateway
    assert oidc.sso_enabled() is False


def test_both_routes_are_404_when_sso_is_off(monkeypatch):
    monkeypatch.setattr(settings, "OIDC_ISSUER", "")

    async def scenario():
        async with client(FakeRedis(), FakePG()) as http:
            assert (await http.get("/api/auth/oidc/login")).status_code == 404
            assert (await http.post("/api/auth/oidc/callback", json={"code": "c", "state": "s"})).status_code == 404

    asyncio.run(scenario())


def test_the_login_url_carries_pkce_state_and_nonce_and_the_state_is_stored(idp):
    async def scenario():
        redis = FakeRedis()
        async with client(redis, FakePG()) as http:
            url, query = await start(http, idp)
            assert url.startswith(f"{ISSUER}/auth?")
            assert (query["response_type"], query["client_id"], query["code_challenge_method"]) == ("code", CLIENT_ID, "S256")
            assert query["redirect_uri"] == settings.OIDC_REDIRECT_URI and "openid" in query["scope"]
            stored = json.loads(redis.values[f"oidc:state:{query['state']}"])
            assert stored["nonce"] == query["nonce"] and oidc.pkce_challenge(stored["verifier"]) == query["code_challenge"]

    asyncio.run(scenario())


def test_a_good_sign_in_creates_a_pending_account_and_the_state_cannot_be_replayed(idp):
    async def scenario():
        pg = FakePG()
        async with client(FakeRedis(), pg) as http:
            _, query = await start(http, idp)
            done = await http.post("/api/auth/oidc/callback", json={"code": "the-code", "state": query["state"]})
            assert done.status_code == 200, done.text
            claims = jwt.decode(done.json()["access_token"], SECRET, algorithms=["HS256"])
            assert claims["sub"] == "sso:alice@corp.com" and claims["roles"] == []
            assert claims[settings.AUTH_TENANT_CLAIM] == settings.REGISTRATION_TENANT_ID  # an administrator grants access in /admin
            code, verifier = idp["exchanged"][0]
            assert code == "the-code" and oidc.pkce_challenge(verifier) == query["code_challenge"]
            replay = await http.post("/api/auth/oidc/callback", json={"code": "the-code", "state": query["state"]})
            assert replay.status_code == 400
            assert (await http.post("/api/auth/oidc/callback", json={"code": "x", "state": "never-issued"})).status_code == 400

    asyncio.run(scenario())


@pytest.mark.parametrize("make_token", [
    lambda nonce: id_token("not-the-nonce"),
    lambda nonce: id_token(nonce, email_verified=False),
    lambda nonce: id_token(nonce, aud="someone-else"),
    lambda nonce: id_token(nonce, iss="https://evil.test"),
    lambda nonce: id_token(nonce, exp=int(time.time()) - 10),
    lambda nonce: id_token(nonce, key=OTHER_KEY),  # signed by a key the provider does not publish
    lambda nonce: "not.a.jwt",
])
def test_every_check_on_the_id_token_refuses_a_bad_one(idp, make_token):
    idp["make_token"] = make_token

    async def scenario():
        pg = FakePG()
        async with client(FakeRedis(), pg) as http:
            _, query = await start(http, idp)
            refused = await http.post("/api/auth/oidc/callback", json={"code": "c", "state": query["state"]})
            assert refused.status_code == 401
            assert pg.accounts == {}  # nothing was created for a sign-in that did not verify

    asyncio.run(scenario())


def test_a_locked_account_and_a_password_account_of_the_same_name_are_refused(idp):
    async def scenario():
        pg = FakePG()
        async with client(FakeRedis(), pg) as http:
            _, first = await start(http, idp)
            assert (await http.post("/api/auth/oidc/callback", json={"code": "c", "state": first["state"]})).status_code == 200
            pg.accounts["sso:alice@corp.com"]["disabled"] = True
            _, second = await start(http, idp)
            assert (await http.post("/api/auth/oidc/callback", json={"code": "c", "state": second["state"]})).status_code == 403
            pg.accounts["sso:alice@corp.com"].update(disabled=False, password_hash="scrypt$whatever")
            _, third = await start(http, idp)
            assert (await http.post("/api/auth/oidc/callback", json={"code": "c", "state": third["state"]})).status_code == 409

    asyncio.run(scenario())
