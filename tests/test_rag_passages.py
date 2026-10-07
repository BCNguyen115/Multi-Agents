"""Small-to-big retrieval: passages are cut, stored with their chunk, searched, mapped back, and read by the reranker."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import numpy as np

from src.agents.rag_agent.knowledge import KnowledgeStore, fuse
from src.config import settings
from src.ingestion.chunker import DocumentChunk
from src.ingestion.embedder import IngestionEmbedder
from src.ingestion.passages import MIN_CHUNK_FOR_PASSAGES, PASSAGE_CHARS, split_passages
from src.shared.reranker_client import rerank_text
from tests.test_rag_upgrades import EmbeddingLLM

LONG = " ".join(f"Sentence number {i} says something about clause {i}." for i in range(80))


# ---- cutting ------------------------------------------------------------------------------------------------------------------------------

def test_a_short_chunk_is_not_split_and_a_long_one_is_covered_by_overlapping_windows():
    assert split_passages("short " * 20) == []
    assert len(LONG) > MIN_CHUNK_FOR_PASSAGES
    passages = split_passages(LONG)
    assert len(passages) > 3 and all(len(p) <= PASSAGE_CHARS for p in passages)
    for i in (0, 40, 79):                              # nothing is lost: every sentence is in some passage
        assert any(f"Sentence number {i} says" in p for p in passages)


# ---- storing ------------------------------------------------------------------------------------------------------------------------------

class Conn:
    def __init__(self, log):
        self.log, self.next_id = log, 100

    async def execute(self, sql, *a):
        self.log.append(("execute", sql.split()[0]))

    async def fetchval(self, sql, *row):
        self.next_id += 1
        self.log.append(("chunk", self.next_id))
        return self.next_id

    async def executemany(self, sql, rows):
        self.log.append(("passages" if "rag_passages" in sql else "chunks", rows))


class PG:
    def __init__(self):
        self.log = []

    @asynccontextmanager
    async def transaction(self):
        yield Conn(self.log)


class OpenAI:
    class embeddings:  # noqa: N801
        @staticmethod
        async def create(**kw):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in kw["input"]])


def chunks():
    return [DocumentChunk(content="c1", raw_content=LONG, metadata={"filename": "a.pdf"}),
            DocumentChunk(content="c2", raw_content="a short chunk", metadata={"filename": "a.pdf"})]


def test_with_the_switch_off_only_chunks_are_written(monkeypatch):
    monkeypatch.setattr(settings, "RAG_INDEX_PASSAGES", False)
    pg = PG()
    asyncio.run(IngestionEmbedder(pg, OpenAI()).replace_document("nda/a.pdf", chunks(), np.zeros((2, 2), dtype=np.float32)))
    assert [entry[0] for entry in pg.log] == ["execute", "chunks"]


def test_with_the_switch_on_each_passage_is_stored_under_the_id_of_its_chunk(monkeypatch):
    monkeypatch.setattr(settings, "RAG_INDEX_PASSAGES", True)
    pg = PG()
    asyncio.run(IngestionEmbedder(pg, OpenAI()).replace_document("nda/a.pdf", chunks(), np.zeros((2, 2), dtype=np.float32)))
    kinds = [entry[0] for entry in pg.log]
    assert kinds == ["execute", "chunk", "chunk", "passages"]
    rows = pg.log[-1][1]
    assert rows and {row[0] for row in rows} == {101}                      # only the long chunk has passages; its id is 101
    assert [row[1] for row in rows] == list(range(len(rows)))               # in order


# ---- searching ------------------------------------------------------------------------------------------------------------------------------

def test_fusion_carries_the_passage_that_matched_to_the_chunk():
    chunk_hit = {"id": 1, "content": "c", "vector_score": 0.5}
    passage_hit = {"id": 1, "content": "c", "vector_score": 0.7, "best_passage": "the matching window"}
    fused = fuse([[chunk_hit], [passage_hit]], 60, 5)
    assert fused[0]["best_passage"] == "the matching window" and fused[0]["vector_score"] == 0.7


class PassagePG:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def fetch(self, sql, *args, **kw):
        self.calls.append(sql)
        if "DISTINCT category" in sql or "rag_meta" in sql:
            return []
        if "rag_passages" in sql:
            if self.fail:
                raise RuntimeError('relation "rag_passages" does not exist')
            return [{"id": 7, "best_passage": "the notice period is thirty days", "vector_score": 0.8},
                    {"id": 7, "best_passage": "a weaker window", "vector_score": 0.4},
                    {"id": 9, "best_passage": "fees are due monthly", "vector_score": 0.6}]
        if "ANY($1::bigint[])" in sql:
            return [{"id": 7, "content": "chunk 7", "raw_content": "chunk 7", "fts_score": 0.0}, {"id": 9, "content": "chunk 9", "raw_content": "chunk 9", "fts_score": 0.0}]
        return []


def search(store):
    return asyncio.run(store.search("notice period", top_k=5))


def test_passage_hits_are_mapped_back_to_their_chunk_with_the_best_passage_kept(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "raw")
    monkeypatch.setattr(settings, "RAG_PASSAGE_SEARCH", True)
    rows = search(KnowledgeStore(PassagePG(), EmbeddingLLM()))
    assert [r["id"] for r in rows] == [7, 9]
    assert rows[0]["best_passage"] == "the notice period is thirty days" and rows[0]["vector_score"] == 0.8
    assert rows[0]["content"] == "chunk 7"                                   # the answer is still written from the whole chunk


def test_without_the_switch_the_passages_are_not_touched(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "raw")
    monkeypatch.setattr(settings, "RAG_PASSAGE_SEARCH", False)
    pg = PassagePG()
    search(KnowledgeStore(pg, EmbeddingLLM()))
    assert not any("rag_passages" in sql for sql in pg.calls)


def test_a_database_without_the_passage_table_searches_chunks_only_and_stops_asking(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUERY_MODE", "raw")
    monkeypatch.setattr(settings, "RAG_PASSAGE_SEARCH", True)
    pg = PassagePG(fail=True)
    store = KnowledgeStore(pg, EmbeddingLLM())
    search(store)
    asked = sum("rag_passages" in sql for sql in pg.calls)
    search(store)
    assert store._passages_ok is False and sum("rag_passages" in sql for sql in pg.calls) == asked


# ---- reranking ------------------------------------------------------------------------------------------------------------------------------------

def test_the_reranker_reads_the_matching_passage_and_falls_back_to_a_window():
    doc = {"content": "x" * 3000, "raw_content": "intro " * 400 + "the notice period is thirty days", "best_passage": "the notice period is thirty days"}
    assert rerank_text(doc, "notice period", 1000, "passage") == "the notice period is thirty days"
    no_passage = {k: v for k, v in doc.items() if k != "best_passage"}
    assert "notice period" in rerank_text(no_passage, "notice period", 200, "passage")   # a keyword-only hit: the best window instead
    assert rerank_text(doc, "q", 1000, "content").startswith("x")                           # the default is untouched
