"""SearchAgent — Real-time Web Search and Crawling Agent.

Combines Tavily Search API with Crawl4AI async web scraper to retrieve
live web context and synthesize comprehensive answers using LLMClient.
"""

import asyncio
import logging
from typing import Any

from src.agents.base_agent import BaseAgent
from src.config import Settings
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_SYSTEM_PROMPT = """Bạn là một Chuyên gia Tìm kiếm và Phân tích Thông tin Web Thời gian thực (SearchAgent).
Nhiệm vụ: Tổng hợp câu trả lời chi tiết, chính xác dựa TRỰC TIẾP và CHỈ dựa trên thông tin tìm kiếm và cào dữ liệu được cung cấp dưới đây.

QUY TẮC BẮT BUỘC:
1. KHÔNG tự bịa đặt hay đưa ra giả định ngoài ngữ cảnh đã cào được.
2. Trình bày câu trả lời cấu trúc rõ ràng, chuyên nghiệp, súc tích.
3. BẮT BUỘC trích dẫn nguồn thông tin ở cuối bài viết theo định dạng Markdown link: `[Tên bài viết/Trang web](URL)`.

Dưới đây là thông tin cào được từ Web:
{web_context}
"""


class SearchAgent(BaseAgent):
    """Real-time Search Agent using Tavily API & Crawl4AI."""

    def __init__(
        self,
        llm_client: LLMClient,
        settings: Settings,
        model: str | None = None,
    ) -> None:
        self.llm_client: LLMClient = llm_client
        self.settings: Settings = settings
        self.tavily_api_key: str = settings.TAVILY_API_KEY
        self.model: str = model or settings.OPENROUTER_MODEL

    def get_metadata(self) -> dict[str, str]:
        return {
            "name": "search_agent",
            "description": (
                "Agent chuyên tìm kiếm Internet thời gian thực, "
                "đọc sâu các bài viết, tin tức, báo cáo mới nhất trên web để trả lời câu hỏi"
            ),
        }

    async def _search_tavily(self, query: str) -> list[dict[str, str]]:
        """Phase 1: Perform web search using Tavily API."""
        if not self.tavily_api_key or self.tavily_api_key.startswith("tvly-dev-dummy"):
            logger.warning("Tavily API key is missing or dummy.")
            return []

        try:
            from tavily import TavilyClient

            loop = asyncio.get_event_loop()
            client = TavilyClient(api_key=self.tavily_api_key)
            response = await loop.run_in_executor(
                None, lambda: client.search(query=query, max_results=3)
            )

            results: list[dict[str, str]] = []
            for item in response.get("results", []):
                results.append(
                    {
                        "title": item.get("title", "No Title"),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", ""),
                    }
                )
            return results
        except ImportError:
            logger.error("tavily-python package is not installed.")
            return []
        except Exception as exc:
            logger.error("Tavily search failed: %s", exc)
            return []

    async def _scrape_urls(self, urls: list[str]) -> dict[str, str]:
        """Phase 2: Deep crawl web pages using Crawl4AI AsyncWebCrawler."""
        scraped_data: dict[str, str] = {}
        if not urls:
            return scraped_data

        try:
            from crawl4ai import AsyncWebCrawler

            async with AsyncWebCrawler(verbose=False) as crawler:
                for url in urls:
                    try:
                        result = await asyncio.wait_for(
                            crawler.arun(url=url),
                            timeout=10.0,
                        )
                        if result and getattr(result, "markdown", None):
                            scraped_data[url] = str(result.markdown)[:3000]
                        else:
                            scraped_data[url] = ""
                    except asyncio.TimeoutError:
                        logger.warning("Crawling URL %s timed out after 10s", url)
                        scraped_data[url] = ""
                    except Exception as crawl_err:
                        logger.warning("Failed to crawl URL %s: %s", url, crawl_err)
                        scraped_data[url] = ""
        except ImportError:
            logger.error("crawl4ai package is not installed.")
        except Exception as exc:
            logger.error("Crawl4AI scraping error: %s", exc)

        return scraped_data

    async def process_request(self, query: str, session_id: str) -> str:
        """Process user search query end-to-end (Search -> Crawl -> Synthesis).

        Implements circuit breaker pattern: graceful degradation when external
        services (Tavily, Crawl4AI) are unavailable.
        """
        logger.info(
            "SearchAgent processing query: '%s'", query, extra={"session_id": session_id}
        )

        try:
            # Step 1: Tavily Search
            search_results = await self._search_tavily(query)

            if not search_results:
                fallback_msg = (
                    "⚠️ Dịch vụ tìm kiếm web tạm thời không khả dụng. "
                    "Nguyên nhân có thể do: thiếu TAVILY_API_KEY, hết quota API, "
                    "hoặc kết nối mạng bị gián đoạn. "
                    "Vui lòng thử lại sau hoặc liên hệ quản trị viên để kiểm tra cấu hình."
                )
                logger.warning(
                    "Search Agent fallback: Tavily returned no results",
                    extra={"session_id": session_id},
                )
                return fallback_msg

            # Step 2: Crawl top URLs (with graceful degradation)
            urls = [r["url"] for r in search_results if r.get("url")]
            try:
                crawled_content = await self._scrape_urls(urls)
            except Exception as crawl_exc:
                logger.warning(
                    "Crawl4AI fallback triggered: %s — using Tavily snippets only",
                    crawl_exc,
                    extra={"session_id": session_id},
                )
                crawled_content = {}

            # Combine context
            context_blocks: list[str] = []
            for res in search_results:
                title = res["title"]
                url = res["url"]
                snippet = res["snippet"]
                markdown = crawled_content.get(url, "")

                content = markdown if markdown else snippet
                context_blocks.append(
                    f"### Bài viết: [{title}]({url})\nURL: {url}\nNội dung:\n{content}\n"
                )

            web_context = "\n---\n".join(context_blocks)

            # Step 3: LLM Synthesis
            system_prompt = _SYSTEM_PROMPT.format(web_context=web_context)

            response: Any = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                model=self.model,
                temperature=0.3,
                max_tokens=1500,
                metadata={"agent": "search_agent"},
                session_id=session_id,
            )
            answer: str = response.choices[0].message.content or ""
            return answer

        except Exception as exc:
            logger.error(
                "SearchAgent process_request exception: %s",
                exc,
                extra={"session_id": session_id},
            )
            return (
                "⚠️ Dịch vụ tìm kiếm web tạm thời không khả dụng do lỗi nội bộ. "
                f"Chi tiết kỹ thuật: {type(exc).__name__}: {exc}. "
                "Vui lòng thử lại sau."
            )
