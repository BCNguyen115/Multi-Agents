"""Quote-grounded answers: the evidence block is parsed, every quote is checked against its source, nothing of it is previewed."""
import asyncio

import pytest

from src.agents.rag_agent.agent import RAGAgent
from src.agents.rag_agent.evidence import VisibleText, check_quotes, quote_in_source, split_evidence
from src.config import settings
from src.orchestrator.core import Orchestrator
from tests.test_answer_streaming import StreamingLLM, agent, drained, generate_with_sink
from tests.test_rag_agent import FakeLLM, FakeStore, ask, chunk

RAW = "The term of this Agreement is two (2) years. Payment is due within thirty (30) days of receipt of the invoice."
ANSWER = 'Thời hạn là 2 năm [1].\n<evidence>\n[1] "The term of this Agreement is two (2) years"\n</evidence>'


@pytest.fixture
def quotes_on(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUOTE_MODE", True)


# ---- parsing ------------------------------------------------------------------------------------------------------------------------------

def test_the_evidence_block_is_split_off_in_every_quote_style():
    raw = 'Phí trong 30 ngày [2].\n<evidence>\n[1] "The term is two years"\n[2] “payable within thirty days”\n[3] plain text without quote marks here\n</evidence>'
    answer, quotes = split_evidence(raw)
    assert answer == "Phí trong 30 ngày [2]."
    assert quotes == [(1, "The term is two years"), (2, "payable within thirty days"), (3, "plain text without quote marks here")]


def test_a_block_cut_off_by_the_length_limit_still_counts_and_no_block_changes_nothing():
    answer, quotes = split_evidence('Trả lời [1].\n<evidence>\n[1] "The term of this Agreement is')
    assert answer == "Trả lời [1]." and quotes == [(1, "The term of this Agreement is")]
    assert split_evidence("Chỉ có câu trả lời [1].") == ("Chỉ có câu trả lời [1].", [])


# ---- checking ------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("quote, found", [
    ("The term of this Agreement is two (2) years", True),
    ("the TERM of  this\nAgreement is two (2) years", True),            # case and whitespace do not matter
    ('"Payment is due within thirty (30) days"', True),                  # quote marks do not matter
    ("The term of this Agreement ... of receipt of the invoice", True),   # an ellipsis joins two pieces of the same source
    ("The term of this Agreement is three (3) years", False),             # one changed word
    ("is due", False),                                                    # occurs in the source but is too short to prove anything
    ("Totally invented sentence that is not in the source", False),
])
def test_a_quote_must_occur_in_its_source(quote, found):
    assert quote_in_source(quote, RAW) is found


def test_quotes_are_checked_against_the_source_they_name():
    sources = [RAW, "Fees are as set out in Schedule A attached hereto."]
    valid = check_quotes([(1, "The term of this Agreement is two (2) years"), (2, "The term of this Agreement is two (2) years"), (9, "anything at all here")], sources)
    assert valid == {1: ["The term of this Agreement is two (2) years"]}  # the same words are not in source 2; source 9 does not exist


# ---- the preview never shows the block --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("pieces", [
    ["Thời hạn là 2 năm [1].\n", '<evidence>\n[1] "The term"\n</evidence>'],
    ["Thời hạn là 2 năm [1].\n<evid", 'ence>\n[1] "The term"\n</evidence>'],
    list('Thời hạn là 2 năm [1].\n<evidence>\n[1] "The term"\n</evidence>'),   # one character at a time
    ["Thời hạn là 2 năm [1].\n<EVIDENCE>\n[1] x\n</EVIDENCE>"],
])
def test_nothing_from_the_evidence_marker_on_is_ever_released(pieces):
    visible = VisibleText()
    shown = "".join(visible.feed(p) for p in pieces) + visible.flush()
    assert shown == "Thời hạn là 2 năm [1].\n"


def test_text_that_only_looks_like_the_start_of_the_marker_is_released_at_the_end():
    visible = VisibleText()
    shown = visible.feed("Điều <evid") + visible.flush()
    assert shown == "Điều <evid"


