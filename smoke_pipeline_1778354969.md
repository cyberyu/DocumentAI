# SurfSense Document Processing: Chunking Strategy

This note covers the ETL + chunking layer of SurfSense and documents the problem with the default approach for financial documents, and the table-preserving fix applied locally.

---

## ETL (unchanged)

All uploaded `.docx` and `.pdf` files go through [Docling](https://github.com/docling-project/docling):

```
File (DOCX / PDF)
    │
    ▼  converter.convert(file_path)
[Docling — PyPdfiumDocumentBackend, CPU, do_ocr=False, do_table_structure=True]
    │
    ▼  result.document.export_to_markdown()
Markdown string (headings + prose + pipe-delimited tables)
```

Docling detects table boundaries and renders each table as a standard Markdown pipe table:

```
| Item | Q1 FY26 | Q2 FY26 |
|---|---|---|
| Revenue | 69,632 | 72,431 |
| Operating income | 31,658 | 33,671 |
```

The Markdown is stored in `documents.source_markdown` and forwarded to the chunker.

---

## Previous approach: `RecursiveChunker` (default)

**Code**: `app/indexing_pipeline/document_chunker.py` → `chunk_text()`  
**Library**: `chonkie.RecursiveChunker`

```python
from chonkie import RecursiveChunker

chunker = RecursiveChunker(
    chunk_size=512  # = embedding model max_seq_length
)

chunks = [c.text for c in chunker.chunk(markdown_text)]
```

`RecursiveChunker` has no concept of Markdown structure. It splits on paragraph → sentence → token boundaries to stay within `chunk_size=512`. A financial table with 40 rows and narrow columns is roughly 40 × 60 chars = 2,400 chars ≈ 600 tokens, which exceeds 512 — so the table gets cut mid-body.

### What this produces for a financial table

| Chunk | Content |
|---|---|
| 0 | `\| Item \| Q1 FY26 \| Q2 FY26 \|` (header row only, orphaned) |
| 1 | `\| Revenue \| 69,632 \| 72,431 \|` |
| 2 | `\| Operating income \| 31,658 \| 33,671 \|` |
| … | one row per chunk, header not repeated |

The MSFT 10-Q documents produced **70+ single-row chunks** per table. When the LLM receives the top-20 retrieved chunks, it sees disconnected rows with no column context, making table reconstruction impossible.

### Observed symptom

Backend logs showed:
- LLM call 1: 478 prompt tokens → 44 completion tokens (planning / tool call)
- LLM call 2: **18,214 prompt tokens → 31 completion tokens** (model gives up)

18K tokens of pipe-delimited fragment rows filled the context; the model produced a near-empty answer.

---

## New approach: `chunk_text_hybrid()` (applied fix)

**Code**: `app/indexing_pipeline/document_chunker.py` → `chunk_text_hybrid()`  
The original `chunk_text()` function is **preserved untouched**.

### Strategy

1. Parse the Markdown line-by-line into alternating **prose** and **table** blocks (a table block = contiguous lines starting with `|`).
2. **Prose blocks** → delegated to the original `chunk_text()` / `RecursiveChunker` (unchanged behaviour).
3. **Table blocks**:
   - If the whole table fits within `max_seq_length` (512 tokens) → emit as a **single chunk**.
   - If the table is larger → split at row boundaries, **repeating the header row** at the start of every sub-chunk, so column context is never lost.

```python
def chunk_text_hybrid(text: str, use_code_chunker: bool = False) -> list[str]:
    max_tokens = getattr(config.embedding_model_instance, "max_seq_length", 512)
    tokenizer  = getattr(config.embedding_model_instance, "tokenizer", None)

    # 1. Split into prose / table blocks
    # 2. Prose  → chunk_text()  (RecursiveChunker, unchanged)
    # 3. Table  → whole chunk if fits; else row-bin with header repeated
```

### What this produces for the same financial table

| Chunk | Content |
|---|---|
| 0 | Full table (header + all rows), single chunk ≤ 512 tokens |

For a very large table (> 512 tokens):

| Chunk | Content |
|---|---|
| 0 | Header + rows 1–N (fits in 512 tokens) |
| 1 | **Header repeated** + rows N+1–M |
| 2 | **Header repeated** + rows M+1–end |

The LLM always receives complete rows with their column headers.

---

## Wiring change

Only two lines in `app/indexing_pipeline/indexing_pipeline_service.py` were modified:

```python
# Before
from app.indexing_pipeline.document_chunker import chunk_text
...
chunk_texts = await asyncio.to_thread(
    chunk_text,
    connector_doc.source_markdown,
    use_code_chunker=connector_doc.should_use_code_chunker,
)

# After
from app.indexing_pipeline.document_chunker import chunk_text, chunk_text_hybrid
...
chunk_texts = await asyncio.to_thread(
    chunk_text_hybrid,
    connector_doc.source_markdown,
    use_code_chunker=connector_doc.should_use_code_chunker,
)
```

Code files (`should_use_code_chunker=True`) still use `CodeChunker` via the `use_code_chunker` path inside `chunk_text_hybrid → chunk_text`.

---

## Re-indexing required

The fix applies to **new** indexing runs only. Documents already in the database were chunked with the old strategy. To apply the fix to existing documents:

1. Delete the documents from the SurfSense UI (or directly: `DELETE FROM documents WHERE id IN (1, 2);`)
2. Re-upload the same DOCX files — the worker will re-run ETL + chunking automatically.

---

## Token usage comparison (MSFT FY26Q1 10-Q, cash flow query)

### Old approach — `RecursiveChunker`

| LLM call | Role | Prompt tokens | Completion tokens |
|---|---|---|---|
| 1 | Planning / tool selection | 478 | 44 |
| 2 | Answer generation (chunk context injected) | 18,214 | **31** |
| **Total** | | **18,692** | **75** |

- The 18,214-token prompt was almost entirely fragmented single-row table chunks.
- The model produced only 31 completion tokens — effectively giving up mid-answer.
- The 20-chunk retrieval cap returned 20 disconnected rows, none with column headers.

### New approach — `chunk_text_hybrid`

| LLM call | Role | Prompt tokens | Completion tokens |
|---|---|---|---|
| 1 | Planning / tool selection | 408 | 51 |
| 2 | First tool call + chunk context | 20,530 | 42 |
| 3 | Answer generation (full table context) | 27,875 | **190** |
| **Total** | | **48,813** | **283** |

- The model made **3 calls** instead of 2 — it had enough coherent context to issue a follow-up retrieval before writing the answer.
- Completion tokens grew from 31 → **190** on the answer call (+513%).
- Total completion tokens: 75 → **283** (+277%).
- Larger prompt (48K vs 18K) is expected: complete table chunks are semantically denser per token, and the model chose to read more of them before answering.

### How chunk tokens translate to context

| Metric | Old | New |
|---|---|---|
| Chunk tokens in peak call | 18,214 (all fragments) | 27,875 (complete tables) |
| Tokens per chunk (avg, retrieval cap = 20) | ~910 — but mostly whitespace/pipes | ~1,390 — full rows + headers |
| Completion tokens (answer call) | 31 | 190 |
| Model could reconstruct a table? | No | Yes |

---

## Summary

| | Previous (`RecursiveChunker`) | New (`chunk_text_hybrid`) |
|---|---|---|
| Prose | Split at para/sentence/token boundary | Unchanged (same `RecursiveChunker`) |
| Tables | Split mid-row, no header repeat | Whole table per chunk; header repeated when split |
| Chunk count (MSFT 10-Q, per table) | ~40–70 single-row chunks | 1 chunk per table (or a few with header) |
| LLM calls per query | 2 | 3 (model reads more before answering) |
| Peak prompt tokens | 18,214 | 27,875 |
| Answer completion tokens | 31 (near-empty) | 190 (full answer) |
| Total completion tokens | 75 | 283 (+277%) |
| Code changed | — | `document_chunker.py` (new function added) · 2 lines in `indexing_pipeline_service.py` |

---

## Future optimization: embedding model upgrade

> **TODO** — revisit when re-indexing is acceptable.

The current embedding model (`all-MiniLM-L6-v2`) truncates input at **512 tokens** when computing vectors. For large financial tables stored as single chunks, only the header + top rows are captured in the embedding; the rest of the table is invisible to vector search (though still searchable via BM25).

Swapping to a long-context embedding model would make whole-table embeddings accurate.

| Model | Dims | Max tokens | Notes |
|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | 512 | **Current default** — truncates large tables |
| `BAAI/bge-base-en-v1.5` | 768 | 512 | Better quality, same token limit |
| `BAAI/bge-large-en-v1.5` | 1024 | 512 | Still 512 |
| `nomic-ai/nomic-embed-text-v1.5` | 768 | **8192** | **Recommended upgrade** — full table fits in embedding |
| `jinaai/jina-embeddings-v2-base-en` | 768 | **8192** | Long context alternative |
| `thenlper/gte-large` | 1024 | 512 | Marginal improvement |

**Recommended**: `nomic-ai/nomic-embed-text-v1.5` (~550 MB, 8K context, 768-dim).

### Steps to upgrade

1. Set `EMBEDDING_MODEL` in `docker-compose.yml` for `backend`, `celery_worker`, `celery_beat`:
   ```yaml
   environment:
     EMBEDDING_MODEL: "nomic-ai/nomic-embed-text-v1.5"
   ```
2. Update the PostgreSQL vector column dimensions (384 → 768) — requires a DB migration:
   ```sql
   ALTER TABLE chunks    ALTER COLUMN embedding TYPE vector(768);
   ALTER TABLE documents ALTER COLUMN embedding TYPE vector(768);
   DROP INDEX chucks_vector_index;
   DROP INDEX document_vector_index;
   CREATE INDEX chucks_vector_index   ON chunks    USING hnsw (embedding vector_cosine_ops);
   CREATE INDEX document_vector_index ON documents USING hnsw (embedding vector_cosine_ops);
   ```
3. Delete all existing documents and re-upload — existing 384-dim vectors are incompatible.
4. Restart all services; the model downloads automatically on first use.


Smoke run 1778354969
