"""Online answer grading: what is graded, what is stored (masked, cut), and that a failure never reaches the reply."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.config import settings
from src.shared import quality
from src.shared.security import wrap_user_input


def grader(reply: str):
    llm = MagicMock()
    llm.chat_completion = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))]))
    return llm


def test_the_grade_is_read_from_the_models_json_and_bad_replies_are_refused():
    assert quality.parse_grade('noise {"score": 4, "reason": "ok"} tail') == (4, "ok")
    for bad in ("", "no json", '{"score": 9}', '{"score": "x"}', '{"reason": "no score"}'):
        assert quality.parse_grade(bad) is None


def test_the_answer_a_user_read_is_taken_out_of_json_replies():
    assert quality.answer_text(json.dumps({"answer": "Hai năm.", "sources": []})) == "Hai năm."
    assert quality.answer_text("plain text") == "plain text"


def test_a_graded_answer_is_stored_masked_and_with_who_asked(monkeypatch):
    pg = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(quality, "_pg", pg)
    who = SimpleNamespace(tenant_id="t1", user_id="alice")
    ok = asyncio.run(quality.review(
        grader('{"score": 2, "reason": "lạc đề"}'), "fast", who, "rag_agent",
        wrap_user_input("Email tôi là a@b.com, NDA bao lâu?")[0], json.dumps({"answer": "Gọi 0901234567"}), False, 1, "s1",
    ))
    assert ok is True
    args = pg.execute.await_args.args
    assert args[1:3] == ("t1", "alice") and args[3] == "rag_agent"
    assert "a@b.com" not in args[4] and "0901234567" not in args[5]  # masked before it is stored
    assert args[6] == 2 and args[8] is False and args[9] == 1


def test_a_grader_that_fails_or_rambles_stores_nothing_and_raises_nothing(monkeypatch):
    pg = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(quality, "_pg", pg)
    who = SimpleNamespace(tenant_id="t", user_id="u")
    broken = MagicMock()
    broken.chat_completion = AsyncMock(side_effect=ConnectionError("down"))
    assert asyncio.run(quality.review(broken, "m", who, "a", "q?", "answer", True, 0, "s")) is False
    assert asyncio.run(quality.review(grader("I think it is fine"), "m", who, "a", "q?", "answer", True, 0, "s")) is False
    pg.execute.assert_not_awaited()


def test_sampling_follows_the_rate_and_needs_a_database(monkeypatch):
    pg = SimpleNamespace(execute=AsyncMock())

    async def run(rate, configured=True):
        monkeypatch.setattr(quality, "_pg", pg if configured else None)
        monkeypatch.setattr(settings, "QUALITY_SAMPLE_RATE", rate)
        task = quality.maybe_review(grader('{"score": 5, "reason": "ok"}'), "m", "rag_agent", "q?", "answer", True, 0, "s")
        if task:
            await task
        return task

    assert asyncio.run(run(0.0)) is None
    assert asyncio.run(run(1.0, configured=False)) is None
    assert asyncio.run(run(1.0)) is not None
    assert pg.execute.await_count == 1