def test_the_streamed_preview_has_no_evidence_but_the_returned_text_has_it(quotes_on):
    queue = asyncio.Queue()
    pieces = ["Thời hạn là 2 ", "năm [1].\n<evid", 'ence>\n[1] "The term', ' of this Agreement is two (2) years"\n</evidence>']
    answer, _ = generate_with_sink(agent(StreamingLLM(*pieces)), queue)
    assert "".join(d["text"] for _, d in drained(queue)) == "Thời hạn là 2 năm [1].\n"
    assert "<evidence>" in answer  # process_request splits it off afterwards


def test_with_the_mode_off_the_stream_is_forwarded_untouched(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUOTE_MODE", False)
    queue = asyncio.Queue()
    answer, _ = generate_with_sink(agent(StreamingLLM("Thời hạn ", "là 2 năm [1].")), queue)
    assert "".join(d["text"] for _, d in drained(queue)) == answer == "Thời hạn là 2 năm [1]."


# ---- the agent --------------------------------------------------------------------------------------------------------------------------------

def test_a_verified_quote_is_attached_to_its_source_and_the_block_is_not_part_of_the_answer(quotes_on):
    llm = FakeLLM(ANSWER)
    out = ask(RAGAgent(FakeStore([chunk(1, raw_content=RAW)]), llm))
    assert out["answer"] == "Thời hạn là 2 năm [1]."
    assert out["sources"][0]["quote"] == "The term of this Agreement is two (2) years"
    assert out["verification"]["quotes"] == {"asked": 1, "valid": 1} and out["verification"]["unquoted_citations"] == []
    assert "<evidence>" in llm.calls[-1]["messages"][0]["content"]  # the rule is in the prompt only in this mode


def test_a_made_up_quote_does_not_verify_the_citation(quotes_on):
    answer = 'Thời hạn là 2 năm [1].\n<evidence>\n[1] "The term of this Agreement is forever and ever"\n</evidence>'
    out = ask(RAGAgent(FakeStore([chunk(1, raw_content=RAW)]), FakeLLM(answer)))
    assert "quote" not in out["sources"][0]
    assert out["verification"]["unquoted_citations"] == [1] and out["verification"]["quotes"] == {"asked": 1, "valid": 0}


def test_sources_cited_inside_the_evidence_block_are_not_citations_of_the_answer(quotes_on):
    answer = 'Thời hạn là 2 năm [1].\n<evidence>\n[1] "The term of this Agreement is two (2) years"\n[2] "Fees are as set out in Schedule A"\n</evidence>'
    out = ask(RAGAgent(FakeStore([chunk(1, raw_content=RAW), chunk(2, raw_content="Fees are as set out in Schedule A.")]), FakeLLM(answer)))
    assert [s["cite"] for s in out["sources"]] == [1] and out["verification"]["cited"] == [1]


def test_without_the_mode_nothing_changes(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUOTE_MODE", False)
    llm = FakeLLM("Thời hạn là 2 năm [1].")
    out = ask(RAGAgent(FakeStore([chunk(1)]), llm))
    assert "quotes" not in out["verification"] and "quote" not in out["sources"][0]
    assert "<evidence>" not in llm.calls[-1]["messages"][0]["content"]


# ---- the Verifier ---------------------------------------------------------------------------------------------------------------------------------

def test_the_verifier_only_demands_quotes_when_told_to():
    verification = {"status": "ok", "grounded": True, "cited": [1], "unsupported_numbers": [], "unquoted_citations": [1]}
    assert Orchestrator._rag_verdict(verification, 0)["is_verified"] is True
    strict = Orchestrator._rag_verdict(verification, 0, require_quotes=True)
    assert strict["is_verified"] is False and "[1]" in strict["verifier_feedback"]
    assert Orchestrator._rag_verdict({**verification, "unquoted_citations": []}, 0, require_quotes=True)["is_verified"] is True
