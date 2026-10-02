"""Ingestion: header/footer stripping, page numbers, structure detection, per-document dedup, incremental sync."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import numpy as np

from src.ingestion.chunker import DocumentChunk, chunk_documents
from src.ingestion.document_loader import (
    SectionedDocument,
    _detect_best_pattern,
    _join_pages,
    _split_into_sections,
    _strip_repeated_lines,
)
from src.ingestion.embedder import IngestionEmbedder, _find_duplicates


# ------------------------------------------------------------------ loader
def _pages(n: int) -> list[str]:
    return [f"ACME CONFIDENTIAL\nUnique body text of page {i} with its own words {i * 7}.\nPage {i} of {n}" for i in range(1, n + 1)]


def test_running_headers_and_page_numbers_are_removed_but_content_stays():
    cleaned = _strip_repeated_lines(_pages(6))
    assert all("ACME CONFIDENTIAL" not in p and "Page " not in p for p in cleaned)
    assert cleaned[2] == "Unique body text of page 3 with its own words 21."


def test_short_documents_are_left_alone():
    assert _strip_repeated_lines(_pages(3)) == _pages(3)


def test_page_offsets_point_at_each_page_start():
    text, starts = _join_pages(["alpha", "bravo", "charlie"])
    assert [text[s:s + 5] for s in starts] == ["alpha", "bravo", "charl"]


def test_documents_without_headings_report_none_instead_of_a_fake_pattern():
    assert _detect_best_pattern("just a flat paragraph of prose with nothing to split on") == (None, "none")
    pattern, name = _detect_best_pattern("ARTICLE 1 Term\nbody\nARTICLE 2 Fees\nbody")
    assert name == "ARTICLE" and pattern is not None
    assert [s.title for s in _split_into_sections("no headings here", None, "none")] == ["Full Document"]


# ------------------------------------------------------------------ chunker
def _document(pages: list[str]) -> SectionedDocument:
    text, starts = _join_pages(pages)
    pattern, name = _detect_best_pattern(text)
    return SectionedDocument(
        filename="x.pdf", filepath="/x.pdf", category="nda", raw_text=text, sections=_split_into_sections(text, pattern, name),
        detected_pattern=name, metadata={"filename": "x.pdf", "category": "nda", "doc_key": "nda/x.pdf", "doc_hash": "h1", "page_starts": starts},
    )


def test_chunks_know_their_page_and_carry_document_identity():
    filler = "The parties agree to the following obligations in detail. " * 20
    doc = _document([f"ARTICLE 1 Term\n{filler}", f"ARTICLE 2 Fees\n{filler}", f"ARTICLE 3 Notices\n{filler}"])
    chunks = chunk_documents([doc])
    assert [c.metadata["page"] for c in chunks] == [1, 2, 3]
    assert all(c.metadata["doc_key"] == "nda/x.pdf" and c.metadata["doc_hash"] == "h1" and "page_starts" not in c.metadata for c in chunks)
    assert [c.metadata["chunk_index"] for c in chunks] == [0, 1, 2]


def test_unstructured_documents_use_the_fallback_splitter_with_pages():
    body = "Plain prose without any headings at all. " * 300
    chunks = chunk_documents([_document([body[: len(body) // 2], body[len(body) // 2:]])])
    assert len(chunks) > 1 and {c.metadata["chunk_method"] for c in chunks} == {"fallback_recursive"}
    assert chunks[0].metadata["page"] == 1 and chunks[-1].metadata["page"] == 2


# ------------------------------------------------------------------ embedder
class FakeConn:
    def __init__(self, log):
        self.log = log

    async def execute(self, sql, *args):
        self.log.append(("execute", sql.split()[0], args[:1]))

    async def executemany(self, sql, rows):
        self.log.append(("insert", len(rows)))


class FakePG:
    def __init__(self, stored=None):
        self.stored, self.log = stored or {}, []

    async def fetch(self, sql, *args, **kw):
        return [{"doc_key": k, "doc_hash": v} for k, v in self.stored.items()]

    @asynccontextmanager
    async def transaction(self):
        yield FakeConn(self.log)

    async def execute(self, sql, *args, **kw):
        self.log.append(("pg-execute", sql.split()[0]))
        return "DELETE 0"


class FakeOpenAI:
    """Embedding = 1-hot of the text's first letter, so equal texts have cosine 1."""

    def __init__(self, fail_on: str = ""):
        self.fail_on = fail_on
        self.embeddings = SimpleNamespace(create=self._create)

    async def _create(self, model, input):
        if any(self.fail_on and self.fail_on in t for t in input):
            raise RuntimeError("embedding failed")
        vectors = []
        for text in input:
            v = [0.0] * 8
            v[ord(text.strip("[")[0].lower()) % 8] = 1.0
            vectors.append(SimpleNamespace(embedding=v))
        return SimpleNamespace(data=vectors)


