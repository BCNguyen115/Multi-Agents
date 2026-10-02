"""Knowledge-base upload from the chat: 200-600 character section chunks, same rows as the folder ingestion."""
import asyncio
import io
from types import SimpleNamespace

import numpy as np
import pytest
from docx import Document

from src.ingestion.chunker import chunk_documents
from src.ingestion.document_loader import Section, load_and_analyze_documents, load_document
from src.ingestion.embedder import IngestionEmbedder
from src.ingestion.upload import (
    MAX_SECTION,
    MIN_SECTION,
    UploadError,
    build_upload_chunks,
    infer_category,
    ingest_upload,
    merge_short_sections,
    safe_category,
    safe_filename,
    split_oversized,
)

SENTENCE = "The supplier shall deliver the goods on time. "


def prose(n: int) -> str:
    return (SENTENCE * (n // len(SENTENCE) + 1))[:n].rstrip()


def docx_bytes(paragraphs: list[str]) -> bytes:
    buffer = io.BytesIO()
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


# A1 and A2 are short enough to need merging; A3 is far over 600; A5 is a short tail.
SECTIONED = [
    "ARTICLE 1 Scope", prose(60),
    "ARTICLE 2 Delivery", prose(300),
    "ARTICLE 3 Fees", prose(1500),
    "ARTICLE 4 Term", prose(300),
    "ARTICLE 5 Law", prose(40),
]


def section(title: str, size: int, start: int = 0) -> Section:
    return Section(title, prose(size), start, start + size)


# ------------------------------------------------------------------ merge / truncate rules
def test_a_section_under_200_is_merged_with_the_next_one():
    merged, folded = merge_short_sections([section("A", 100), section("B", 300), section("C", 400)])
    assert [s.title for s in merged] == ["A + B", "C"] and folded == 1
    assert len(merged[0].content) >= MIN_SECTION


def test_a_short_run_keeps_merging_until_it_reaches_200():
    merged, folded = merge_short_sections([section("A", 60), section("B", 60), section("C", 60), section("D", 300)])
    assert [s.title for s in merged] == ["A + B + C + D"] and folded == 3


def test_a_short_last_section_joins_the_previous_one_only_when_nothing_is_cut():
    fits, _ = merge_short_sections([section("A", 300), section("B", 100)])
    assert [s.title for s in fits] == ["A + B"]
    too_big, _ = merge_short_sections([section("A", 590), section("B", 100)])
    assert [s.title for s in too_big] == ["A", "B"]


def test_sections_already_in_range_are_left_alone():
    sections = [section("A", 200), section("B", 600), section("C", 450)]
    merged, folded = merge_short_sections(sections)
    assert [s.title for s in merged] == ["A", "B", "C"] and folded == 0


def test_a_long_section_is_split_into_similar_pieces_and_nothing_is_lost():
    text = prose(2000)
    pieces = split_oversized(text)
    assert len(pieces) == 4 and all(MIN_SECTION <= len(p) <= MAX_SECTION for p in pieces)
    assert "".join(pieces).replace(" ", "") == text.replace(" ", "")  # every character is still there, in order
    assert "".join(split_oversized("x" * 900)) == "x" * 900  # no boundary at all: still lossless
    assert split_oversized("short") == ["short"]


# ------------------------------------------------------------------ chunks
def sectioned_document(category: str = "msa", tmp_path=None):
    path = tmp_path / "contract.docx"
    path.write_bytes(docx_bytes(SECTIONED))
    return load_document(str(path), category)


def test_every_chunk_is_between_200_and_600_characters_and_the_long_article_is_kept_whole(tmp_path):
    chunks, report = build_upload_chunks(sectioned_document(tmp_path=tmp_path))
    # A1+A2 merged, A3 (1500 chars) split in three, A4+A5 merged: 5 chunks, none of the 1500 characters dropped
    assert report.sections == 5 and report.merged == 2 and report.split == 1 and report.chunks == 5
    assert all(MIN_SECTION <= len(c.raw_content) <= MAX_SECTION for c in chunks)
    fees = [c.raw_content for c in chunks if c.metadata["section_title"] == "ARTICLE 3 Fees"]
    assert len(fees) == 3 and len("".join(fees).replace(" ", "")) >= 0.95 * len(prose(1500).replace(" ", ""))
    assert [c.metadata["section_title"] for c in chunks][0].startswith("ARTICLE 1 Scope + ARTICLE 2 Delivery")


def test_chunks_carry_the_contextual_prefix_like_existing_ones(tmp_path):
    chunks, _ = build_upload_chunks(sectioned_document(tmp_path=tmp_path))
    for chunk in chunks:
        title = chunk.metadata["section_title"]
        assert chunk.content == f"[Source: contract.docx - Section: {title}]\n\n{chunk.raw_content}"


def test_upload_rows_match_the_folder_ingestion_of_the_same_file(tmp_path):
    folder = tmp_path / "dataset" / "msa"
    folder.mkdir(parents=True)
    (folder / "contract.docx").write_bytes(docx_bytes(SECTIONED))
    existing = chunk_documents(load_and_analyze_documents(str(tmp_path / "dataset")))
    uploaded, _ = build_upload_chunks(load_document(str(folder / "contract.docx"), "msa"))

    # same stored columns, same identity: only the number/size of chunks differs (by request)
    columns = ("filename", "category", "doc_key", "doc_hash", "detected_pattern")
    assert {k: existing[0].metadata[k] for k in columns} == {k: uploaded[0].metadata[k] for k in columns}
    assert set(existing[0].metadata) - {"chunk_method"} == set(uploaded[0].metadata) - {"chunk_method"}
    assert existing[0].content.startswith("[Source: contract.docx - Section: ") and uploaded[0].content.startswith("[Source: contract.docx - Section: ")


def test_prose_without_headings_is_split_without_losing_text(tmp_path):
    path = tmp_path / "memo.docx"
    paragraph = prose(1500)
    path.write_bytes(docx_bytes([paragraph, paragraph]))
    doc = load_document(str(path), "general")
    chunks, report = build_upload_chunks(doc)
    assert doc.detected_pattern == "none" and report.split == 0
    assert all(len(c.raw_content) <= MAX_SECTION for c in chunks)
    stored = "".join(c.raw_content for c in chunks).replace(" ", "").replace("\n", "")
    assert len(stored) >= 0.95 * len((paragraph * 2).replace(" ", ""))  # splitter whitespace aside, everything is there


# ------------------------------------------------------------------ names and categories
def test_filenames_are_reduced_to_a_safe_base_name_and_the_type_is_checked():
    assert safe_filename("..\\..\\etc/passwd.pdf") == "passwd.pdf"
    assert safe_filename("Hợp đồng (v2).docx") == "Hợp đồng (v2).docx"
    with pytest.raises(UploadError):
        safe_filename("notes.exe")
    with pytest.raises(UploadError):
        safe_filename("")


def test_categories_are_slugs_and_inferred_from_the_name_or_first_page():
    assert safe_category("  NDA / Legal!! ") == "nda-legal" and safe_category("???") is None and safe_category(None) is None
    assert infer_category("acme_nda_2024.pdf", "", ["nda", "msa"]) == "nda"
    assert infer_category("x.pdf", "MASTER SERVICES AGREEMENT between...", []) == "msa"
    assert infer_category("x.pdf", "STATEMENT OF WORK no. 4", []) == "sow"
    assert infer_category("x.pdf", "lunch menu", ["nda"]) == "general"


# ------------------------------------------------------------------ pipeline
class FakePG:
    def __init__(self):
        self.stored: dict[str, str] = {}
        self.counts: dict[str, int] = {}

    async def fetch(self, sql, *args, **kw):
        if "count(*)" in sql:
            return [{"n": self.counts.get(args[0], 0)}]
        return [{"doc_key": k, "doc_hash": v} for k, v in self.stored.items()]


class FakeEmbedder(IngestionEmbedder):
    def __init__(self, fail: bool = False):
        super().__init__(FakePG(), openai_client=None)
        self.fail, self.written = fail, []

    async def embed_all_chunks(self, chunks, batch_size=100, session_id="INGESTION"):
        if self.fail:
            raise RuntimeError("embedding api down")
        return np.random.default_rng(1).normal(size=(len(chunks), 64)).astype(np.float32)

    async def replace_document(self, doc_key, chunks, embeddings, session_id="INGESTION"):
        self.written.append((doc_key, chunks))
        self.pg.stored[doc_key] = chunks[0].metadata["doc_hash"]
        self.pg.counts[doc_key] = len(chunks)
        return len(chunks)


def run_upload(embedder, data, name="contract.docx", category=None, tmp_path=None, **kw):
    return asyncio.run(ingest_upload(embedder, name, data, category=category, dataset_dir=str(tmp_path) if tmp_path else None, **kw))


def test_upload_adds_then_recognises_an_identical_file_then_updates_a_changed_one(tmp_path):
    embedder = FakeEmbedder()
    data = docx_bytes(SECTIONED)

    first = run_upload(embedder, data, category="msa", tmp_path=tmp_path)
    assert first["status"] == "added" and first["chunks"] == 5 and first["merged"] == 2 and first["split"] == 1
    assert first["doc_key"] == "msa/contract.docx" and first["saved_to_dataset"]
    assert (tmp_path / "msa" / "contract.docx").read_bytes() == data  # kept so run_ingestion --prune/--reset retain it

    again = run_upload(embedder, data, category="msa", tmp_path=tmp_path)
    assert again["status"] == "unchanged" and again["chunks"] == 0 and len(embedder.written) == 1

    changed = run_upload(embedder, docx_bytes(SECTIONED + ["ARTICLE 6 Extra", prose(400)]), category="msa", tmp_path=tmp_path)
    assert changed["status"] == "updated" and changed["replaced_chunks"] == 5 and len(embedder.written) == 2


def test_category_is_inferred_when_not_given(tmp_path):
    result = run_upload(FakeEmbedder(), docx_bytes(["MASTER SERVICES AGREEMENT", *SECTIONED]), name="acme.docx", tmp_path=tmp_path)
    assert result["category"] == "msa" and result["doc_key"] == "msa/acme.docx"


def test_unreadable_files_and_embedding_failures_are_reported_not_half_stored(tmp_path):
    with pytest.raises(UploadError):
        run_upload(FakeEmbedder(), b"not a docx at all", tmp_path=tmp_path)
    with pytest.raises(UploadError, match="giới hạn"):
        run_upload(FakeEmbedder(), docx_bytes(SECTIONED), tmp_path=tmp_path, max_chunks=2)
    failing = FakeEmbedder(fail=True)
    with pytest.raises(RuntimeError):
        run_upload(failing, docx_bytes(SECTIONED), tmp_path=tmp_path)
    assert failing.written == [] and not (tmp_path / "general").exists()


# ------------------------------------------------------------------ endpoint
class FakeFile:
    def __init__(self, name: str, data: bytes):
        self.filename, self._buffer = name, io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    from src.gateway import main

    store = SimpleNamespace(known=["msa"], invalidated=0)

    async def known_categories(session_id="N/A"):
        return store.known

    store.known_categories = known_categories
    store.invalidate_categories = lambda: setattr(store, "invalidated", store.invalidated + 1)
    monkeypatch.setattr(main, "knowledge_store", store)
    monkeypatch.setattr(main, "knowledge_embedder", FakeEmbedder())
    monkeypatch.setattr(main.settings, "KNOWLEDGE_DIR", str(tmp_path))
    return main, store


def call(main, principal, file, category=None):
    return asyncio.run(main.upload_knowledge(file=file, session_id="s1", category=category, principal=principal))


def test_endpoint_stores_the_document_and_describes_it_in_chat_words(gateway):
    main, store = gateway
    principal = main.Principal(user_id="anonymous", tenant_id="t", department_id="d")
    response = call(main, principal, FakeFile("contract.docx", docx_bytes(SECTIONED)), category="MSA")
    assert response.status == "added" and response.category == "msa" and response.chunks == 5 and response.session_id == "s1"
    assert "thêm mới" in response.message and "chia thành nhiều đoạn" in response.message and "gộp" in response.message
    assert store.invalidated == 1  # a new category is recognised in questions at once


def test_endpoint_refuses_callers_without_the_knowledge_role_and_bad_files(gateway):
    main, _ = gateway
    reader = main.Principal(user_id="bob", tenant_id="t", department_id="d", roles=frozenset({"approver"}), authenticated=True)
    with pytest.raises(main.HTTPException) as denied:
        call(main, reader, FakeFile("contract.docx", docx_bytes(SECTIONED)))
    assert denied.value.status_code == 403
    admin = main.Principal(user_id="amy", tenant_id="t", department_id="d", roles=frozenset({"admin"}), authenticated=True)
    assert call(main, admin, FakeFile("contract.docx", docx_bytes(SECTIONED)), category="msa").status == "added"
    with pytest.raises(main.HTTPException) as bad:
        call(main, admin, FakeFile("notes.exe", b"hello"))
    assert bad.value.status_code == 400


def test_endpoint_size_limit_and_middleware_cover_the_new_route(gateway, monkeypatch):
    main, _ = gateway
    monkeypatch.setattr(main.settings, "KNOWLEDGE_MAX_FILE_MB", 1)
    principal = main.Principal(user_id="anonymous", tenant_id="t", department_id="d")
    with pytest.raises(main.HTTPException) as big:
        call(main, principal, FakeFile("big.pdf", b"0" * (2 * 1024 * 1024)))
    assert big.value.status_code == 413

    async def call_next(_request):
        return "passed"

    request = SimpleNamespace(url=SimpleNamespace(path="/api/knowledge/upload"), headers={"content-length": str(5 * 1024 * 1024)})
    assert asyncio.run(main.reject_oversized_uploads(request, call_next)).status_code == 413
