"""Server-side conversations: ownership, optimistic concurrency, limits (real PostgreSQL via RAG_TEST_DSN)."""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi import FastAPI

from src.config import settings
from src.gateway import conversations
from src.gateway.conversations import ConversationIn, _newer_than, router

SECRET = "0123456789abcdef0123456789abcdef-test-secret"
DSN = os.getenv("RAG_TEST_DSN")


def bearer(user, tenant="acme"):
    claims = {"sub": user, "exp": int(time.time()) + 300, "tenant_id": tenant, "department_id": "legal", "roles": []}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def message(text):
    return {"id": f"m-{text}", "role": "user", "content": text}


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
    monkeypatch.setattr(settings, "AUTH_JWT_AUDIENCE", "")
    monkeypatch.setattr(settings, "AUTH_JWT_ISSUER", "")


def client_for(pg=None):
    app = FastAPI()
    app.include_router(router)
    if pg is not None:
        app.state.pg_client = pg
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------- no database needed
def test_versions_are_compared_to_the_millisecond_because_javascript_cannot_hold_more():
    saved = datetime(2026, 10, 1, 3, 0, 0, 123456, tzinfo=timezone.utc)
    assert not _newer_than(saved, datetime(2026, 10, 1, 3, 0, 0, 123000, tzinfo=timezone.utc))  # what a browser sends back
    assert not _newer_than(saved, saved)
    assert _newer_than(saved, saved - timedelta(milliseconds=5))
    assert _newer_than(saved, None)  # a client that never saw this chat
    assert not _newer_than(saved, datetime(2026, 10, 1, 3, 0, 0, 123000))  # no timezone: taken as UTC


def test_input_is_validated_before_anything_touches_the_database(jwt_mode):
    async def scenario():
        async with client_for() as client:  # no database configured at all
            assert (await client.get("/api/conversations", headers=bearer("alice"))).status_code == 503
            assert (await client.get("/api/conversations/bad id!", headers=bearer("alice"))).status_code == 422
            assert (await client.put("/api/conversations/ok", headers=bearer("alice"), json={"messages": "nope"})).status_code == 422
            assert (await client.get("/api/conversations")).status_code == 401  # no token

    asyncio.run(scenario())


def test_an_oversized_conversation_is_refused(jwt_mode, monkeypatch):
    monkeypatch.setattr(conversations, "MAX_BYTES", 200)

    async def scenario():
        async with client_for() as client:
            response = await client.put("/api/conversations/big", headers=bearer("alice"), json={"messages": [message("x" * 500)]})
            assert response.status_code == 413

    asyncio.run(scenario())


def test_a_conversation_body_limits_the_number_of_messages():
    with pytest.raises(ValueError):
        ConversationIn(messages=[message(str(i)) for i in range(conversations.MAX_MESSAGES + 1)])


