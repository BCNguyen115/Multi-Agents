"""Latency and measurement upgrades: the question is embedded while the planner runs, the cross-encoder can be skipped when the
first candidate clearly leads, and the evaluation can grade relevance with an LLM instead of "is it the source chunk"."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.run_rag_eval import evaluate_judged, judged_metrics, ndcg_at
from src.agents.rag_agent.agent import RAGAgent
from src.agents.rag_agent.knowledge import KnowledgeStore
from src.agents.rag_agent.planner import QueryPlan
from src.config import settings
from src.shared import reranker_client
from src.shared.reranker_client import rerank_documents
from tests.test_rag_agent import FakeLLM, FakeRedis, FakeStore, ask, chunk
from tests.test_rag_upgrades import CountingEmbedding, RecordingPG, ROW


class EmbedStore(FakeStore):
    """A store that can embed ahead of the search, and remembers what it was asked."""

    def __init__(self, rows, fail=False):
        super().__init__(rows)
        self.embedded, self.fail = [], fail

    async def embed_query(self, text, session_id="N/A"):
        self.embedded.append(text)
        if self.fail:
            raise ConnectionError("embedding api down")
        return [0.25, 0.5]


# ---- the question is embedded while the planner runs ------------------------------------------------------------------------------------

def test_a_question_without_history_is_embedded_during_planning_and_the_vector_reaches_the_search(monkeypatch):
    monkeypatch.setattr(settings, "RAG_PARALLEL_EMBED", True)
    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "both")
    store = EmbedStore([chunk(1)])
    ask(RAGAgent(store, FakeLLM("Thời hạn là 2 năm [1].")))
    assert store.embedded == ["Thời hạn NDA?"]
    assert store.plans[0].query_vector == [0.25, 0.5]


def test_a_follow_up_is_not_embedded_early_because_the_planner_will_rewrite_it(monkeypatch):
    monkeypatch.setattr(settings, "RAG_PARALLEL_EMBED", True)
    store = EmbedStore([chunk(1)])
    history = FakeRedis([{"role": "user", "content": "Cho tôi NDA"}, {"role": "assistant", "content": "Đây là NDA"}])
    ask(RAGAgent(store, FakeLLM("Trả lời [1]."), redis_client=history), question="còn thời hạn thì sao?")
    assert store.embedded == [] and store.plans[0].query_vector is None


def test_a_question_the_planner_rewrote_does_not_get_the_early_vector(monkeypatch):
    monkeypatch.setattr(settings, "RAG_PARALLEL_EMBED", True)
    store = EmbedStore([chunk(1)])
    llm = FakeLLM("Trả lời [1].", plan={"standalone": "thời hạn bảo mật của NDA", "passage": "The term is two years."})
    ask(RAGAgent(store, llm), question="thời hạn?")
    assert store.plans[0].standalone == "thời hạn bảo mật của NDA" and store.plans[0].query_vector is None


def test_a_failed_early_embedding_is_not_an_error_the_search_deals_with_it(monkeypatch):
    monkeypatch.setattr(settings, "RAG_PARALLEL_EMBED", True)
    store = EmbedStore([chunk(1)], fail=True)
    out = ask(RAGAgent(store, FakeLLM("Thời hạn là 2 năm [1].")))
    assert out["verification"]["status"] == "ok" and store.plans[0].query_vector is None


def test_the_switch_and_the_query_mode_turn_it_off(monkeypatch):
    store = EmbedStore([chunk(1)])
    monkeypatch.setattr(settings, "RAG_PARALLEL_EMBED", False)
    ask(RAGAgent(store, FakeLLM("a [1].")))
    monkeypatch.setattr(settings, "RAG_PARALLEL_EMBED", True)
    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "hyde")  # the raw question is not searched in this mode
    ask(RAGAgent(store, FakeLLM("a [1].")))
    assert store.embedded == []


def test_the_search_does_not_embed_the_question_twice(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "both")
    llm = CountingEmbedding()
    plan = QueryPlan(standalone="thời hạn", passage="The term is two years.", query_vector=[0.9, 0.8])
    asyncio.run(KnowledgeStore(RecordingPG(rows=[ROW]), llm).search("thời hạn", top_k=5, plan=plan))
    assert llm.texts == ["The term is two years."]            # only the passage: the question's vector came with the plan
    llm = CountingEmbedding()
    other = QueryPlan(standalone="khác", passage="The term is two years.", query_vector=[0.9, 0.8])
    asyncio.run(KnowledgeStore(RecordingPG(rows=[ROW]), llm).search("thời hạn", top_k=5, plan=other))
    assert sorted(llm.texts) == ["The term is two years.", "thời hạn"]  # a vector of another question is never reused


# ---- skipping the cross-encoder ------------------------------------------------------------------------------------------------------------

DOCS = [{"id": 1, "content": "a", "vector_score": 0.80}, {"id": 2, "content": "b", "vector_score": 0.50}, {"id": 3, "content": "c", "vector_score": 0.4}]
CLOSE = [{"id": 1, "content": "a", "vector_score": 0.80}, {"id": 2, "content": "b", "vector_score": 0.78}]


def rerank(docs, monkeypatch):
    monkeypatch.setattr(reranker_client, "_consecutive_failures", 0)
    scorer = AsyncMock(return_value=[{**d, "rerank_score": 1.0 - i / 10} for i, d in enumerate(docs)])
    with patch("src.shared.reranker_client._score", new=scorer):
        out = asyncio.run(rerank_documents("q", docs, top_k=2))
    return out, scorer.await_count


def test_a_clear_leader_skips_the_cross_encoder_only_when_configured(monkeypatch):
    out, calls = rerank(DOCS, monkeypatch)
    assert calls == 1                                                    # off by default: always rerank
    monkeypatch.setattr(settings, "RERANK_SKIP_MIN_SCORE", 0.6)
    monkeypatch.setattr(settings, "RERANK_SKIP_MARGIN", 0.1)
    out, calls = rerank(DOCS, monkeypatch)
    assert calls == 0 and [d["id"] for d in out] == [1, 2] and "rerank_score" not in out[0]


def test_a_narrow_lead_or_a_low_score_still_goes_to_the_cross_encoder(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_SKIP_MIN_SCORE", 0.6)
    monkeypatch.setattr(settings, "RERANK_SKIP_MARGIN", 0.1)
    assert rerank(CLOSE, monkeypatch)[1] == 1
    weak = [{"id": 1, "content": "a", "vector_score": 0.5}, {"id": 2, "content": "b", "vector_score": 0.1}]
    assert rerank(weak, monkeypatch)[1] == 1


# ---- measuring relevance with an LLM ------------------------------------------------------------------------------------------------------

def test_ndcg_rewards_the_best_chunk_being_first():
    assert ndcg_at([2, 0, 0, 0, 0]) == 1.0
    assert 0 < ndcg_at([0, 0, 2, 0, 0]) < 1.0
    assert ndcg_at([0, 0, 0]) == 0.0 and ndcg_at([]) == 0.0
    assert ndcg_at([1, 2]) < ndcg_at([2, 1])


def test_judged_metrics_count_any_relevant_chunk_not_only_the_source_chunk():
    metrics = judged_metrics([[0, 2, 0, 0, 0, 0, 0, 0, 0, 0], [1, 1, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 2]])
    assert metrics["answer_hit@5"] == 0.25               # the grade-2 chunk of the first question is at rank 2: inside; the last one's at rank 6: outside
    assert metrics["related_hit@5"] == 0.5
    assert metrics["precision@5"] == pytest.approx((1 / 5 + 2 / 5) / 4, abs=1e-3)


class JudgeLLM:
    """Grades a passage 2 when it mentions the answer word, 0 otherwise; one reply is unreadable."""

    def __init__(self):
        self.calls = 0

    async def chat_completion(self, **kw):
        self.calls += 1
        prompt = kw["messages"][0]["content"]
        text = "not json" if "garbled" in prompt else json.dumps({"grade": 2 if "thirty" in prompt.split("Passage:")[1] else 0})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class JudgedStore:
    async def search(self, query, top_k=10, plan=None, **kw):
        return [
            {"filename": "a.pdf", "section_title": "Other", "content": "unrelated fees text"},
            {"filename": "a.pdf", "section_title": "Notice", "content": "notice is thirty days"},   # another chunk that answers it
            {"filename": "a.pdf", "section_title": "Garbled", "content": "garbled"},
        ]


class JudgedPlanner:
    async def plan(self, question, transcript, session_id):
        return QueryPlan(question)


def test_an_llm_grades_every_retrieved_chunk_and_an_unreadable_verdict_never_counts_as_a_hit():
    data = {"answerable": [{"question": "thời hạn thông báo?", "filename": "a.pdf", "section_title": "NotThere"}]}
    llm = JudgeLLM()
    result = asyncio.run(evaluate_judged(JudgedStore(), JudgedPlanner(), llm, data, 5))
    assert llm.calls == 3 and result["questions"] == 1
    assert result["answer_hit@5"] == 1.0                  # a chunk other than the source states the answer...
    assert result["exact_chunk_hit@5"] == 0.0             # ...which "is it the source chunk" would have called a miss
    assert 0 < result["ndcg@5"] < 1.0                     # it is at rank 2, not 1
