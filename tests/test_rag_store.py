"""Hybrid retrieval: pure helpers always; SQL/migration/filters against a real pgvector DB when RAG_TEST_DSN is set."""
import asyncio
import os

import pytest

from src.agents.rag_agent.knowledge import KnowledgeStore, build_tsquery, detect_categories, fuse
from src.config import settings


# ------------------------------------------------------------------ pure helpers
def test_tsquery_is_an_or_of_distinct_words_and_cannot_be_injected():
    assert build_tsquery("What is the term of the NDA? term!") == "'what' | 'the' | 'term' | 'nda'"
    hostile = build_tsquery("x'); DROP TABLE rag_chunks; -- & | ! <->")
    assert hostile == "'drop' | 'table' | 'rag_chunks'"  # only \w words survive
    assert build_tsquery("a b ?") is None
    assert build_tsquery("một hai ba bốn năm sáu bảy tám chín mười", max_terms=3).count("|") == 2


def test_categories_named_in_the_question_are_detected_as_whole_words():
    known = ["nda", "sow", "msa", "purchase"]
    assert detect_categories("Thời hạn của NDA và SOW là gì?", known) == ["nda", "sow"]
    assert detect_categories("sowing and msa123 are not categories", known) == []
    assert detect_categories("anything", []) == []


def test_fusion_ranks_by_agreement_and_keeps_the_best_scores():
    vector = [{"id": 1, "vector_score": 0.9}, {"id": 2, "vector_score": 0.8}, {"id": 3, "vector_score": 0.5}]
    keyword = [{"id": 3, "vector_score": 0.5, "fts_score": 0.02}, {"id": 2, "vector_score": 0.8, "fts_score": 0.01}]
    fused = fuse([vector, keyword], k=60, limit=10)
    # id3: 1/63 + 1/61, id2: 1/62 + 1/62, id1: 1/61 only
    assert [r["id"] for r in fused] == [3, 2, 1]
    by_id = {r["id"]: r for r in fused}
    assert by_id[3]["fts_score"] == 0.02 and by_id[1]["fts_score"] == 0.0 and by_id[2]["vector_score"] == 0.8
    assert by_id[2]["rrf_score"] == pytest.approx(2 / 62)
    assert len(fuse([vector], k=60, limit=2)) == 2


def test_a_plan_supplies_the_hyde_passage_without_another_llm_call(monkeypatch):
    from src.agents.rag_agent.planner import QueryPlan

    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "both")
    embedded, statements = [], []

    class LLM:
        async def embedding(self, input_text=None, **kw):
            embedded.append(input_text)
            return [0.0, 0.0, 0.0]

        async def chat_completion(self, **kw):
            raise AssertionError("the plan already carries the HyDE passage")

    class PG:
        async def fetch(self, sql, *args, session_id=None):
            statements.append((sql, args))
            return []

    plan = QueryPlan("Thời hạn bảo mật?", "The confidentiality obligations last five years.")
    asyncio.run(KnowledgeStore(PG(), LLM()).search("Thời hạn bảo mật?", top_k=5, categories=[], plan=plan))
    assert embedded == ["Thời hạn bảo mật?", "The confidentiality obligations last five years."]  # the question as typed + the passage
    assert any("to_tsquery" in sql for sql, _ in statements)


def test_without_a_passage_in_the_plan_the_store_writes_its_own(monkeypatch):
    from src.agents.rag_agent.planner import QueryPlan

    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "both")
    asked = []

    class LLM:
        async def embedding(self, input_text=None, **kw):
            return [0.0, 0.0, 0.0]

        async def chat_completion(self, **kw):
            asked.append(kw["metadata"]["purpose"])
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "A passage."})()})()]})()

    class PG:
        async def fetch(self, sql, *args, session_id=None):
            return []

    asyncio.run(KnowledgeStore(PG(), LLM()).search("Thời hạn?", top_k=5, categories=[], plan=QueryPlan("Thời hạn?")))
    assert asked == ["hyde_generation"]


# ------------------------------------------------------------------ real database
DSN = os.getenv("RAG_TEST_DSN")
needs_db = pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch pgvector database")


