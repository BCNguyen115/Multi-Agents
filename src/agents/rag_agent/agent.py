"""RAG Agent — Retrieval-Augmented Generation agent.

Inherits from ``BaseAgent``.  Processing flow:
  1. Receive user query.
  2. Retrieve relevant context from the pgvector knowledge store.
  3. Send query + context to OpenRouter (gpt-4o-mini) for answer generation.
  4. Return the LLM response (or a friendly fallback message on error).

Usage:
    from src.agents.rag_agent.agent import RAGAgent

    agent = RAGAgent(knowledge_store=ks, openai_client=client, model="gpt-4o-mini")
    answer = await agent.process_request("What is pgvector?", session_id="abc")
"""

import json
import logging
from typing import Any, List, Tuple

from src.agents.base_agent import BaseAgent
from src.agents.rag_agent.knowledge import KnowledgeStore
from src.config import settings
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.reranker_client import rerank_documents

logger: logging.Logger = get_logger(__name__)

# Fallback message returned when the LLM or DB is unavailable.
_FALLBACK_MESSAGE: str = (
    "Xin lỗi, tôi hiện không thể tra cứu tài liệu lúc này. "
    "Vui lòng thử lại sau hoặc liên hệ quản trị viên."
)

_RAG_SYSTEM_PROMPT: str = (
    "Bạn là trợ lý AI chuyên tra cứu tài liệu nội bộ. "
    "Dựa trên ngữ cảnh (context) được cung cấp dưới đây, hãy trả lời "
    "câu hỏi của người dùng một cách chính xác và ngắn gọn. "
    "Nếu ngữ cảnh không chứa đủ thông tin, hãy thông báo rõ ràng rằng "
    "bạn không tìm thấy tài liệu liên quan."
)


