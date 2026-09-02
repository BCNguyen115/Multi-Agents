"""Ingestion package — document processing pipeline for RAG.

Modules:
    document_loader: PDF/DOCX loading with section structure analysis.
    chunker: Section-based chunking with merge/split logic.
    embedder: Embedding, deduplication, and pgvector storage.
"""
