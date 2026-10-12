"""Run checkpoints: every step of a request is saved, so a run can be listed, shown, resumed and replayed from any step.

The orchestrator logic runs on LangGraph's in-memory saver; what PostgreSQL really stores (no uploaded file, cut answers, retention)
needs RAG_TEST_DSN, like the other real-database tests.
"""
import asyncio
import json
import os

import pytest

from scripts import run_orchestration_eval as ev
from src.orchestrator import checkpointing
from src.orchestrator.checkpointing import open_checkpointer, purge_old_runs
from src.shared.security import wrap_user_input

GROUNDED = {"answer": "Thời hạn là 2 năm [1].", "sources": [], "verification": {"status": "ok", "grounded": True, "cited": [1], "unsupported_numbers": []}}
DSN = os.getenv("RAG_TEST_DSN")


def make(checkpointer, agent="rag_agent", replies=(GROUNDED,)):
    agents = {agent: ev.make_agent(agent, {"replies": list(replies)})}
    return ev.build_orchestrator(agents, ev.ScriptedLLM(), checkpointer=checkpointer), agents[agent]


def ask(orch, session="s1", **kw):
    return json.loads(asyncio.run(orch.handle_request(query=wrap_user_input("Thời hạn NDA?")[0], session_id=session, agent_mode="rag_agent", **kw)))


def memory_saver():
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def test_without_a_checkpointer_nothing_is_saved_and_the_run_has_no_id():
    orch, _ = make(None)
    assert "run_id" not in ask(orch)["pev_trace"]
    with pytest.raises(RuntimeError, match="CHECKPOINT_ENABLED"):
        asyncio.run(orch.run_history("anything"))


def test_a_run_is_saved_step_by_step_and_its_id_is_in_the_trace():
    orch, _ = make(memory_saver())
    run_id = ask(orch)["pev_trace"]["run_id"]
    history = asyncio.run(orch.run_history(run_id))
    nexts = [tuple(h["next"]) for h in history]
    assert ("executor",) in nexts and ("verifier",) in nexts and nexts[-1] == ()  # oldest first, the last step has nothing left to run
    assert history[-1]["values"]["is_verified"] is True and history[-1]["values"]["target_agent"] == "rag_agent"


def test_every_request_is_its_own_run_even_in_the_same_session():
    orch, _ = make(memory_saver())
    first, second = ask(orch)["pev_trace"]["run_id"], ask(orch)["pev_trace"]["run_id"]
    assert first != second
    runs = asyncio.run(orch.recent_runs("s1"))
    assert {r["run_id"] for r in runs} == {first, second}
    assert runs[0]["query"] == "Thời hạn NDA?" and runs[0]["agent"] == "rag_agent" and runs[0]["verified"] is True  # the nonce wrapper is not shown
    assert asyncio.run(orch.recent_runs("another-session")) == []


def test_replaying_from_a_step_runs_the_nodes_after_it_again():
    orch, agent = make(memory_saver())
    run_id = ask(orch)["pev_trace"]["run_id"]
    assert agent.calls == ["process_request"]

    async def replay():
        history = await orch.run_history(run_id)
        before_executor = next(h for h in history if tuple(h["next"]) == ("executor",))
        return await orch.replay_run(run_id, before_executor["checkpoint_id"])

    final = asyncio.run(replay())
    assert agent.calls == ["process_request", "process_request"]  # the executor really ran again
    assert final["is_verified"] is True and "2 năm" in final["final_response"]


def test_a_finished_run_continued_without_a_step_does_nothing():
    orch, agent = make(memory_saver())
    run_id = ask(orch)["pev_trace"]["run_id"]
    asyncio.run(orch.replay_run(run_id))
    assert agent.calls == ["process_request"]


def test_the_stream_entry_point_reports_the_run_id_too():
    orch, _ = make(memory_saver())

    async def collect():
        return [e async for e in orch.handle_stream_request(query=wrap_user_input("Thời hạn NDA?")[0], session_id="s1", agent_mode="rag_agent")]

    final = json.loads(asyncio.run(collect())[-1]["data"])
    assert final["pev_trace"]["run_id"]


def test_long_text_is_cut_and_the_uploaded_file_is_never_saved():
    cut = checkpointing._lean("x" * 30, 10)
    assert cut.startswith("x" * 10) and "20 more characters" in cut
    assert checkpointing._lean("short", 10) == "short" and checkpointing._lean({"a": 1}, 10) == {"a": 1}
    assert checkpointing._lean({"csv_content": "secret", "query": "q", "nested": {"csv_content": "secret"}}, 10) == {"query": "q", "nested": {}}
    assert "csv_content" in checkpointing._NOT_SAVED


@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
def test_postgres_keeps_no_uploaded_file_cuts_long_answers_and_purges_old_runs():
    tables = "checkpoint_writes, checkpoint_blobs, checkpoints, checkpoint_migrations"

    async def scenario():
        import psycopg

        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as admin:
            await admin.execute(f"DROP TABLE IF EXISTS {tables}")
        saver, pool = await open_checkpointer(DSN, 50)
        try:
            orch = ev.build_orchestrator({"data_agent": ev.make_agent("data_agent", {"replies": ["y" * 500]})}, ev.ScriptedLLM(), checkpointer=saver)
            out = json.loads(await orch.handle_request(
                query=wrap_user_input("Tóm tắt")[0], session_id="s1", csv_content="secret,csv\n1,2\n", csv_filename="f.csv", agent_mode="data_agent",
            ))
            run_id = out["pev_trace"]["run_id"]
            history = await orch.run_history(run_id)
            assert "secret,csv" not in json.dumps(history, default=str)
            last = history[-1]["values"]
            assert len(last["execution_result"]) < 200 and "more characters not saved" in last["execution_result"]

            async with pool.connection() as conn:
                for table, column in (("checkpoints", "convert_to(checkpoint::text, 'UTF8')"), ("checkpoint_blobs", "blob"), ("checkpoint_writes", "blob")):
                    row = await (await conn.execute(f"SELECT count(*) AS n FROM {table} WHERE position(convert_to('secret,csv', 'UTF8') in {column}) > 0")).fetchone()
                    assert row["n"] == 0, f"the uploaded file reached {table}"

            assert await purge_old_runs(saver, pool, 365) == 0  # a fresh run is not old
            assert await purge_old_runs(saver, pool, 0) == 1
            assert await orch.run_history(run_id) == []
        finally:
            await pool.close()
            async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as admin:
                await admin.execute(f"DROP TABLE IF EXISTS {tables}")

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:  # psycopg's async mode cannot use Windows' default proactor loop
        runner.run(scenario())
