"""Knowledge module — HyDE-enhanced semantic search via pgvector.

Provides:
  1. Generate text embeddings via the OpenRouter-compatible API.
  2. Store document embeddings in PostgreSQL (pgvector).
  3. **HyDE (Hypothetical Document Embeddings)**: generate a hypothetical
     answer before embedding for improved retrieval accuracy.
  4. Query the ``rag_chunks`` table for semantically similar documents.

Usage:
    from src.agents.rag_agent.knowledge import KnowledgeStore

    ks = KnowledgeStore(pg_client=pg, llm_client=llm_client)
    await ks.ensure_table()
    docs = await ks.search_with_hyde("What is the termination clause?",
                                      session_id="abc")
"""

import json
import logging
from typing import Any, List, Optional

from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.postgres_client import PostgresClient

logger: logging.Logger = get_logger(__name__)

# Default embedding model available via OpenRouter.
_EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
_EMBEDDING_DIM: int = 1536

# HyDE configuration
_HYDE_SYSTEM_PROMPT: str = (
    "You are an expert legal document analyst. Given a user's question, "
    "write a detailed, factual paragraph that would be found in a legal "
    "document (such as an NDA, MSA, Purchase Agreement, SOW, or Corporate "
    "Agreement) that directly answers the question. "
    "Write as if you are quoting from the actual document. "
    "Do NOT say 'I think' or 'In my opinion'. Just write the document text."
)
_HYDE_MODEL: str = "openai/gpt-4o-mini"

# SQL templates -----------------------------------------------------------

_CREATE_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id        BIGSERIAL PRIMARY KEY,
    content   TEXT NOT NULL,
    embedding VECTOR({dim})
);
""".format(dim=_EMBEDDING_DIM)

_INSERT_DOC_SQL: str = """
INSERT INTO knowledge_documents (content, embedding)
VALUES ($1, $2::vector);
"""

# Legacy search on knowledge_documents
_SEARCH_SQL: str = """
SELECT content,
       embedding <=> $1::vector AS distance
FROM   knowledge_documents
ORDER  BY distance
LIMIT  $2;
"""

# Vector search on rag_chunks (with rich metadata)
_SEARCH_RAG_CHUNKS_SQL: str = """
SELECT content,
       filename,
       category,
       section_title,
       embedding <=> $1::vector AS distance
FROM   rag_chunks
ORDER  BY distance
LIMIT  $2;
"""

# Hybrid search on rag_chunks (Vector + Full-Text Search with Weighted Score)
_HYBRID_SEARCH_RAG_CHUNKS_SQL: str = """
SELECT content,
       filename,
       category,
       section_title,
       (1 - (embedding <=> $1::vector)) AS vector_score,
       COALESCE(ts_rank_cd(to_tsvector('english', content), websearch_to_tsquery('english', $2)), 0) AS fts_score,
       (0.7 * (1 - (embedding <=> $1::vector)) + 0.3 * COALESCE(ts_rank_cd(to_tsvector('english', content), websearch_to_tsquery('english', $2)), 0)) AS combined_score
