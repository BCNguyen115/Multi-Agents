"""Job queue on PostgreSQL: one worker per job, runs as its owner, clears the uploaded bytes, recovers lost jobs (real PostgreSQL via RAG_TEST_DSN)."""
import asyncio
import os
import time

import httpx
import jwt
import pytest
from fastapi import FastAPI

from src.config import settings
from src.gateway import jobs as jobs_api
from src.shared import jobs
from src.shared.auth import Principal, current_principal

SECRET = "0123456789abcdef0123456789abcdef-test-secret"
DSN = os.getenv("RAG_TEST_DSN")
ALICE = Principal("alice", "acme", "legal", authenticated=True)


@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
class TestAgainstPostgres:
    @staticmethod
    def run(scenario):
        from src.shared.migrations import upgrade_to_head
        from src.shared.postgres_client import PostgresClient

        upgrade_to_head(DSN)

        async def go():
            pg = PostgresClient(dsn=DSN)
            await pg.connect(min_size=1, max_size=6)
            try:
                await pg.execute("DELETE FROM jobs")
                await scenario(pg)
            finally:
                await pg.execute("DELETE FROM jobs")
                await pg.disconnect()

        asyncio.run(go())

    def test_a_job_runs_as_its_owner_and_the_uploaded_bytes_do_not_outlive_it(self):
        seen = {}

        @jobs.register("t.echo")
        async def echo(payload, data):
            who = current_principal()
            seen.update(user=who.user_id, tenant=who.tenant_id, department=who.department_id, size=len(data))
            return {"echo": payload["x"]}

        async def scenario(pg):
            job_id = await jobs.enqueue(pg, "t.echo", ALICE, {"x": 7}, b"0123456789")
            assert (await pg.fetch("SELECT status FROM jobs WHERE id = $1", job_id))[0]["status"] == "queued"
            assert await jobs.run_one(pg) is True and await jobs.run_one(pg) is False  # nothing else queued
            row = (await pg.fetch("SELECT status, result, payload_bytes, attempts FROM jobs WHERE id = $1", job_id))[0]
            assert row["status"] == "done" and row["attempts"] == 1 and row["payload_bytes"] is None
            assert seen == {"user": "alice", "tenant": "acme", "department": "legal", "size": 10}

        self.run(scenario)

    def test_a_failing_job_reports_its_reason_and_does_not_stop_the_worker(self):
        @jobs.register("t.bad_file")
        async def bad_file(payload, data):
            raise jobs.JobError("This PDF has no text.")

        @jobs.register("t.crash")
        async def crash(payload, data):
            raise RuntimeError("secret internal detail")

        async def scenario(pg):
            bad = await jobs.enqueue(pg, "t.bad_file", ALICE, {}, b"x")
            crash_id = await jobs.enqueue(pg, "t.crash", ALICE, {}, b"x")
            unknown = await jobs.enqueue(pg, "t.nobody_handles_this", ALICE, {})
            while await jobs.run_one(pg):
                pass
            rows = {r["id"]: r for r in await pg.fetch("SELECT id, status, error, payload_bytes FROM jobs")}
            assert rows[bad]["status"] == "failed" and rows[bad]["error"] == "This PDF has no text."
            assert rows[crash_id]["status"] == "failed" and "secret" not in rows[crash_id]["error"]  # internals are not handed to the user
            assert rows[unknown]["status"] == "failed" and rows[bad]["payload_bytes"] is None and rows[crash_id]["payload_bytes"] is None

        self.run(scenario)

    def test_two_workers_never_take_the_same_job(self):
        ran = []

        @jobs.register("t.once")
        async def once(payload, data):
            ran.append(payload["n"])
            await asyncio.sleep(0.05)
            return {}

        async def scenario(pg):
            for n in range(6):
                await jobs.enqueue(pg, "t.once", ALICE, {"n": n})

            async def worker():
                while await jobs.run_one(pg):
                    pass

            await asyncio.gather(*[worker() for _ in range(4)])
            assert sorted(ran) == list(range(6))  # each job exactly once, however many workers raced
            assert (await pg.fetch("SELECT count(*) AS n FROM jobs WHERE status = 'done'"))[0]["n"] == 6

        self.run(scenario)

    def test_a_job_whose_worker_vanished_is_put_back_and_finally_failed(self, monkeypatch):
        monkeypatch.setattr(settings, "JOB_STALE_MINUTES", 10)
        monkeypatch.setattr(settings, "JOB_MAX_ATTEMPTS", 2)

        async def scenario(pg):
            job_id = await jobs.enqueue(pg, "t.echo", ALICE, {}, b"data")
            await jobs.claim(pg)  # taken... and the worker dies
            assert await jobs.requeue_stale(pg) == 0  # too recent to be called lost
            await pg.execute("UPDATE jobs SET started_at = now() - interval '1 hour' WHERE id = $1", job_id)
            assert await jobs.requeue_stale(pg) == 1
            assert (await pg.fetch("SELECT status FROM jobs WHERE id = $1", job_id))[0]["status"] == "queued"  # attempt 1 of 2: again
            await jobs.claim(pg)
            await pg.execute("UPDATE jobs SET started_at = now() - interval '1 hour' WHERE id = $1", job_id)
            await jobs.requeue_stale(pg)
            row = (await pg.fetch("SELECT status, payload_bytes FROM jobs WHERE id = $1", job_id))[0]
            assert row["status"] == "failed" and row["payload_bytes"] is None  # attempts used up

        self.run(scenario)

    def test_old_finished_jobs_are_purged_and_only_the_owner_reads_a_job(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
        monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
        monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
        monkeypatch.setattr(settings, "AUTH_JWT_AUDIENCE", "")
        monkeypatch.setattr(settings, "AUTH_JWT_ISSUER", "")

        def bearer(user, tenant="acme"):
            claims = {"sub": user, "exp": int(time.time()) + 300, "tenant_id": tenant, "department_id": "legal", "roles": []}
            return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}

        @jobs.register("t.result")
        async def with_result(payload, data):
            return {"doc_key": "nda/a.pdf", "chunks": 3}

        async def scenario(pg):
            job_id = await jobs.enqueue(pg, "t.result", ALICE, {})
            await jobs.run_one(pg)
            app = FastAPI()
            app.include_router(jobs_api.router)
            app.state.pg_client = pg
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                mine = await client.get(f"/api/jobs/{job_id}", headers=bearer("alice"))
                assert mine.status_code == 200 and mine.json()["status"] == "done" and mine.json()["result"]["chunks"] == 3
                assert (await client.get(f"/api/jobs/{job_id}", headers=bearer("bob"))).status_code == 404
                assert (await client.get(f"/api/jobs/{job_id}", headers=bearer("alice", tenant="globex"))).status_code == 404
                assert (await client.get("/api/jobs/bad id!", headers=bearer("alice"))).status_code == 422
            await pg.execute("UPDATE jobs SET finished_at = now() - interval '30 days' WHERE id = $1", job_id)
            await jobs.purge_finished(pg)
            assert (await pg.fetch("SELECT count(*) AS n FROM jobs"))[0]["n"] == 0

        self.run(scenario)
