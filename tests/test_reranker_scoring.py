"""Reranker: the pool is scored once at full length; a failed call falls back to the hybrid order."""
import asyncio
from unittest.mock import patch

import pytest

from src.config import settings
from src.shared import reranker_client
from src.shared.reranker_client import rerank_documents


def docs(n):
    return [{"id": i, "content": f"text {i}"} for i in range(n)]


class FakeScorer:
    """Stands in for one TEI call; returns None (= failure) when ``fail``."""

    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def __call__(self, query, docs_, max_chars, budget, endpoint, session_id):
        self.calls.append({"ids": [d["id"] for d in docs_], "max_chars": max_chars, "budget": budget})
        return None if self.fail else sorted(({**d, "rerank_score": d["id"]} for d in docs_), key=lambda d: -d["rerank_score"])


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(reranker_client, "_consecutive_failures", 0)
    monkeypatch.setattr(settings, "RERANK_POOL_K", 10)
    monkeypatch.setattr(settings, "MAX_RERANK_TEXT_LENGTH", 1000)
    monkeypatch.setattr(settings, "RERANKER_TIMEOUT", 8.0)


def run(scorer, n=20, top_k=3):
    with patch("src.shared.reranker_client._score", new=scorer):
        return asyncio.run(rerank_documents("q", docs(n), top_k=top_k))


def test_only_the_pool_is_scored_once_at_full_length():
    scorer = FakeScorer()
    top = run(scorer)
    assert len(scorer.calls) == 1 and scorer.calls[0]["ids"] == list(range(10)) and scorer.calls[0]["max_chars"] == 1000
    assert scorer.calls[0]["budget"] == 8.0
    assert [d["id"] for d in top] == [9, 8, 7]


def test_a_failed_call_keeps_the_hybrid_order():
    assert [d["id"] for d in run(FakeScorer(fail=True))] == [0, 1, 2]