FROM   rag_chunks
ORDER  BY combined_score DESC
LIMIT  $3;
"""


class KnowledgeStore:
    """Manages document storage and semantic retrieval via pgvector.

    Supports both legacy ``knowledge_documents`` and the new ``rag_chunks``
    table populated by the ingestion pipeline.

    Attributes:
        pg: PostgreSQL async client instance.
        llm_client: Unified ``LLMClient`` instance (LiteLLM + Langfuse).
    """

    def __init__(
        self,
        pg: PostgresClient,
        llm_client: LLMClient,
    ) -> None:
        """Initialise the knowledge store.

        Args:
            pg: An already-connected ``PostgresClient``.
            llm_client: Unified LLM client instance.
        """
        self.pg: PostgresClient = pg
        self.llm_client: LLMClient = llm_client

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    async def ensure_table(self, session_id: str = "SYSTEM") -> None:
        """Create the ``knowledge_documents`` table if it does not exist.

        Also ensures the HNSW index on ``rag_chunks`` is created for
        optimised vector search performance.

        Args:
            session_id: Correlation ID for logging.
        """
        try:
            await self.pg.execute(
                _CREATE_TABLE_SQL, session_id=session_id
            )
            logger.info(
                "knowledge_documents table verified / created",
                extra={"session_id": session_id},
            )
        except Exception as exc:
            logger.error(
                "Failed to ensure knowledge_documents table: %s",
                exc,
                extra={"session_id": session_id},
            )
            raise

        # Ensure HNSW index for accelerated vector search
        await self._ensure_hnsw_index(session_id=session_id)

    async def _ensure_hnsw_index(self, session_id: str = "SYSTEM") -> None:
        """Create HNSW index on ``rag_chunks.embedding`` if not exists.

        HNSW (Hierarchical Navigable Small World) provides sub-linear
        approximate nearest-neighbour search, dramatically reducing query
        latency compared to sequential scan on large vector tables.

        Index parameters:
          - ``m = 16``: Maximum number of connections per layer.
          - ``ef_construction = 64``: Size of dynamic candidate list during build.

        Args:
            session_id: Correlation ID for logging.
        """
        hnsw_sql: str = (
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_hnsw "
            "ON rag_chunks "
            "USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64);"
        )
        try:
            await self.pg.execute(hnsw_sql, session_id=session_id)
            logger.info(
                "HNSW index on rag_chunks.embedding verified / created",
                extra={"session_id": session_id},
            )
        except Exception as exc:
            # Non-fatal: table may not exist yet (created by ingestion pipeline)
            logger.warning(
                "HNSW index creation skipped (table may not exist yet): %s",
                exc,
                extra={"session_id": session_id},
            )

    # ------------------------------------------------------------------
    # Embedding generation
    # ------------------------------------------------------------------

    async def _embed_text(
        self, text: str, session_id: str = "N/A"
    ) -> List[float]:
        """Generate an embedding vector for the given text.

        Args:
            text: Input text to embed.
            session_id: Correlation ID for logging.

        Returns:
            List[float]: Embedding vector of dimension ``_EMBEDDING_DIM``.
        """
        try:
            embedding: List[float] = await self.llm_client.embedding(
                input_text=text,
                model=_EMBEDDING_MODEL,
                metadata={"purpose": "rag_search"},
                session_id=session_id,
            )
            logger.debug(
                "Generated embedding (dim=%d) for text len=%d",
                len(embedding),
                len(text),
                extra={"session_id": session_id},
            )
            return embedding
        except Exception as exc:
            logger.error(
                "Embedding generation failed: %s",
                exc,
                extra={"session_id": session_id},
            )
            raise

    # ------------------------------------------------------------------
    # HyDE — Hypothetical Document Generation
    # ------------------------------------------------------------------

    async def _generate_hypothetical_document(
        self, query: str, session_id: str = "N/A"
    ) -> str:
        """Use an LLM to generate a hypothetical document for HyDE.

        Instead of embedding the raw user query, HyDE first generates a
        hypothetical answer passage, which is then embedded for retrieval.

        Args:
            query: The user's natural-language question.
            session_id: Correlation ID.

        Returns:
            Generated hypothetical document text. Falls back to the raw
            query if generation fails.
        """
        try:
            response: Any = await self.llm_client.chat_completion(
                model=_HYDE_MODEL,
                messages=[
                    {"role": "system", "content": _HYDE_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                temperature=0.7,
                max_tokens=512,
                metadata={"purpose": "hyde_generation"},
                session_id=session_id,
            )
            hypothetical: str = response.choices[0].message.content or ""
            logger.info(
                "HyDE generated hypothetical doc (%d chars) for query: %s",
                len(hypothetical),
                query[:80],
                extra={"session_id": session_id},
            )
            return hypothetical
        except Exception as exc:
            logger.warning(
                "HyDE generation failed, falling back to raw query: %s",
                exc,
                extra={"session_id": session_id},
            )
            return query

    # ------------------------------------------------------------------
    # Document ingestion (legacy)
    # ------------------------------------------------------------------

    async def add_document(
        self, content: str, session_id: str = "N/A"
    ) -> None:
        """Embed and store a single document in the vector store.

        Args:
            content: Raw document text.
            session_id: Correlation ID for logging.
        """
        embedding: List[float] = await self._embed_text(
            content, session_id=session_id
        )
        embedding_str: str = json.dumps(embedding)

        try:
            await self.pg.execute(
                _INSERT_DOC_SQL,
                content,
                embedding_str,
                session_id=session_id,
            )
            logger.info(
                "Document stored (len=%d chars)",
                len(content),
                extra={"session_id": session_id},
            )
        except Exception as exc:
            logger.error(
                "Failed to store document: %s",
                exc,
                extra={"session_id": session_id},
            )
            raise

    # ------------------------------------------------------------------
    # Semantic search (legacy — knowledge_documents table)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 3,
        session_id: str = "N/A",
    ) -> List[dict[str, Any]]:
        """Search the knowledge base for documents similar to *query*.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return.
            session_id: Correlation ID for logging.

        Returns:
            List[dict[str, Any]]: List of dicts with keys ``content``
            and ``distance``.
        """
        try:
            query_embedding: List[float] = await self._embed_text(
                query, session_id=session_id
            )
            embedding_str: str = json.dumps(query_embedding)

            rows = await self.pg.fetch(
                _SEARCH_SQL,
                embedding_str,
                top_k,
                session_id=session_id,
            )

            results: List[dict[str, Any]] = [
                {"content": row["content"], "distance": float(row["distance"])}
                for row in rows
            ]
            logger.info(
                "Vector search returned %d results for query len=%d",
                len(results),
                len(query),
                extra={"session_id": session_id},
            )
            return results

        except Exception as exc:
            logger.error(
                "Vector search failed: %s",
                exc,
                extra={"session_id": session_id},
            )
            raise

    # ------------------------------------------------------------------
    # HyDE-enhanced search (rag_chunks table)
    # ------------------------------------------------------------------

    async def search_with_hyde(
        self,
        query: str,
        top_k: int = 20,
        session_id: str = "N/A",
    ) -> List[dict[str, Any]]:
        """Search the rag_chunks table using HyDE-enhanced Hybrid Search.

        Flow:
          1. Generate a hypothetical document via LLM.
          2. Embed the hypothetical document (not the raw query).
          3. Query pgvector + FTS for top_k candidate chunks.

        Args:
            query: User's natural-language question.
            top_k: Maximum number of raw candidate results to fetch.
            session_id: Correlation ID.

        Returns:
            List of candidate dicts with ``content``, ``filename``, ``category``,
            ``section_title``, and score metadata.
        """
        try:
            # Step 1: HyDE — generate hypothetical answer
            hypothetical: str = await self._generate_hypothetical_document(
                query, session_id=session_id
            )

            # Step 2: Embed the hypothetical document
            hyde_embedding: List[float] = await self._embed_text(
                hypothetical, session_id=session_id
            )
            embedding_str: str = json.dumps(hyde_embedding)

            # Step 3: Query rag_chunks via Hybrid Search (Vector + FTS)
            try:
                rows = await self.pg.fetch(
                    _HYBRID_SEARCH_RAG_CHUNKS_SQL,
                    embedding_str,
                    query,
                    top_k,
                    session_id=session_id,
                )
                results: List[dict[str, Any]] = [
                    {
                        "content": row["content"],
                        "filename": row["filename"],
                        "category": row["category"],
                        "section_title": row["section_title"],
                        "vector_score": float(row["vector_score"]),
                        "fts_score": float(row["fts_score"]),
                        "combined_score": float(row["combined_score"]),
                    }
                    for row in rows
                ]
            except Exception as sql_exc:
                logger.warning(
                    "Hybrid search query failed (%s), falling back to vector search",
                    sql_exc,
                    extra={"session_id": session_id},
                )
                rows = await self.pg.fetch(
                    _SEARCH_RAG_CHUNKS_SQL,
                    embedding_str,
                    top_k,
                    session_id=session_id,
                )
                results = [
                    {
                        "content": row["content"],
                        "filename": row["filename"],
                        "category": row["category"],
                        "section_title": row["section_title"],
                        "distance": float(row["distance"]),
                    }
                    for row in rows
                ]

            logger.info(
                "HyDE Hybrid search returned %d candidates (query: %s)",
                len(results),
                query[:60],
                extra={"session_id": session_id},
            )
            return results

        except Exception as exc:
            logger.error(
                "HyDE search failed: %s",
                exc,
                extra={"session_id": session_id},
            )
            # Fallback: try legacy search
            logger.warning(
                "Falling back to legacy search",
                extra={"session_id": session_id},
            )
            return await self.search(query, top_k=top_k, session_id=session_id)