def _chunk(doc_key: str, doc_hash: str, text: str, index: int = 0) -> DocumentChunk:
    category, filename = doc_key.split("/")
    return DocumentChunk(content=text, raw_content=text, metadata={
        "doc_key": doc_key, "doc_hash": doc_hash, "filename": filename, "category": category, "section_title": "S", "chunk_index": index, "page": 1,
    })


def test_duplicates_are_removed_inside_one_document_only():
    embedder = IngestionEmbedder(FakePG(), FakeOpenAI())
    same = np.array([[1, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    chunks = [_chunk("nda/a.pdf", "h", t, i) for i, t in enumerate(["x", "x2", "y"])]
    kept, vectors, removed = embedder.deduplicate(chunks, same)
    assert removed == 1 and len(kept) == 2 and vectors.shape == (2, 3)
    assert _find_duplicates(np.eye(3)) == set()

    async def two_documents():
        pg = FakePG()
        stats = await IngestionEmbedder(pg, FakeOpenAI()).ingest([_chunk("nda/a.pdf", "h1", "same clause"), _chunk("msa/b.pdf", "h2", "same clause")])
        return stats, pg.log

    stats, log = asyncio.run(two_documents())
    assert stats["inserted"] == 2 and stats["removed"] == 0  # the same clause in two contracts stays citable from both
    assert [e for e in log if e[0] == "insert"] == [("insert", 1), ("insert", 1)]


def test_unchanged_documents_are_skipped_and_changed_ones_replaced_atomically():
    pg = FakePG(stored={"nda/a.pdf": "h1", "nda/b.pdf": "old"})
    chunks = [_chunk("nda/a.pdf", "h1", "alpha"), _chunk("nda/b.pdf", "new", "bravo"), _chunk("nda/c.pdf", "h3", "charlie")]
    stats = asyncio.run(IngestionEmbedder(pg, FakeOpenAI()).ingest(chunks))
    assert (stats["docs_skipped"], stats["docs_ingested"], stats["inserted"]) == (1, 2, 2)
    replaced = [e for e in pg.log if e[0] == "execute"]
    assert [e[2] for e in replaced] == [("nda/b.pdf",), ("nda/c.pdf",)]  # delete-then-insert per changed document only


def test_one_failing_document_does_not_stop_the_others_and_is_reported():
    pg = FakePG()
    chunks = [_chunk("nda/a.pdf", "h1", "alpha"), _chunk("nda/bad.pdf", "h2", "BOOM text"), _chunk("nda/c.pdf", "h3", "charlie")]
    stats = asyncio.run(IngestionEmbedder(pg, FakeOpenAI(fail_on="BOOM")).ingest(chunks))
    assert stats["failed"] == ["nda/bad.pdf"] and stats["docs_ingested"] == 2 and stats["inserted"] == 2


def test_prune_only_runs_when_asked():
    pg = FakePG()
    asyncio.run(IngestionEmbedder(pg, FakeOpenAI()).ingest([_chunk("nda/a.pdf", "h1", "alpha")]))
    assert ("pg-execute", "DELETE") not in pg.log
    asyncio.run(IngestionEmbedder(pg, FakeOpenAI()).ingest([_chunk("nda/a.pdf", "h1", "alpha")], prune=True))
    assert ("pg-execute", "DELETE") in pg.log
