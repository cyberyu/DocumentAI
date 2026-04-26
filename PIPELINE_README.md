# SurfSense Document Processing Pipeline

Technical documentation of the full RAG pipeline used by SurfSense — from file upload to retrieval — intended for replication in another application.

---

## Overview

```
DOCX/PDF/etc.
    │
    ▼
[ETL: Docling]                              converts to Markdown
    │                                         current: docling (Python pkg, CPU, no OCR, table-structure enabled)
    ▼
[Chunker: RecursiveChunker]                 splits Markdown into token-bounded text chunks
    │                                         current: chonkie RecursiveChunker, chunk_size=512, no overlap
    ▼
[Embedder: all-MiniLM-L6-v2]               produces 384-dim vectors
    │                                         current: fastembed, local model, 512 token max
    ▼
[PostgreSQL 17 + pgvector]                  stores text + embedding + GIN full-text index
    │                                         current: pgvector/pgvector:pg17, HNSW cosine index, asyncpg driver
    ▼
[Hybrid Search: RRF(vector <=> + BM25)]     retrieves top-K chunks at query time
    │                                         current: SQLAlchemy async CTEs, k=60, 20 chunks/doc cap
    ▼
[LLM: vLLM / OpenAI-compatible]             generates answer with cited chunks as context
                                             current: vLLM serving Qwen/Qwen2.5-7B-Instruct at http://172.19.0.1:8001/v1
```

---

## Sections at a glance

| § | Content | Software stack |
|---|---|---|
| **1. ETL** | Docling setup — `do_table_structure=True`, `do_ocr=False`, `export_to_markdown()` | `docling` Python pkg · `PyPdfiumDocumentBackend` · CPU · no OCR |
| **2. Chunking** | `RecursiveChunker(chunk_size=512)` from chonkie, no overlap | `chonkie` · `RecursiveChunker` · chunk_size = embedding model `max_seq_length` (512) |
| **3. Embedding** | `sentence-transformers/all-MiniLM-L6-v2` via fastembed, 384-dim, batch API | `fastembed` · `sentence-transformers/all-MiniLM-L6-v2` · local inference · 384-dim · 512 token max |
| **4. Storage** | Full PostgreSQL schema (`chunks` + `documents`), HNSW index for vectors, GIN index for BM25 | `PostgreSQL 17` · `pgvector` extension · HNSW cosine ops · GIN `tsvector` · `asyncpg` · `SQLAlchemy` async |
| **5. Retrieval** | Full RRF SQL query, `k=60`, per-doc 20-chunk cap, optional reranker | `pgvector` `<=>` operator · `plainto_tsquery` · RRF `k=60` · optional `flashrank` reranker |
| **6. LLM** | OpenAI-compatible endpoint, required vLLM flags | `vLLM` · `Qwen/Qwen2.5-7B-Instruct` · `litellm` · `langchain-litellm` · flags: `--enable-auto-tool-choice --tool-call-parser hermes` |
| **7. Minimal example** | End-to-end Python code to ingest a DOCX and run a search query | `docling` · `chonkie` · `fastembed` · `SQLAlchemy` async · `asyncpg` |
| **8. Known limitations** | Table chunking problem + fix options, embedding model recommendations, missing overlap | Fix: swap to `docling` `HybridChunker`, or set `ETL_SERVICE=UNSTRUCTURED` in `.env` |

---

## 1. ETL: File → Markdown

**Code**: `app/etl_pipeline/etl_pipeline_service.py`, `app/services/docling_service.py`

