"""Thumbs on answers: stored per user, validated, rate limited, and exportable as evaluation questions."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from scripts.export_feedback_eval import build_items
from src.gateway import feedback
from src.gateway.feedback import FeedbackIn
from src.shared.auth import Principal

ALICE = Principal("alice", "acme", "legal", frozenset(), authenticated=True)


class PG:
    def __init__(self):
        self.rows = []

    async def execute(self, sql, *args):
        self.rows.append(args)


def request(pg):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_client=pg, redis_client=None)), client=SimpleNamespace(host="203.0.113.7"), headers={})


def send(body, pg):
    return asyncio.run(feedback.submit_feedback(body, request(pg), ALICE))


def test_a_thumb_is_stored_for_the_caller_with_what_was_cited():
    pg = PG()
    body = FeedbackIn(rating=1, query="Thời hạn NDA?", message_id="m1", cited=[{"file": "nda/a.pdf", "section": "Term", "page": 3, "snippet": "The term is two years."}])
    send(body, pg)
    tenant, user, session, message, query, rating, comment, cited = pg.rows[0]
    assert (tenant, user, message, query, rating) == ("acme", "alice", "m1", "Thời hạn NDA?", 1)
    assert json.loads(cited)[0]["file"] == "nda/a.pdf"


def test_only_plus_or_minus_one_is_a_rating_and_text_is_bounded():
    with pytest.raises(ValidationError):
        FeedbackIn(rating=5)
    with pytest.raises(ValidationError):
        FeedbackIn(rating=1, comment="x" * 5000)
    with pytest.raises(ValidationError):
        FeedbackIn(rating=1, cited=[{"file": "f"}] * 11)


def test_without_a_database_the_route_says_the_service_is_starting():
    with pytest.raises(HTTPException) as starting:
        send(FeedbackIn(rating=-1), None)
    assert starting.value.status_code == 503


def test_thumbs_up_become_evaluation_questions_and_thumbs_down_go_to_review():
    rows = [
        {"query": "Thời hạn NDA?", "rating": 1, "comment": "", "cited": [{"file": "nda/a.pdf", "snippet": "The term of this Agreement is two (2) years from the date"}]},
        {"query": "Thời hạn NDA?", "rating": 1, "comment": "", "cited": [{"file": "nda/a.pdf", "snippet": "The term of this Agreement is two (2) years from the date"}]},  # same again
        {"query": "Phí là bao nhiêu?", "rating": -1, "comment": "sai số", "cited": [{"file": "sow/b.pdf", "snippet": "Fees are as set out in Schedule A"}]},
        {"query": "", "rating": 1, "comment": "", "cited": [{"file": "x.pdf", "snippet": "a long enough snippet of text here"}]},     # no question
        {"query": "Câu hỏi", "rating": 1, "comment": "", "cited": [{"file": "y.pdf", "snippet": "short"}]},                           # nothing to match on
        {"query": "Câu hỏi hai", "rating": 1, "comment": "", "cited": json.dumps([{"file": "z.pdf", "snippet": "Termination for convenience requires thirty days notice"}])},
    ]
    questions, review = build_items(rows)
    assert questions == [
        {"question": "Thời hạn NDA?", "file": "nda/a.pdf", "phrase": "The term of this Agreement is two (2) years from the date"},
        {"question": "Câu hỏi hai", "file": "z.pdf", "phrase": "Termination for convenience requires thirty days notice"},
    ]
    assert review == [{"question": "Phí là bao nhiêu?", "comment": "sai số", "cited": [{"file": "sow/b.pdf", "snippet": "Fees are as set out in Schedule A"}]}]


def test_an_exported_question_is_answered_by_a_chunk_that_contains_its_phrase():
    from scripts.run_rag_eval import _is_answer

    (question,), _ = build_items([{"query": "q", "rating": 1, "comment": "", "cited": [{"file": "nda/a.pdf", "snippet": "The term of this  Agreement\nis two years from the date of signature."}]}])
    chunk = {"filename": "nda/a.pdf", "content": "[Source: nda/a.pdf]\n\nThe term of this Agreement is two years from the date of signature. More."}
    assert _is_answer(chunk, question)
