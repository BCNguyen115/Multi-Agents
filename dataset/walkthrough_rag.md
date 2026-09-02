# RAG Ingestion Pipeline — Walkthrough Report

**Generated:** 2026-08-04 13:58:45 UTC
**Duration:** 74.6 seconds

---

## 1. Document Loading

- **Dataset directory:** `/app/dataset`
- **Total files processed:** 50
- **File breakdown:**
  - `corporate`: 10 files
  - `msa`: 10 files
  - `nda`: 10 files
  - `purchase`: 10 files
  - `sow`: 10 files

## 2. Section Analysis (Regex Patterns)

The loader analysed each document to detect the best section-heading pattern:

| Priority | Pattern | Description |
|----------|---------|-------------|
| 1 | `ARTICLE` | `ARTICLE I`, `ARTICLE 3` |
| 2 | `SECTION` | `Section 1.01`, `SECTION 2` |
| 3 | `NUMBERED_HEADING` | `1. Definitions`, `2. Term` |
| 4 | `DECIMAL_SUBSECTION` | `1.1 Overview`, `2.3.1` |
| 5 | `ALL_CAPS_HEADING` | `RECITALS`, `DEFINITIONS` |

**Pattern distribution:**

- `SECTION`: 15 documents
- `ALL_CAPS_HEADING`: 14 documents
- `DECIMAL_SUBSECTION`: 12 documents
- `NUMBERED_HEADING`: 7 documents
- `ARTICLE`: 2 documents

## 3. Chunking

- **Total chunks created:** 2075
- **Strategy:** Section-based chunking with merge/split
- **Chunk size range:** 600-6000 characters
- **Small sections (< 600 chars):** merged with neighbours
- **Large sections (> 6000 chars):** split with ~12% overlap
- **Contextual prefix:** `[Source: filename - Section: title]`

## 4. Embedding & Deduplication

- **Embedding model:** `text-embedding-3-small`
- **Chunks before dedup:** 2075
- **Chunks after dedup:** 1971
- **Chunks removed:** 104 (cosine similarity > 0.90)

## 5. Storage

- **Database:** PostgreSQL (pgvector)
- **Table:** `rag_chunks`
- **Chunks inserted:** 1971
- **Index:** ivfflat (vector_cosine_ops)

## 6. HyDE Configuration

The RAG Agent uses **HyDE (Hypothetical Document Embeddings)**:

1. User submits a query
2. LLM (`gpt-4o-mini`) generates a hypothetical answer passage
3. The hypothetical passage is embedded using `text-embedding-3-small`
4. pgvector searches for nearest real chunks to the hypothetical embedding
5. Top-5 chunks are returned with source metadata
