"""HyDE (Hypothetical Document Embeddings) & FAISS Retrieval module.

Implements the HyDE technique: instead of embedding the raw user query,
an LLM first generates a hypothetical answer, which is then embedded and
used to search the FAISS vector store.

Usage:
    from src.retriever import HyDERetriever
    retriever = HyDERetriever.from_chunks(chunks, embeddings, ...)
    results = retriever.query("What is the termination clause?")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import openai
from langchain_openai import OpenAIEmbeddings

from src.chunker import DocumentChunk
from src.embedder import create_embeddings_model

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TOP_K: int = 5
HYDE_SYSTEM_PROMPT: str = (
    "You are an expert legal document analyst. Given a user's question, "
    "write a detailed, factual paragraph that would be found in a legal "
    "document (such as an NDA, MSA, Purchase Agreement, SOW, or Corporate "
    "Agreement) that directly answers the question. "
    "Write as if you are quoting from the actual document. "
    "Do NOT say 'I think' or 'In my opinion'. Just write the document text."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RetrievalResult:
    """A single retrieval result.

    Attributes:
        chunk: The matched document chunk.
        score: Similarity score (lower = more similar for L2; higher for IP).
        rank: 1-based rank in the result list.
    """

    chunk: DocumentChunk
    score: float
    rank: int


# ---------------------------------------------------------------------------
# HyDE Retriever
# ---------------------------------------------------------------------------


class HyDERetriever:
    """Retriever that uses HyDE (Hypothetical Document Embeddings).

    The retrieval flow:
      1. User sends a query.
      2. An LLM generates a *hypothetical document* that would answer the query.
      3. The hypothetical document is embedded.
      4. FAISS searches for the nearest real chunks to that embedding.

    Attributes:
        index: The FAISS index storing chunk embeddings.
        chunks: The ordered list of chunks (aligned with the index).
        embeddings_model: LangChain OpenAI embeddings model.
        llm_client: OpenAI async/sync client for HyDE generation.
        llm_model: Model name for HyDE generation.
        top_k: Default number of results to return.
    """

    def __init__(
        self,
        index: faiss.IndexFlatIP,
        chunks: list[DocumentChunk],
        embeddings_model: OpenAIEmbeddings,
        llm_client: openai.OpenAI,
        llm_model: str = "openai/gpt-4o-mini",
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        """Initialise the HyDE retriever.

        Args:
            index: Pre-built FAISS index.
            chunks: Chunk list aligned with the index rows.
            embeddings_model: Configured embedding model.
            llm_client: OpenAI client for HyDE generation.
            llm_model: LLM model identifier.
            top_k: Default number of results to return.
        """
        self.index: faiss.IndexFlatIP = index
        self.chunks: list[DocumentChunk] = chunks
        self.embeddings_model: OpenAIEmbeddings = embeddings_model
        self.llm_client: openai.OpenAI = llm_client
        self.llm_model: str = llm_model
        self.top_k: int = top_k

    # ---- Factory ----

    @classmethod
    def from_chunks(
        cls,
        chunks: list[DocumentChunk],
        embeddings: np.ndarray,
        api_key: str,
        base_url: str | None = None,
        embedding_model: str = "text-embedding-3-small",
        llm_model: str = "openai/gpt-4o-mini",
        top_k: int = DEFAULT_TOP_K,
    ) -> HyDERetriever:
        """Build a retriever from pre-computed chunks and embeddings.

        Args:
            chunks: List of document chunks.
            embeddings: Numpy array of shape ``(len(chunks), dim)``.
            api_key: API key for both embedding and LLM.
            base_url: Optional base URL for OpenRouter.
            embedding_model: Embedding model name.
            llm_model: LLM model name for HyDE generation.
            top_k: Default result count.

        Returns:
            Configured ``HyDERetriever`` instance.
        """
        # Build FAISS index (Inner Product on L2-normalised vectors)
        dim: int = embeddings.shape[1]
        index: faiss.IndexFlatIP = faiss.IndexFlatIP(dim)

        # Normalise embeddings for cosine similarity via inner product
        norms: np.ndarray = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normalised: np.ndarray = (embeddings / norms).astype(np.float32)
        index.add(normalised)

        logger.info("FAISS index built: %d vectors, dim=%d", index.ntotal, dim)

        # Build embedding model
        emb_model: OpenAIEmbeddings = create_embeddings_model(
            api_key=api_key, base_url=base_url, model=embedding_model
        )

        # Build LLM client
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        llm_client: openai.OpenAI = openai.OpenAI(**client_kwargs)

        return cls(
            index=index,
            chunks=chunks,
            embeddings_model=emb_model,
            llm_client=llm_client,
            llm_model=llm_model,
            top_k=top_k,
        )

    # ---- HyDE generation ----

    def generate_hypothetical_document(self, query: str) -> str:
        """Use an LLM to generate a hypothetical document for the query.

        Args:
            query: The user's natural-language question.

        Returns:
            Generated hypothetical document text.
        """
        try:
            response: openai.types.chat.ChatCompletion = (
                self.llm_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[
                        {"role": "system", "content": HYDE_SYSTEM_PROMPT},
                        {"role": "user", "content": query},
                    ],
                    temperature=0.7,
                    max_tokens=512,
                )
            )
            hypothetical: str = response.choices[0].message.content or ""
            logger.info(
                "HyDE generated hypothetical doc (%d chars) for query: %s",
                len(hypothetical),
                query[:80],
            )
            return hypothetical
        except Exception as exc:
            logger.error("HyDE generation failed: %s", exc)
            # Fallback: use the raw query
            logger.warning("Falling back to raw query embedding")
            return query

    # ---- Retrieval ----

    def query(
        self,
        user_query: str,
        top_k: int | None = None,
        use_hyde: bool = True,
    ) -> list[RetrievalResult]:
        """Retrieve the most relevant chunks for a user query.

        Args:
            user_query: The natural-language question.
            top_k: Number of results to return (overrides default).
            use_hyde: If True, apply HyDE; otherwise embed the query directly.

        Returns:
            Ordered list of ``RetrievalResult`` objects (most relevant first).
        """
        k: int = top_k or self.top_k

        # Step 1: Generate hypothetical document (or use raw query)
        if use_hyde:
            text_to_embed: str = self.generate_hypothetical_document(user_query)
        else:
            text_to_embed = user_query

        # Step 2: Embed the text
        try:
            query_embedding: list[float] = self.embeddings_model.embed_query(
                text_to_embed
            )
        except Exception as exc:
            logger.error("Query embedding failed: %s", exc)
            return []

        # Normalise for IP-based cosine similarity
        query_vec: np.ndarray = np.array([query_embedding], dtype=np.float32)
        norm: float = float(np.linalg.norm(query_vec))
        if norm > 0:
            query_vec = query_vec / norm

        # Step 3: Search FAISS
        scores: np.ndarray
        indices: np.ndarray
        scores, indices = self.index.search(query_vec, k)

        results: list[RetrievalResult] = []
        for rank, (idx, score) in enumerate(
            zip(indices[0], scores[0]), start=1
        ):
            if idx < 0:
                continue  # FAISS returns -1 when fewer than k results
            results.append(
                RetrievalResult(
                    chunk=self.chunks[int(idx)],
                    score=float(score),
                    rank=rank,
                )
            )

        logger.info(
            "Retrieved %d results for query (hyde=%s): %s",
            len(results),
            use_hyde,
            user_query[:80],
        )
        return results

    # ---- Persistence ----

    def save_index(self, filepath: str) -> None:
        """Save the FAISS index to disk.

        Args:
            filepath: Destination file path.
        """
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, filepath)
        logger.info("FAISS index saved to %s", filepath)

    def load_index(self, filepath: str) -> None:
        """Load a FAISS index from disk.

        Args:
            filepath: Path to the saved index file.

        Raises:
            FileNotFoundError: If the index file does not exist.
        """
        if not Path(filepath).exists():
            raise FileNotFoundError(f"FAISS index not found: {filepath}")
        self.index = faiss.read_index(filepath)
        logger.info(
            "FAISS index loaded from %s (%d vectors)",
            filepath,
            self.index.ntotal,
        )
