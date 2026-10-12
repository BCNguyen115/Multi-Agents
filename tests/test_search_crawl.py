"""SearchAgent reads result pages with Scrapling: HTTP first, the browser only for near-empty pages, and only public hosts.

No network: the fetchers and DNS are fakes, so these run anywhere (the live behaviour was checked by hand against real sites).
"""
import asyncio
import socket
from unittest.mock import MagicMock

import pytest

from src.agents.search_agent.agent import SearchAgent

DNS = {"news.example": "93.184.216.34", "evil.example": "10.0.0.5"}  # evil.example is a public-looking name pointing inside


class Page:
    def __init__(self, status=200, text="x" * 500, headers=None):
        self.status, self.text = status, text
        self.headers = headers if headers is not None else {"Content-Type": "text/html; charset=utf-8"}

    def markdown(self, **_):
        return self.text


class FakeHTTP:
    pages: dict = {}
    calls: list = []

    @classmethod
    async def get(cls, url, **_):
        cls.calls.append(url)
        return cls.pages[url]


class FakeBrowser:
    page = None  # a Page, or an Exception to raise
    calls: list = []

    @classmethod
    async def async_fetch(cls, url, **_):
        cls.calls.append(url)
        if isinstance(cls.page, Exception):
            raise cls.page
        return cls.page


@pytest.fixture
def crawl(monkeypatch):
    FakeHTTP.pages, FakeHTTP.calls, FakeBrowser.page, FakeBrowser.calls = {}, [], Page(text="y" * 400), []
    monkeypatch.setattr("scrapling.fetchers.AsyncFetcher", FakeHTTP)
    monkeypatch.setattr("scrapling.fetchers.DynamicFetcher", FakeBrowser)
    real = socket.getaddrinfo

    def fake_dns(host, *args, **kwargs):
        if host in DNS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (DNS[host], 0))]
        return real(host, *args, **kwargs)  # IP literals resolve to themselves, offline

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    agent = SearchAgent(MagicMock(), MagicMock(TAVILY_API_KEY="x", OPENROUTER_MODEL="m"))
    return lambda *urls: asyncio.run(agent._scrape_urls(list(urls)))


def test_a_normal_page_is_read_over_http_and_cut_to_3000_characters(crawl):
    FakeHTTP.pages["https://news.example/a"] = Page(text="word " * 2000)
    assert len(crawl("https://news.example/a")["https://news.example/a"]) == 3000
    assert FakeBrowser.calls == []


def test_a_nearly_empty_page_is_read_again_in_the_browser(crawl):
    FakeHTTP.pages["https://news.example/js"] = Page(text="Loading...")
    assert crawl("https://news.example/js")["https://news.example/js"] == "y" * 400
    assert FakeBrowser.calls == ["https://news.example/js"]


def test_without_a_browser_the_http_text_is_kept(crawl):
    FakeHTTP.pages["https://news.example/js"] = Page(text="Loading...")
    FakeBrowser.page = RuntimeError("Executable doesn't exist")  # an image built with INSTALL_BROWSER=false
    assert crawl("https://news.example/js")["https://news.example/js"] == "Loading..."


def test_missing_and_non_html_pages_come_back_empty_without_a_browser(crawl):
    FakeHTTP.pages["https://news.example/gone"] = Page(status=404)
    FakeHTTP.pages["https://news.example/file.pdf"] = Page(headers={"content-type": "application/pdf"})
    assert crawl("https://news.example/gone", "https://news.example/file.pdf") == {
        "https://news.example/gone": "",
        "https://news.example/file.pdf": "",
    }
    assert FakeBrowser.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/health",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://redis.internal/",
        "http://evil.example/",  # a public-looking name that resolves to 10.0.0.5
        "ftp://news.example/x",
        "file:///etc/passwd",
    ],
)
def test_addresses_that_are_not_public_web_hosts_are_never_fetched(crawl, url):
    assert crawl(url) == {url: ""}
    assert FakeHTTP.calls == [] and FakeBrowser.calls == []


def test_a_redirect_is_followed_by_hand_and_every_hop_is_vetted(crawl):
    FakeHTTP.pages["http://news.example/old"] = Page(status=301, headers={"Location": "https://news.example/new"})
    FakeHTTP.pages["https://news.example/new"] = Page(text="z" * 600)
    assert crawl("http://news.example/old")["http://news.example/old"] == "z" * 600

    FakeHTTP.calls.clear()
    FakeHTTP.pages["https://news.example/trap"] = Page(status=302, headers={"location": "http://169.254.169.254/latest/"})
    assert crawl("https://news.example/trap") == {"https://news.example/trap": ""}
    assert FakeHTTP.calls == ["https://news.example/trap"]  # the metadata address was never requested


def test_a_redirect_loop_ends(crawl):
    FakeHTTP.pages["https://news.example/loop"] = Page(status=302, headers={"location": "/loop"})
    assert crawl("https://news.example/loop") == {"https://news.example/loop": ""}
    assert len(FakeHTTP.calls) == 4  # the first request and three redirects


def test_one_bad_page_does_not_lose_the_others(crawl):
    FakeHTTP.pages["https://news.example/ok"] = Page(text="k" * 700)  # /boom is missing from the fake: its fetch raises KeyError
    out = crawl("https://news.example/ok", "https://news.example/boom")
    assert out == {"https://news.example/ok": "k" * 700, "https://news.example/boom": ""}