# ---------------------------------------------------------------- real PostgreSQL
@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
class TestAgainstPostgres:
    @staticmethod
    def run(scenario):
        from src.shared.migrations import upgrade_to_head
        from src.shared.postgres_client import PostgresClient

        upgrade_to_head(DSN)

        async def go():
            pg = PostgresClient(dsn=DSN)
            await pg.connect(min_size=1, max_size=4)
            try:
                await pg.execute("DELETE FROM conversations")
                async with client_for(pg) as client:
                    await scenario(client, pg)
            finally:
                await pg.execute("DELETE FROM conversations")
                await pg.disconnect()

        asyncio.run(go())

    def test_save_list_read_and_delete(self, jwt_mode):
        async def scenario(client, pg):
            alice = bearer("alice")
            saved = await client.put("/api/conversations/c1", headers=alice, json={"title": "Hợp đồng NDA", "pinned": True, "messages": [message("chào")]})
            assert saved.status_code == 200 and saved.json()["title"] == "Hợp đồng NDA" and saved.json()["pinned"] is True
            listing = (await client.get("/api/conversations", headers=alice)).json()
            assert [c["id"] for c in listing] == ["c1"] and "messages" not in listing[0]
            full = (await client.get("/api/conversations/c1", headers=alice)).json()
            assert full["messages"] == [message("chào")]
            assert (await client.delete("/api/conversations/c1", headers=alice)).status_code == 204
            assert (await client.get("/api/conversations/c1", headers=alice)).status_code == 404

        self.run(scenario)

    def test_nobody_can_see_or_touch_another_users_conversation(self, jwt_mode):
        async def scenario(client, pg):
            await client.put("/api/conversations/secret", headers=bearer("alice"), json={"title": "riêng tư", "messages": [message("mật")]})
            for other in (bearer("mallory"), bearer("alice", tenant="globex")):  # another user; the same user name in another tenant
                assert (await client.get("/api/conversations", headers=other)).json() == []
                assert (await client.get("/api/conversations/secret", headers=other)).status_code == 404
                await client.delete("/api/conversations/secret", headers=other)  # a no-op for them
                overwrite = await client.put("/api/conversations/secret", headers=other, json={"title": "chiếm", "messages": []})
                assert overwrite.status_code == 200  # their own, new conversation with the same id
            assert (await client.get("/api/conversations/secret", headers=bearer("alice"))).json()["title"] == "riêng tư"

        self.run(scenario)

    def test_a_stale_save_gets_409_with_the_newer_server_version(self, jwt_mode):
        async def scenario(client, pg):
            alice = bearer("alice")
            first = (await client.put("/api/conversations/c1", headers=alice, json={"title": "v1", "messages": [message("a")]})).json()
            second = await client.put("/api/conversations/c1", headers=alice, json={"title": "v2", "messages": [message("b")], "base_updated_at": first["updated_at"]})
            assert second.status_code == 200 and second.json()["title"] == "v2"
            stale = await client.put("/api/conversations/c1", headers=alice, json={"title": "from another tab", "messages": [], "base_updated_at": first["updated_at"]})
            assert stale.status_code == 409 and stale.json()["title"] == "v2" and stale.json()["messages"] == [message("b")]
            unseen = await client.put("/api/conversations/c1", headers=alice, json={"title": "never saw it", "messages": []})
            assert unseen.status_code == 409  # no base version for an existing chat: refuse rather than overwrite
            assert (await client.get("/api/conversations/c1", headers=alice)).json()["title"] == "v2"

        self.run(scenario)

    def test_a_browser_that_only_keeps_milliseconds_can_still_save(self, jwt_mode):
        async def scenario(client, pg):
            alice = bearer("alice")
            first = (await client.put("/api/conversations/c1", headers=alice, json={"title": "v1", "messages": []})).json()
            parsed = datetime.fromisoformat(first["updated_at"].replace("Z", "+00:00"))
            millis = parsed.replace(microsecond=parsed.microsecond // 1000 * 1000).isoformat()  # what Date.toISOString() would give back
            again = await client.put("/api/conversations/c1", headers=alice, json={"title": "v2", "messages": [], "base_updated_at": millis})
            assert again.status_code == 200

        self.run(scenario)

    def test_the_number_of_conversations_per_user_is_capped(self, jwt_mode, monkeypatch):
        monkeypatch.setattr(conversations, "MAX_CONVERSATIONS_PER_USER", 2)

        async def scenario(client, pg):
            alice = bearer("alice")
            for name in ("a", "b"):
                assert (await client.put(f"/api/conversations/{name}", headers=alice, json={"messages": []})).status_code == 200
            assert (await client.put("/api/conversations/c", headers=alice, json={"messages": []})).status_code == 409
            assert (await client.put("/api/conversations/c", headers=bearer("bob"), json={"messages": []})).status_code == 200  # the cap is per user

        self.run(scenario)

    def test_concurrent_saves_of_one_chat_do_not_corrupt_it(self, jwt_mode):
        async def scenario(client, pg):
            alice = bearer("alice")
            first = (await client.put("/api/conversations/c1", headers=alice, json={"title": "v1", "messages": []})).json()
            results = await asyncio.gather(*[
                client.put("/api/conversations/c1", headers=alice, json={"title": f"w{i}", "messages": [message(str(i))], "base_updated_at": first["updated_at"]})
                for i in range(6)
            ])
            codes = sorted(r.status_code for r in results)
            assert codes == [200] + [409] * 5  # exactly one writer wins; the others are told so
            final = (await client.get("/api/conversations/c1", headers=alice)).json()
            assert final["title"] == next(r.json()["title"] for r in results if r.status_code == 200)

        self.run(scenario)