def _one_hot(text: str) -> list[float]:
    """Deterministic 1536-d 'embedding': the topic word decides the axis, so similarity is controllable."""
    axis = 0 if "termination" in text.lower() else 1 if "confidential" in text.lower() else 2
    vector = [0.0] * 1536
    vector[axis] = 1.0
    return vector


class TopicLLM:
    async def embedding(self, input_text=None, **kw):
        return _one_hot(input_text or "")

    async def chat_completion(self, **kw):
        raise AssertionError("HyDE must not run in raw mode")


@needs_db
def test_migration_search_filters_and_fallbacks_on_a_real_database(monkeypatch):
    from src.ingestion.schema import CREATE_TABLE_SQL, ensure_schema
    from src.shared.postgres_client import PostgresClient

    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "raw")
    monkeypatch.setattr(settings, "RAG_TENANT_IDS", None)

    async def scenario():
        pg = PostgresClient(dsn=DSN)
        await pg.connect(min_size=1, max_size=4)
        try:
            await pg.execute("DROP TABLE IF EXISTS rag_chunks")
            await pg.execute(CREATE_TABLE_SQL)  # the OLD schema: no doc_key/tsv, plus the redundant ivfflat index
            await pg.execute("CREATE INDEX idx_rag_chunks_embedding ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1)")
            rows = [
                ("Termination requires ninety days written notice.", "a.pdf", "nda", "Termination"),
                ("Confidential information must not be disclosed.", "a.pdf", "nda", "Confidentiality"),
                ("Termination for convenience by the customer.", "b.pdf", "msa", "Termination"),
                ("Payment is due within thirty days.", "c.pdf", "sow", "Payment"),
            ]
            for content, filename, category, section in rows:
                await pg.execute(
                    "INSERT INTO rag_chunks (content, raw_content, embedding, filename, category, section_title) VALUES ($1,$1,$2::vector,$3,$4,$5)",
                    content, str(_one_hot(content)), filename, category, section,
                )

            await ensure_schema(pg)
            await ensure_schema(pg)  # idempotent
            columns = {r["column_name"] for r in await pg.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='rag_chunks'")}
            assert {"doc_key", "doc_hash", "chunk_index", "page", "tenant_id", "tsv"} <= columns
            indexes = {r["indexname"] for r in await pg.fetch("SELECT indexname FROM pg_indexes WHERE tablename='rag_chunks'")}
            assert "idx_rag_chunks_embedding" not in indexes and {"idx_rag_chunks_hnsw", "idx_rag_chunks_tsv"} <= indexes

            # ensure_schema builds the frozen baseline (English tsv); the gateway and run_ingestion then apply the Alembic
            # revisions, and the search SQL (simple + unaccent) belongs to revision 0003: do the same here
            from src.shared.migrations import upgrade_to_head

            await asyncio.to_thread(upgrade_to_head, DSN)

            store = KnowledgeStore(pg, TopicLLM())
            hits = await store.search("termination notice period", top_k=5)
            assert hits[0]["content"].startswith("Termination requires ninety days")  # vector AND keywords agree
            assert hits[0]["vector_score"] == pytest.approx(1.0) and hits[0]["fts_score"] > 0

            # a natural, long question still finds keyword matches (OR semantics), unlike websearch_to_tsquery's AND
            long_question = "What is the payment timing that the SOW requires for the thirty day window?"
            assert any(h["fts_score"] > 0 for h in await store.search(long_question, top_k=5))

            # categories named in the question narrow the search ...
            assert {h["category"] for h in await store.search("NDA termination", top_k=5)} == {"nda"}
            # ... and a category with no chunks falls back to the whole corpus instead of returning nothing
            assert len(await store.search("termination", top_k=5, categories=["nonexistent"])) == 4

            # tenant restriction (hook)
            await pg.execute("UPDATE rag_chunks SET tenant_id='acme' WHERE filename='b.pdf'")
            monkeypatch.setattr(settings, "RAG_TENANT_IDS", ["public"])
            assert "b.pdf" not in {h["filename"] for h in await store.search("termination", top_k=5)}
            monkeypatch.setattr(settings, "RAG_TENANT_IDS", ["acme"])
            assert {h["filename"] for h in await store.search("termination", top_k=5)} == {"b.pdf"}
        finally:
            await pg.execute("DROP TABLE IF EXISTS rag_chunks")
            await pg.disconnect()

    asyncio.run(scenario())
