# Document Chunker Patch — Table-Aware Chunking Fix

## Background

The original SurfSense Docker `document_chunker.py` is a thin wrapper with no
chunking logic of its own — it delegates entirely to `config.chunker_instance`:

```python
def chunk_text(text: str, use_code_chunker: bool = False) -> list[str]:
    chunker = config.code_chunker_instance if use_code_chunker else config.chunker_instance
    return [c.text for c in chunker.chunk(text)]
```

`RecursiveChunker` (from **chonkie**) was added as a local improvement and wired
as `config.chunker_instance`, configured to match the embedding model's context
window:

```python
# app/config/__init__.py
_chunker_chunk_size = int(os.getenv("CHUNKER_CHUNK_SIZE",
    getattr(embedding_model_instance, "max_seq_length", 512)))
chunker_instance = RecursiveChunker(chunk_size=_chunker_chunk_size)
```

The embedding model is `all-MiniLM-L6-v2` whose `max_seq_length` is **256
tokens**, so the effective default is `chunk_size=256`.

---

## Why RecursiveChunker Breaks Tables

`RecursiveChunker` splits text hierarchically on a priority-ordered separator
list: paragraphs → sentences → words → characters. The default list includes
`|`, which is the column delimiter in Markdown pipe tables.

Docling exports every table as Markdown. Because `|` is a split point, each row
becomes its own chunk — header and data rows are separated:

```
Chunk 1:  | Revenue | Cost | Profit |      ← header only
          |---------|------|--------|
Chunk 2:  | 49,100  | 20,300 | 28,800 |   ← data, no header
Chunk 3:  | 45,100  | 19,200 | 25,900 |   ← data, no header
```

At retrieval time a query may surface Chunk 2 or 3 without Chunk 1. The LLM
receives numeric values with no column labels — it cannot determine what each
number represents, producing wrong or empty answers.

## Why 256 Tokens Is Too Small

A typical financial table row is 20–60 tokens wide. A table with 10–15 rows
easily exceeds 256 tokens total. Even if the splitter did not treat `|` as a
separator, a 256-token budget would still cut multi-row tables mid-body.

256 also creates a secondary problem: wide tables where a single row itself
approaches 256 tokens may be truncated within a row, producing malformed
Markdown that the LLM cannot parse reliably.

The 256-token limit was chosen to align with the embedding model's context
window — a reasonable default for prose — but it is the wrong unit for
structured tabular data, where the atomic unit is the entire table, not a
token count.

---

## The Fix — `document_chunker_patch.py`

`document_chunker_patch.py` introduces `chunk_text_hybrid()`, which separates
table blocks from prose before chunking:

1. Scan line-by-line and classify contiguous runs of `|`-prefixed lines as
   table blocks; everything else is prose.
2. **Table blocks** — emit the entire table as one chunk, regardless of token length.
3. **Prose blocks** — pass through the existing `chunk_text()` unchanged.

```
After chunk_text_hybrid:
  entire table → single chunk   (header + all rows together)
  prose para   → chunked normally by RecursiveChunker
```

```python
def chunk_text_hybrid(text: str, use_code_chunker: bool = False) -> list[str]:
    TABLE_LINE = re.compile(r"^\s*\|")

    blocks: list[tuple[str, str]] = []
    current_lines: list[str] = []
    in_table = False

    for line in text.splitlines(keepends=True):
        is_table_line = bool(TABLE_LINE.match(line))
        if is_table_line != in_table:
            if current_lines:
                blocks.append(("table" if in_table else "prose", "".join(current_lines)))
            current_lines = []
            in_table = is_table_line
        current_lines.append(line)

    if current_lines:
        blocks.append(("table" if in_table else "prose", "".join(current_lines)))

    chunks: list[str] = []
    for kind, block in blocks:
        if kind != "table":
            chunks.extend(chunk_text(block, use_code_chunker=use_code_chunker))
        else:
            stripped = block.strip()
            if stripped:
                chunks.append(stripped)

    return [c for c in chunks if c.strip()]
```

The patch ships as a drop-in alongside the unchanged production file — it does
not modify `document_chunker.py` or `app/config/__init__.py`.

---

## Limitations

| Limitation | Details |
|---|---|
| **Embedding truncation on large tables** | `all-MiniLM-L6-v2` truncates input at 512 tokens. For tables larger than ~512 tokens the embedding represents only the header and top rows. BM25 full-text search still covers the full stored text, so keyword-level retrieval remains accurate. |
| **Header-only vectors are usually sufficient** | Financial table headers are unique identifiers (e.g. "Consolidated Statements of Income"), so the truncated embedding is typically enough for vector similarity match. |
| **No prose overlap** | `RecursiveChunker` is configured without `chunk_overlap`. Prose sentences at chunk boundaries lose surrounding context. Pre-existing limitation, not introduced by this patch. |
| **Ingest-time only** | The fix applies only to documents indexed after the patch is deployed. Existing fragmented chunks in PostgreSQL must be replaced by re-ingesting the document. |

---

## Deployment

```bash
# Copy patch into running containers
docker cp document_chunker_patch.py surfsense-backend-1:/app/app/indexing_pipeline/document_chunker_patch.py
docker cp document_chunker_patch.py surfsense-celery_worker-1:/app/app/indexing_pipeline/document_chunker_patch.py
```

Update call sites to use `chunk_text_hybrid` instead of `chunk_text`:

```python
# Before
from app.indexing_pipeline.document_chunker import chunk_text
chunks = chunk_text(markdown_text)

# After
from app.indexing_pipeline.document_chunker_patch import chunk_text_hybrid
chunks = chunk_text_hybrid(markdown_text)
```

Re-ingest all affected documents after deploying.

---

## Files

| File | Role |
|---|---|
| `app/indexing_pipeline/document_chunker.py` | Original production entry point — unchanged |
| `document_chunker_patch.py` | Adds `chunk_text_hybrid()` |
| `app/config/__init__.py` | Configures `RecursiveChunker(chunk_size=256)` |