class RAGAgent(BaseAgent):
    """Retrieval-Augmented Generation agent.

    Combines vector-based document retrieval with LLM generation to
    answer questions grounded in an internal knowledge base.

    Attributes:
        knowledge_store: The ``KnowledgeStore`` instance for vector search.
        llm_client: Unified ``LLMClient`` instance (LiteLLM + Langfuse).
        model: LLM model identifier (default ``"gpt-4o-mini"``).
    """

    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        llm_client: LLMClient,
        model: str = "openai/gpt-4o-mini",
    ) -> None:
        """Initialise the RAG Agent.

        Args:
            knowledge_store: Pre-configured ``KnowledgeStore``.
            llm_client: Unified LLM client instance.
            model: Model ID to use for chat completion.
        """
        self.knowledge_store: KnowledgeStore = knowledge_store
        self.llm_client: LLMClient = llm_client
        self.model: str = model

    # ------------------------------------------------------------------
    # BaseAgent implementation
    # ------------------------------------------------------------------

    async def process_request(self, query: str, session_id: str) -> str:
        """Handle a document-retrieval query end-to-end.

        Steps:
          1. Search the knowledge store for relevant context & citations.
          2. Build a prompt with retrieved context.
          3. Call the LLM via OpenRouter.
          4. Return JSON containing the answer and source citations.

        Args:
            query: The user's natural-language question.
            session_id: Correlation ID for end-to-end tracing.

        Returns:
            str: JSON string with keys ``answer`` and ``sources``.
        """
        logger.info(
            "RAGAgent processing request (query len=%d)",
            len(query),
            extra={"session_id": session_id},
        )

        # ------ Step 1: Retrieve context & citations from vector DB ------
        context_text, sources = await self._retrieve_context(
            query, session_id=session_id
        )

        # ------ Step 2-3: Call LLM with context ------
        answer: str = await self._generate_answer(
            query, context_text, session_id=session_id
        )

        logger.info(
            "RAGAgent response generated (len=%d, sources=%d)",
            len(answer),
            len(sources),
            extra={"session_id": session_id},
        )

        result_payload: dict[str, Any] = {
            "answer": answer,
            "sources": sources,
        }
        return json.dumps(result_payload, ensure_ascii=False)

    def get_metadata(self) -> dict[str, str]:
        """Return metadata describing this agent's capabilities.

        The ``description`` is intentionally explicit and LLM-friendly
        so that the Orchestrator's intent classifier can reliably
        match document-retrieval queries to this agent.

        Returns:
            dict[str, str]: Agent metadata.
        """
        return {
            "name": "rag_agent",
            "description": (
                "Agent chuyên tra cứu và trả lời câu hỏi dựa trên tài liệu "
                "nội bộ, hợp đồng, NDA, SOW, MSA, quy trình, hoặc bất kỳ thông "
                "tin nào có trong cơ sở dữ liệu."
            ),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _retrieve_context(
        self, query: str, session_id: str
    ) -> Tuple[str, List[dict[str, str]]]:
        """Search the knowledge store using HyDE and format context + citations.

        Args:
            query: The user's query.
            session_id: Correlation ID.

        Returns:
            Tuple[str, List[dict[str, str]]]: Formatted context text and list of
            source dicts (file, section, category).
        """
        try:
            # 1. Hybrid Search (Vector + Full-Text Search) returning candidate pool (default 20)
            candidates_k: int = getattr(settings, "HYBRID_CANDIDATES_K", 20)
            top_k: int = getattr(settings, "RERANK_TOP_K", 5)

            raw_candidates: List[dict[str, Any]] = (
                await self.knowledge_store.search_with_hyde(
                    query=query, top_k=candidates_k, session_id=session_id
                )
            )

            # 2. TEI Cross-Encoder Reranking down to top_k (default 5) with graceful fallback
            results: List[dict[str, Any]] = await rerank_documents(
                query=query,
                documents=raw_candidates,
                top_k=top_k,
                session_id=session_id,
            )

            if not results:
                logger.info(
                    "No relevant documents found",
                    extra={"session_id": session_id},
                )
                return "(Không tìm thấy tài liệu liên quan trong cơ sở dữ liệu.)", []

            context_parts: List[str] = []
            sources: List[dict[str, str]] = []
            seen_sources: set[tuple[str, str]] = set()

            for i, doc in enumerate(results):
                filename: str = doc.get("filename", "")
                section: str = doc.get("section_title", "")
                category: str = doc.get("category", "")

                if filename:
                    key: tuple[str, str] = (filename, section)
                    if key not in seen_sources:
                        seen_sources.add(key)
                        sources.append(
                            {
                                "file": filename,
                                "section": section,
                                "category": category,
                            }
                        )

                source_info: str = ""
                if filename:
                    source_info = (
                        f"[Source: {filename} | "
                        f"Category: {category or 'N/A'} | "
                        f"Section: {section or 'N/A'}]"
                    )
                context_parts.append(
                    f"[Tài liệu {i + 1}] {source_info}\n{doc['content']}"
                )

            return "\n\n".join(context_parts), sources

        except Exception as exc:
            logger.error(
                "Context retrieval failed, proceeding without context: %s",
                exc,
                extra={"session_id": session_id},
            )
            return "(Lỗi khi tra cứu cơ sở dữ liệu. Không có ngữ cảnh bổ sung.)", []

    async def _generate_answer(
        self, query: str, context: str, session_id: str
    ) -> str:
        """Call the LLM with the user query and retrieved context.

        Args:
            query: The user's question.
            context: Retrieved context text.
            session_id: Correlation ID.

        Returns:
            str: LLM-generated answer, or ``_FALLBACK_MESSAGE`` on error.
        """
        user_prompt: str = (
            f"**Ngữ cảnh từ tài liệu:**\n{context}\n\n"
            f"**Câu hỏi của người dùng:**\n{query}"
        )

        try:
            response: Any = await self.llm_client.chat_completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": _RAG_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
                metadata={"agent": "rag_agent"},
                session_id=session_id,
            )

            answer: str = response.choices[0].message.content or ""
            logger.info(
                "LLM call successful (model=%s, len=%d)",
                self.model,
                len(answer),
                extra={"session_id": session_id},
            )
            return answer

        except Exception as exc:
            logger.error(
                "Error during LLM call in RAGAgent: %s",
                exc,
                extra={"session_id": session_id},
            )
            return _FALLBACK_MESSAGE
