"""Web answers are verified against the pages the model was shown (links, then numbers), with no LLM judge."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.agents.search_agent.agent import SearchAgent
from src.agents.search_agent.verification import verify_web_answer
from src.orchestrator.core import Orchestrator

SOURCES = [
    {"title": "Giá dầu tăng", "url": "https://news.example/dau", "text": "Giá dầu Brent đạt 82,5 USD/thùng, tăng 3% so với tuần trước."},
    {"title": "OPEC", "url": "https://www.opec.example/a/", "text": "Sản lượng giảm 1,2 triệu thùng mỗi ngày."},
    {"title": "Lưu trữ", "url": "https://news.example/2031/05/luu-tru", "text": "Bài viết cũ."},
]


def verify(answer, question=""):
    return verify_web_answer(answer, SOURCES, question)


def test_an_answer_that_links_its_page_and_states_its_numbers_passes():
    v = verify("Dầu Brent đạt 82,5 USD/thùng, tăng 3% [Giá dầu tăng](https://news.example/dau).")
    assert v == {"kind": "web", "status": "ok", "grounded": True, "cited": [1], "unknown_urls": [], "unsupported_numbers": []}


def test_an_invented_link_is_reported_and_the_answer_is_not_grounded():
    v = verify("Dầu tăng [bài viết](https://bia.example/y) và [Giá dầu tăng](https://news.example/dau).")
    assert v["unknown_urls"] == ["https://bia.example/y"] and v["cited"] == [1] and v["grounded"] is False


def test_the_same_page_written_another_way_still_counts():
    v = verify("Sản lượng giảm 1,2 triệu thùng (http://opec.example/a#top).")  # other scheme, no www, no trailing slash, a fragment
    assert v["cited"] == [2] and v["grounded"] is True


LISTING = [
    {"title": "Công nghệ", "url": "https://tech.news.example/cong-nghe.html",
     "text": "Tin mới: Chip tự chế https://tech.news.example/chip-tu-che-post1.html và xem thêm https://evil.example/quang-cao nhé."},
]


def test_an_article_link_printed_by_a_section_page_on_its_own_site_counts_as_that_page():
    v = verify_web_answer("Chip tự chế [bài](https://tech.news.example/chip-tu-che-post1.html).", LISTING)  # the real failure: a listing page, its article links
    assert v["cited"] == [1] and v["unknown_urls"] == [] and v["grounded"] is True


def test_a_link_a_page_prints_but_that_points_to_another_site_is_still_unknown():
    v = verify_web_answer("Xem [quảng cáo](https://evil.example/quang-cao).", LISTING)
    assert v["unknown_urls"] == ["https://evil.example/quang-cao"] and v["grounded"] is False


def test_a_link_on_the_pages_site_that_the_page_never_prints_is_still_unknown():
    v = verify_web_answer("Xem [bài](https://tech.news.example/bai-bia-dat.html).", LISTING)
    assert v["unknown_urls"] == ["https://tech.news.example/bai-bia-dat.html"] and v["cited"] == []


def test_an_answer_without_any_link_is_not_grounded():
    v = verify("Dầu Brent đạt 82,5 USD/thùng.")
    assert v["cited"] == [] and v["grounded"] is False


def test_a_number_no_page_contains_is_reported():
    v = verify("Dầu Brent đạt 95 USD/thùng [Giá dầu tăng](https://news.example/dau).")
    assert v["unsupported_numbers"] == ["95"] and v["cited"] == [1]


def test_digits_of_an_address_and_numbers_of_the_question_are_not_claims():
    answer = "Năm 2024 dầu đạt 82,5 USD [Lưu trữ](https://news.example/2031/05/luu-tru)."
    assert verify(answer, "giá dầu năm 2024 là bao nhiêu")["unsupported_numbers"] == []
    assert verify(answer)["unsupported_numbers"] == ["2024"]  # without the question nobody said 2024


def ask(answer):
    llm = MagicMock()
    llm.chat_completion = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]))
    agent = SearchAgent(llm, MagicMock(TAVILY_API_KEY="x", OPENROUTER_MODEL="m"))
    agent._search_tavily = AsyncMock(return_value=[{"title": s["title"], "url": s["url"], "snippet": ""} for s in SOURCES])
    agent._scrape_urls = AsyncMock(return_value={s["url"]: s["text"] for s in SOURCES})
    return json.loads(asyncio.run(agent.process_request("Giá dầu hôm nay?", "s1")))


def test_the_agent_returns_its_answer_with_sources_and_the_verification():
    out = ask("Dầu Brent đạt 82,5 USD/thùng [Giá dầu tăng](https://news.example/dau).")
    assert out["answer"].startswith("Dầu Brent") and out["verification"]["grounded"] is True
    assert [s["url"] for s in out["sources"]] == [s["url"] for s in SOURCES]
    assert out["sources"][0]["domain"] == "news.example" and out["sources"][1]["domain"] == "opec.example"


def test_the_agent_flags_an_answer_that_invents_a_link_or_a_number():
    out = ask("Dầu đạt 95 USD [bài](https://bia.example/y).")
    assert out["verification"]["unknown_urls"] == ["https://bia.example/y"] and out["verification"]["unsupported_numbers"] == ["95"]


def test_the_verdict_accepts_a_grounded_answer_without_an_llm_judge():
    assert Orchestrator._web_verdict({"cited": [1], "unknown_urls": [], "unsupported_numbers": []}, 0) == {"is_verified": True, "verifier_feedback": ""}


def test_the_verdict_names_every_problem_and_spends_a_retry():
    verdict = Orchestrator._web_verdict({"cited": [], "unknown_urls": ["https://bia.example/y"], "unsupported_numbers": ["95"]}, 0)
    assert verdict["is_verified"] is False and verdict["retry_count"] == 1
    assert "bia.example" in verdict["verifier_feedback"] and "95" in verdict["verifier_feedback"]


def test_an_answer_with_no_citation_at_all_is_rejected():
    verdict = Orchestrator._web_verdict({"cited": [], "unknown_urls": [], "unsupported_numbers": []}, 1)
    assert verdict["is_verified"] is False and verdict["retry_count"] == 2 and "trích dẫn" in verdict["verifier_feedback"]