**Library**: [Docling](https://github.com/docling-project/docling)

The entry point is `EtlPipelineService.extract(EtlRequest)`. It classifies the file by extension then routes to the appropriate parser:

| Category | Extensions | Parser | Current stack |
|---|---|---|---|
| `PLAINTEXT` | `.txt`, `.md`, `.csv` | read directly | built-in Python `open()` |
| `DIRECT_CONVERT` | `.html`, `.xml` | simple conversion | built-in |
| `AUDIO` | `.mp3`, `.wav`, `.m4a` | Whisper transcription | `openai-whisper` |
| `IMAGE` | `.png`, `.jpg` | vision LLM or Docling | no vision LLM configured; falls back to Docling |
| `DOCUMENT` | `.docx`, `.pdf`, `.xlsx` | Docling | `docling` Python pkg, `PyPdfiumDocumentBackend`, CPU |

For `.docx` and `.pdf` files, Docling is used:

```python
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = False          # OCR disabled
pipeline_options.do_table_structure = True  # table detection enabled

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=pipeline_options,
            backend=PyPdfiumDocumentBackend,
        )
    }
)

result = converter.convert(file_path)
markdown = result.document.export_to_markdown()
```

**Output**: a single Markdown string containing headings, paragraphs, and tables rendered as pipe-delimited Markdown tables.

**Key limitation**: Each row of a financial table becomes a separate chunk in the next step. Column headers and data rows are split apart, which impairs RAG accuracy for tables. See §5 Known Limitations.

---

## 2. Chunking: Markdown → Chunks

**Code**: `app/indexing_pipeline/document_chunker.py`, `app/config/__init__.py`

**Library**: [chonkie](https://github.com/chonkie-ai/chonkie) — `RecursiveChunker`

```python
from chonkie import RecursiveChunker

chunker = RecursiveChunker(
    chunk_size=512   # tokens; derived from embedding model's max_seq_length
)

chunks: list[str] = [c.text for c in chunker.chunk(markdown_text)]
```

- `chunk_size` is set to `embedding_model.max_seq_length` (default 512 for `all-MiniLM-L6-v2`).
- `RecursiveChunker` splits on paragraph boundaries first, then sentences, then tokens — no fixed overlap.
- Code files use `CodeChunker` instead (same `chunk_size`).
- There is **no chunk overlap** configured; adjacent semantic context is not preserved across chunk boundaries.

---

## 3. Embedding: Chunks → Vectors

**Code**: `app/utils/document_converters.py`

**Model**: `sentence-transformers/all-MiniLM-L6-v2` (local, 384 dimensions)

**Library**: [fastembed](https://github.com/qdrant/fastembed) via `AutoEmbeddings`

```python
from fastembed import AutoEmbeddings

embedding_model = AutoEmbeddings.get_embeddings("sentence-transformers/all-MiniLM-L6-v2")

# Per-chunk embedding
vector: np.ndarray = embedding_model.embed(chunk_text)   # shape: (384,)

# Batch embedding (preferred for indexing)
vectors: list[np.ndarray] = embedding_model.embed_batch(chunk_texts)
```

Texts longer than the model's context window (512 tokens) are truncated before embedding using the model's own tokenizer.

The **document** itself also gets a single embedding (of its full content or a truncated version) stored in `documents.embedding`.

---

## 4. Storage: PostgreSQL + pgvector

### Schema

```sql
-- One row per source document
CREATE TABLE documents (
    id                      SERIAL PRIMARY KEY,
    title                   VARCHAR NOT NULL,
    document_type           documenttype NOT NULL,  -- 'FILE', 'CRAWLED_URL', etc.
    content                 TEXT NOT NULL,           -- full Markdown from ETL
    source_markdown         TEXT,                    -- original Markdown before processing
    content_hash            VARCHAR UNIQUE NOT NULL,
    embedding               vector(384),             -- whole-document embedding
    document_metadata       JSON,
    status                  JSONB NOT NULL DEFAULT '{"state": "ready"}',
    search_space_id         INTEGER NOT NULL REFERENCES searchspaces(id) ON DELETE CASCADE,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ
);

-- One row per chunk
CREATE TABLE chunks (
    id          SERIAL PRIMARY KEY,
    content     TEXT NOT NULL,       -- raw chunk text (Markdown)
    embedding   vector(384),         -- chunk embedding
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL
);
```

### Indexes

```sql
-- Chunks: cosine similarity ANN (HNSW)
CREATE INDEX chucks_vector_index ON chunks USING hnsw (embedding vector_cosine_ops);

-- Chunks: BM25 full-text search
CREATE INDEX chucks_search_index ON chunks USING gin (to_tsvector('english', content));

-- Documents: same pattern
CREATE INDEX document_vector_index ON documents USING hnsw (embedding vector_cosine_ops);
CREATE INDEX document_search_index ON documents USING gin (to_tsvector('english', content));
```

### Inserting a document + chunks

```python
from sqlalchemy.ext.asyncio import AsyncSession

async def store_document_and_chunks(
    session: AsyncSession,
    title: str,
    markdown: str,
    chunks: list[str],
    chunk_vectors: list[np.ndarray],
    doc_vector: np.ndarray,
    search_space_id: int,
):
    doc = Document(
        title=title,
        content=markdown,
        embedding=doc_vector.tolist(),
        search_space_id=search_space_id,
        content_hash=hashlib.sha256(markdown.encode()).hexdigest(),
        document_type=DocumentType.FILE,
        status={"state": "ready"},
        created_at=datetime.utcnow(),
    )
    session.add(doc)
    await session.flush()  # get doc.id

    for text, vec in zip(chunks, chunk_vectors):
        session.add(Chunk(
            content=text,
            embedding=vec.tolist(),
            document_id=doc.id,
            created_at=datetime.utcnow(),
        ))

    await session.commit()
```

---

## 5. Retrieval: Hybrid Search (RRF)

**Code**: `app/retriever/chunks_hybrid_search.py`

SurfSense uses **Reciprocal Rank Fusion (RRF)** to merge results from two independent searches:

1. **Vector search** — cosine similarity via pgvector HNSW index (`embedding <=> query_embedding`)
2. **Keyword search** — PostgreSQL `plainto_tsquery` BM25 full-text ranking

```sql
-- Simplified RRF query (actual query uses CTEs)
WITH semantic AS (
    SELECT id, rank() OVER (ORDER BY embedding <=> :query_vec) AS rank
    FROM chunks
    JOIN documents ON chunks.document_id = documents.id
    WHERE documents.search_space_id = :space_id
    ORDER BY embedding <=> :query_vec
    LIMIT :n
),
keyword AS (
    SELECT id, rank() OVER (ORDER BY ts_rank_cd(to_tsvector('english', content), plainto_tsquery('english', :query)) DESC) AS rank
    FROM chunks
    JOIN documents ON chunks.document_id = documents.id
    WHERE documents.search_space_id = :space_id
      AND to_tsvector('english', content) @@ plainto_tsquery('english', :query)
    ORDER BY ts_rank_cd(to_tsvector('english', content), plainto_tsquery('english', :query)) DESC
    LIMIT :n
)
SELECT
    chunks.*,
    COALESCE(1.0 / (60 + semantic.rank), 0) + COALESCE(1.0 / (60 + keyword.rank), 0) AS score
FROM semantic
FULL OUTER JOIN keyword ON semantic.id = keyword.id
JOIN chunks ON chunks.id = COALESCE(semantic.id, keyword.id)
ORDER BY score DESC
LIMIT :top_k;
```

**RRF constant**: `k = 60` (standard value)

**Post-retrieval grouping**: results are grouped by document. Per document, at most `_MAX_FETCH_CHUNKS_PER_DOC = 20` chunks are sent to the LLM. This improves coherence for large documents but means the first 20 chunks by `id` (insertion order) are always included alongside the matched chunks.

### Optional reranking

If `RERANKERS_ENABLED=TRUE`, a cross-encoder reranker (e.g. `ms-marco-MiniLM-L-12-v2` via flashrank) re-scores the hybrid results before sending to the LLM.

---

## 6. LLM Generation

The retrieved chunks are formatted into a prompt as a numbered list with citation markers `[citation:<chunk_id>]`. The LLM (any OpenAI-compatible endpoint) is called with tool-calling enabled to allow structured retrieval steps.

**Required vLLM flags** for Qwen2.5 models:
```
--enable-auto-tool-choice --tool-call-parser hermes
```

---

## 7. Replicating the Pipeline

### Dependencies

```
# requirements.txt
docling                  # ETL: DOCX/PDF → Markdown  (current: CPU, table-structure enabled)
chonkie                  # chunking: RecursiveChunker
fastembed                # embeddings: local SentenceTransformer models
sentence-transformers    # embedding model weights
sqlalchemy[asyncio]      # ORM + async queries
asyncpg                  # PostgreSQL async driver
pgvector                 # pgvector SQLAlchemy type
litellm                  # LLM abstraction layer
langchain-litellm        # LangChain adapter for litellm
```

### Current Docker service versions

| Service | Image | Version | Role |
|---|---|---|---|
| **db** | `pgvector/pgvector` | `pg17` | PostgreSQL 17 + pgvector extension |
| **redis** | `redis` | `8-alpine` | Celery broker & result backend |
| **searxng** | `searxng/searxng` | `2026.3.13-3c1f68c59` | Self-hosted web search (used by agent) |
| **backend** | `ghcr.io/modsetter/surfsense-backend` | `latest` (v0.0.19) | FastAPI + Uvicorn, Python 3.12 |
| **celery_worker** | same as backend | `latest` | Celery worker — runs ETL + indexing tasks |
| **celery_beat** | same as backend | `latest` | Celery beat — scheduled periodic tasks |
| **zero-cache** | `rocicorp/zero` | `0.26.2` | Real-time data sync (Rocicorp Zero) |
| **frontend** | `ghcr.io/modsetter/surfsense-web` | `latest` (v0.0.19) | Next.js 15, Node.js, custom entrypoint patch |
| **vLLM** | host process | — | OpenAI-compatible LLM server, port 8001 |

### PostgreSQL setup

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for title trigram index
```

### Minimal end-to-end example

```python
import asyncio
import hashlib
from datetime import datetime

import numpy as np
from chonkie import RecursiveChunker
from docling.document_converter import DocumentConverter
from fastembed import AutoEmbeddings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# --- 1. Convert DOCX to Markdown ---
converter = DocumentConverter()
result = converter.convert("my_document.docx")
markdown = result.document.export_to_markdown()

# --- 2. Chunk ---
embedding_model = AutoEmbeddings.get_embeddings("sentence-transformers/all-MiniLM-L6-v2")
chunker = RecursiveChunker(chunk_size=512)
chunks = [c.text for c in chunker.chunk(markdown)]

# --- 3. Embed ---
doc_vector = np.array(list(embedding_model.embed([markdown]))[0])
chunk_vectors = list(embedding_model.embed_batch(chunks))

# --- 4. Store ---
engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/mydb")
async_session = sessionmaker(engine, class_=AsyncSession)

async def ingest():
    async with async_session() as session:
        await store_document_and_chunks(
            session,
            title="my_document.docx",
            markdown=markdown,
            chunks=chunks,
            chunk_vectors=chunk_vectors,
            doc_vector=doc_vector,
            search_space_id=1,
        )

asyncio.run(ingest())

# --- 5. Query ---
async def search(query: str, top_k: int = 5):
    async with async_session() as session:
        retriever = ChucksHybridSearchRetriever(session)
        return await retriever.hybrid_search(
            query_text=query,
            top_k=top_k,
            search_space_id=1,
        )

results = asyncio.run(search("cash flow from operations September 2025"))
for r in results:
    print(r["document"]["title"])
    for chunk in r["chunks"]:
        print("  ", chunk["content"][:200])
```

---

## 8. Known Limitations and Improvements

### Table chunking (current behaviour)
Docling converts tables to pipe-delimited Markdown. `RecursiveChunker` splits on paragraph/sentence boundaries, so a table's **header row** and **data rows** end up in different chunks. During retrieval, a data row may be returned without its header, making column attribution impossible for the LLM.

**Fix options**:

| Option | Effort | Current stack impact |
|---|---|---|
| Use `docling`'s `HybridChunker` instead of `RecursiveChunker` — it is table-aware and keeps table rows with their headers | Low | Drop-in replacement; change one line in `app/config/__init__.py` |
| Post-process the Markdown: detect Markdown table blocks (`\|...\|`) and emit each full table as a single chunk | Medium | Add a pre-chunking step before `RecursiveChunker` |
| Use `LLAMACLOUD` or `UNSTRUCTURED` ETL service — both offer table-aware JSON export | Medium | Set `ETL_SERVICE=UNSTRUCTURED` or `ETL_SERVICE=LLAMACLOUD` in `.env`; requires API keys |
| Re-index with chunk overlap (`chunk_overlap=128`) so adjacent rows share context | Low | `RecursiveChunker` supports `chunk_overlap`; partial improvement only |

### Embedding model
`all-MiniLM-L6-v2` (384-dim, 512 token max) is fast but not optimised for long financial text. For better recall on 10-Q/10-K style documents, consider:
- `BAAI/bge-base-en-v1.5` (768-dim, 512 tokens)
- `nomic-ai/nomic-embed-text-v1.5` (768-dim, 8192 tokens — handles full tables)

### No chunk overlap
`RecursiveChunker` with no overlap means sentences at chunk boundaries lose surrounding context. Add `chunk_overlap=64` (roughly a sentence) to improve cross-boundary queries.
