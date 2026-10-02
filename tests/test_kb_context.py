"""Contextual retrieval: an LLM-written sentence per chunk, stored in content, never in raw_content."""
import asyncio
from types import SimpleNamespace

from src.agents.rag_agent.agent import RAGAgent
from src.config import settings
from src.ingestion.context import CONTEXT_MARK, apply_context, contextualize_chunks, generate_context
from src.ingestion.upload import build_upload_chunks, ingest_upload

from tests.test_kb_upload import FakeEmbedder, SECTIONED, docx_bytes, sectioned_document


class FakeLLM:
    def __init__(self, reply="Hợp đồng dịch vụ giữa ACME và Beta; đoạn này nói về thời hạn giao hàng.", fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

    async def chat_completion(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("llm down")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


PREFIX = "[Source: a.pdf - Section: ARTICLE 2]\n\n"


def test_the_context_goes_between_the_prefix_and_the_text_and_raw_content_is_untouched():
    out = apply_context(PREFIX + "The term is 24 months.", "The term is 24 months.", "Master services agreement, term clause.")
    assert out == PREFIX + "[Context: Master services agreement, term clause.]\n\nThe term is 24 months."


def test_applying_a_context_twice_replaces_it_instead_of_stacking():
    once = apply_context(PREFIX + "Text.", "Text.", "first")
    twice = apply_context(once, "Text.", "second")
    assert twice.count(CONTEXT_MARK) == 1 and "second" in twice and "first" not in twice


def test_no_context_means_no_change():
    assert apply_context(PREFIX + "Text.", "Text.", "") == PREFIX + "Text."


def test_brackets_in_the_model_answer_cannot_break_the_marker():
    out = asyncio.run(generate_context(FakeLLM("About [Annex A] and [1]"), "doc", "S", "passage"))
    assert "[" not in out and "]" not in out


def test_a_failing_model_costs_nothing_but_the_context():
    assert asyncio.run(generate_context(FakeLLM(fail=True), "doc", "S", "passage")) == ""


def test_every_chunk_of_a_document_gets_its_own_call_and_only_content_changes(tmp_path):
    chunks, _ = build_upload_chunks(sectioned_document(tmp_path=tmp_path))
    raw_before = [c.raw_content for c in chunks]
    llm = FakeLLM()
    added = asyncio.run(contextualize_chunks(llm, "ARTICLE 1 ... the whole agreement starts here", chunks))
    assert added == len(chunks) == len(llm.calls)
    assert [c.raw_content for c in chunks] == raw_before
    assert all(c.content.startswith("[Source:") and CONTEXT_MARK in c.content and c.content.endswith(c.raw_content) for c in chunks)
    assert llm.calls[0]["metadata"]["purpose"] == "kb_chunk_context"


def test_an_upload_adds_contexts_only_when_the_option_is_on(tmp_path, monkeypatch):
    data = docx_bytes(SECTIONED)
    off, on = FakeEmbedder(), FakeEmbedder()
    monkeypatch.setattr(settings, "KB_LLM_CONTEXT", False)
    llm = FakeLLM()
    result = asyncio.run(ingest_upload(off, "c.docx", data, category="msa", dataset_dir=str(tmp_path), llm_client=llm))
    assert result["contextualized"] == 0 and llm.calls == []
    monkeypatch.setattr(settings, "KB_LLM_CONTEXT", True)
    result = asyncio.run(ingest_upload(on, "d.docx", data, category="msa", dataset_dir=str(tmp_path), llm_client=llm))
    assert result["contextualized"] == result["chunks"] == len(llm.calls)
    assert all(CONTEXT_MARK in c.content for c in on.written[0][1])


def test_the_citation_snippet_shows_the_document_text_not_the_generated_context():
    chunk = {"content": "[Source: a.pdf - Section: S]\n\n[Context: A sentence from the model.]\n\nThe term is 24 months.",
             "filename": "a.pdf", "section_title": "S", "category": "nda", "page": 1}
    assert RAGAgent._source(1, chunk)["snippet"] == "The term is 24 months."
