# Sandwich Chunker & Adjacent Chunk Expansion

This document explains the two retrieval quality features developed for the SurfSense
MSFT FY26Q1 10-Q benchmark, the bugs found along the way, and the fixes applied.

---

## Table of Contents

1. [Background: Why These Features Exist](#1-background)
2. [Sandwich Chunker](#2-sandwich-chunker)
   - [What it does](#21-what-it-does)
   - [Implementation](#22-implementation)
   - [Bug: Empty Block Resets `last_prose_tail`](#23-bug-empty-block-resets-last_prose_tail)
   - [Fix](#24-fix)
3. [Adjacent Chunk Expansion](#3-adjacent-chunk-expansion)
   - [What it does](#31-what-it-does)
   - [Implementation](#32-implementation)
   - [How to enable](#33-how-to-enable)
4. [`_build_document_xml` Matched-First Index Fix](#4-matched-first-index-fix)
   - [Problem](#41-problem)
   - [Fix](#42-fix)
5. [Merge Loop: Mentioned-Doc `matched_chunk_ids` Promotion Fix](#5-matched-chunk-ids-promotion-fix)
   - [Problem](#51-problem)
   - [Fix](#52-fix)
6. [RRF Ordering Fix: Implemented but Insufficient for G3-027](#6-rrf-ordering-fix--implemented-but-insufficient-for-g3-027)
7. [End-to-End Data Flow (current state)](#7-end-to-end-data-flow-current-state)
8. [Benchmark Impact](#8-benchmark-impact)
9. [How to Re-ingest After Chunker Changes](#9-how-to-re-ingest)
10. [File Locations](#10-file-locations)

---

## 1. Background

The SurfSense backend answers financial questions by:

1. Running a hybrid (vector + BM25) RRF search over the knowledge base.
2. Building a virtual XML filesystem of matching documents.
3. Giving the LLM agent `read_file` / `ls` tools to navigate that filesystem.

The core challenge for financial 10-Q documents is **tables**.  Raw Markdown tables
are large, structurally uniform, and share similar headings across sections.  Two
problems arise:

- **Retrieval**: A table chunk with no surrounding text embeds poorly — the embedding
  model (all-MiniLM-L6-v2, max 512 tokens) only sees column headers and numbers,
  not the caption that identifies what the table is about.
- **Navigation**: Even when the correct chunk is retrieved and flagged
  `matched="true"` in the XML index, if the model only reads the first 100 lines of
  the index it can miss the flag entirely.

The sandwich chunker and adjacent expansion were built to fix the retrieval problem.
The matched-first index fix addresses the navigation problem.

---

## 2. Sandwich Chunker

### 2.1 What it does

`chunk_text_hybrid()` in [`document_chunker_patch.py`](document_chunker_patch.py) is
a Markdown-aware chunker that replaces the default recursive chunker for financial
documents.

For every Markdown table it:

- **Prepends** the last non-empty line of the preceding prose block ("context bread
  top") — typically a heading or caption such as
  *"We repurchased the following shares of common stock under the share repurchase
  programs:"*.
- **Appends** the first non-empty line of the following prose block ("context bread
  bottom") — typically a footnote or unit label such as
  *"(In millions, except per share amounts)"*.

This ensures a table chunk carries enough unique textual signal for the embedding
model to locate it correctly via vector similarity, while BM25 already covers the
full table text.

Prose sections are left to fall through to the standard `RecursiveChunker`.

### 2.2 Implementation

```python
# document_chunker_patch.py — simplified pseudocode

TABLE_LINE = re.compile(r"^\s*\|")

blocks = split_document_into_alternating_table_and_prose_blocks(text)

chunks: list[str] = []
last_prose_tail: str = ""        # last non-empty line of preceding prose
last_table_chunk_idx: int = -1   # index of most recently emitted table chunk

for kind, block in blocks:
    if kind != "table":
        non_empty = [ln for ln in block.splitlines() if ln.strip()]
        # Append first non-empty prose line to preceding table chunk (bread bottom)
        if non_empty and last_table_chunk_idx >= 0:
            chunks[last_table_chunk_idx] += "\n" + non_empty[0]
        last_table_chunk_idx = -1
        if non_empty:
            last_prose_tail = non_empty[-1]   # save bread top for next table
        # Fall through to recursive prose chunker
        chunks.extend(chunk_text(block))
    else:
        stripped = block.strip()
        if not stripped:
            continue
        # Prepend bread top
        if last_prose_tail:
            stripped = last_prose_tail + "\n" + stripped
            last_prose_tail = ""          # consumed; next table resets
        chunks.append(stripped)
        last_table_chunk_idx = len(chunks) - 1
```

### 2.3 Bug: Empty Block Resets `last_prose_tail`

**Symptom**: After fixing the chunker, the MSFT 10-Q table at chunk 11530 (Share
Repurchase table, §"Table 37") still had no bread-top caption when re-ingested.

**Cause**: In the original implementation, the condition to update `last_prose_tail`
was:

```python
# BROKEN (original)
last_prose_tail = non_empty[-1]   # always executed, even for empty blocks
```

When the document is split into `(prose , blank_lines , table)`, the blank-lines
segment is parsed as a `"prose"` block whose `non_empty` list is `[]`.  The code
fell through to `last_prose_tail = non_empty[-1]` which raised `IndexError`, and also
(in an earlier variant) reset `last_prose_tail = ""` — erasing the caption set by the
real preceding prose block.

**Effect**: Table 37 was stored as:

```
| **(In millions)** | ...
| Repurchased shares | 8 | 10 |
...
```

without the identifying caption *"We repurchased the following shares of common stock
under the share repurchase programs:"*.

### 2.4 Fix

Guard the `last_prose_tail` update behind the truthiness of `non_empty`:

```python
# FIXED
if non_empty:
    last_prose_tail = non_empty[-1]
# Empty blocks (blank separators) do NOT reset last_prose_tail.
```

After re-ingesting the 10-Q document, chunk 11530 reads:

```
We repurchased the following shares of common stock under the share repurchase programs:
| **(In millions)** | Three Months Ended | ...
| Shares | 8 | 10 |
| Amount | $3,955 | $2,800 |
...
```

This caption is the unique textual signal that enables vector search to rank the
correct chunk at the top for repurchase-related queries.

---

## 3. Adjacent Chunk Expansion

### 3.1 What it does

Even with the sandwich fix, a single-chunk retrieval miss can occur when the answer
spans multiple chunks (e.g., a table header chunk + a totals-row chunk).  Adjacent
expansion retrieves the positional neighbours of every matched chunk, giving the
model full context windows around each hit.

### 3.2 Implementation

Located in
[`rag_expansion_patch/chunks_hybrid_search.py`](rag_expansion_patch/chunks_hybrid_search.py)
inside `ChucksHybridSearchRetriever.hybrid_search()`.

```python
if expand_adjacent_chunks and matched_chunk_ids and adjacent_chunks_window > 0:
    window = max(1, min(int(adjacent_chunks_window), 3))   # capped at 3

    # Compute positional row-number per chunk within each document
    positions_subq = select(
        Chunk.id.label("chunk_id"),
        Chunk.document_id,
        func.row_number().over(
            partition_by=Chunk.document_id, order_by=Chunk.id
        ).label("pos"),
    ).where(Chunk.document_id.in_(doc_ids)).subquery("positions")

    # Collect positions of all matched chunks
    matched_positions_subq = select(
        positions_subq.c.pos, positions_subq.c.document_id
    ).where(positions_subq.c.chunk_id.in_(list(matched_chunk_ids))) \
     .subquery("matched_positions")

    # Find all chunks within ±window positions of any matched chunk
    adjacent_query = select(positions_subq.c.chunk_id).join(
        matched_positions_subq,
        (positions_subq.c.document_id == matched_positions_subq.c.document_id)
        & (positions_subq.c.pos >= matched_positions_subq.c.pos - window)
        & (positions_subq.c.pos <= matched_positions_subq.c.pos + window),
    )
    adjacent_ids = {row[0] for row in (await db_session.execute(adjacent_query)).all()}
    matched_chunk_ids |= adjacent_ids   # expand in-place
```

**Key design choice**: Position is based on `ROW_NUMBER()` ordered by `Chunk.id`,
not by `Chunk.id` arithmetic.  This is robust to non-contiguous chunk IDs caused by
deletions or re-ingestion.

### 3.3 How to enable

**Backend configuration** — pass through `KnowledgeFSMiddleware`:

```python
# knowledge_search.py — KnowledgeFSMiddleware constructor
KnowledgeFSMiddleware(
    expand_adjacent_chunks=True,
    adjacent_chunks_window=1,   # ±1 neighbour → up to 2 extra chunks per hit
)
```

**Benchmark CLI**:

```bash
python3 scripts/run_surfsense_benchmark.py \
    --expand-adjacent-chunks \
    --adjacent-chunks-window 1
```

The `run_surfsense_benchmark_deepseekflash.py` wrapper propagates these flags to the
inner script automatically:

```bash
python3 scripts/run_surfsense_benchmark_deepseekflash.py \
    --max-questions 100 \
    --run-name deepseekflash_full100_adj1
```

---

## 4. Matched-First Index Fix

### 4.1 Problem

`_build_document_xml()` in
[`rag_expansion_patch/knowledge_search.py`](rag_expansion_patch/knowledge_search.py)
builds a `<chunk_index>` listing every chunk in the document with its line range and
a `matched="true"` flag for retrieved chunks.

The MSFT 10-Q document has **321 chunks**.  The index therefore has ~330 lines.  The
LLM agent calls `read_file(offset=0, limit=100)` on first access and sees only the
first 100 index entries.

Table 37 (chunk 11530) is at document position 101 (counting from 1).  Its index
entry appeared on line 108 — outside the first 100 lines the model reads.  The model
never saw `matched="true"` for chunk 11530 and instead followed the **earlier**
`matched="true"` marker for chunk 11451 (an equity statement chunk at document
position 23) — leading to the wrong answer `+$1,446 million` for the repurchase
question.

### 4.2 Fix

Emit all `matched="true"` entries **first** in the index, followed by all unmatched
entries.  The document content body still appears in document order.

```python
# knowledge_search.py — _build_document_xml()

# Pass 1: compute line numbers for all chunks in document order.
current_line = first_chunk_line
index_entries: list[tuple[int | None, str]] = []
for cid, xml_str in chunk_entries:
    num_lines = xml_str.count("\n") + 1
    end_line = current_line + num_lines - 1
    matched_attr = ' matched="true"' if cid is not None and cid in matched else ""
    if cid is not None:
        entry = f'  <entry chunk_id="{cid}" lines="{current_line}-{end_line}"{matched_attr}/>'
    else:
        entry = f'  <entry lines="{current_line}-{end_line}"{matched_attr}/>'
    index_entries.append((cid, entry))
    current_line = end_line + 1

# Pass 2: emit matched entries first so the model sees them within the first
# read_file(limit=100) call even for very long documents.
matched_entries = [e for cid, e in index_entries if cid is not None and cid in matched]
other_entries   = [e for cid, e in index_entries if cid is None or cid not in matched]
lines.append("<chunk_index>")
lines.extend(matched_entries)   # ← always visible
lines.extend(other_entries)
lines.append("</chunk_index>")
```

**Result**: The model immediately sees the highest-priority chunks at the top of the
index, regardless of their position in the document.  This fix alone raised G3-027
from wrong to correct (`+$1,155 million`) on the non-mentioned-document path.

---

## 5. Matched-Chunk-IDs Promotion Fix

### 5.1 Problem

When a document is explicitly mentioned by the user (via `--document-title-contains`
in the benchmark wrapper, which resolves to `mentioned_document_ids` in the chat
request), `fetch_mentioned_documents()` returns the document with
`matched_chunk_ids: []` — an empty list, because the fetch is not query-driven.

The merge loop in `KnowledgeFSMiddleware._execute_search()` originally used a
`seen_doc_ids: set[int]` to deduplicate:

```python
# BROKEN (original)
seen_doc_ids: set[int] = set()
for doc in mentioned_results:
    seen_doc_ids.add(doc_id)
    merged_auth.append(doc)
for doc in search_results:
    if doc_id in seen_doc_ids:
        continue    # ← search result DISCARDED; its matched_chunk_ids are lost
    merged_auth.append(doc)
```

The document entered the XML filesystem with `matched_chunk_ids = []`, so the
`<chunk_index>` had **no** `matched="true"` flags at all.  The model read the index
sequentially and followed the first chunk — which happened to be a cash-flow chunk
(11449) adjacent to the equity statement chunk (11451), giving the wrong answer
`+$1,543 million`.

### 5.2 Fix

Promote the search result's `matched_chunk_ids` into the mentioned entry, preserving
RRF rank order (best match first), instead of discarding the search result entirely:

```python
# FIXED
seen_doc_ids: dict[int, dict[str, Any]] = {}   # was: set[int]
for doc in mentioned_results:
    doc_id = (doc.get("document") or {}).get("id")
    if doc_id is not None:
        seen_doc_ids[doc_id] = doc
    merged_auth.append(doc)
for doc in search_results:
    doc_id = (doc.get("document") or {}).get("id")
    if doc_id is not None and doc_id in seen_doc_ids:
        # Preserve RRF rank order: use the search list as the ordered base
        mentioned_entry = seen_doc_ids[doc_id]
        incoming_ordered = doc.get("matched_chunk_ids") or []
        existing_set = set(mentioned_entry.get("matched_chunk_ids") or [])
        incoming_set = set(incoming_ordered)
        mentioned_entry["matched_chunk_ids"] = incoming_ordered + [
            cid for cid in existing_set if cid not in incoming_set
        ]
        continue
    merged_auth.append(doc)
```

---

## 6. RRF Ordering Fix — Implemented but Insufficient for G3-027

### What was implemented

Three additional changes were made to propagate RRF rank order all the way to the
XML the model reads:

**`chunks_hybrid_search.py`** — after assembling `matched_chunk_ids` in
`Chunk.id` ascending order (SQL default), re-sort by RRF rank:

```python
rrf_rank: dict[int, int] = {
    item["chunk_id"]: i for i, item in enumerate(serialized_chunk_results)
}
for doc_id in doc_ids:
    doc_map[doc_id]["matched_chunk_ids"].sort(
        key=lambda cid: rrf_rank.get(cid, 999_999)
    )
```

**`knowledge_search.py` — `_build_document_xml`** — when `matched_chunk_ids` is an
ordered list, emit matched chunks first in **both** the `<chunk_index>` and the
`<document_content>` body in that order, so sequential reads also hit the best
match first.

**`knowledge_search.py` — merge loop** — preserve the incoming RRF-ordered list
(see Fix 5 above) rather than converting to a set.

### Why G3-027 still fails on the mentioned-doc path

All three fixes are deployed and the RRF ordering is confirmed correct in retrieval
debugging:

```
matched_chunk_ids = [11726, 11530, 11531, 11529, ...]  # RRF order ✅
document_content: chunk 11726 first, chunk 11530 second ✅
```

Despite this, DeepSeek-v4-flash consistently reads `grep` results or jumps to the
cash-flow statement (chunk ~11450 range) and derives `+$1,543 million` from there.
The model ignores the carefully ordered document content and finds its own path to a
plausible-sounding but wrong answer.

### Conclusion

This is a **model behaviour problem**, not a retrieval problem.  The retrieval
pipeline is delivering the correct chunk (11530, Table 37, containing `$3,955` and
`$2,800`) as the first matched result.  DeepSeek-v4-flash does not reliably respect
the document structure and prefers the cash flow statement when multiple numeric
answers are present.

**G3-027 on the mentioned-doc path cannot be solved through further retrieval
engineering with this model.  A stronger or differently-prompted model is required.**

---

## 7. End-to-End Data Flow (current state)

```
User question
     │
     ▼
KnowledgeFSMiddleware._execute_search()
     │
     ├─ fetch_mentioned_documents()       → mentioned_results  (matched_chunk_ids=[])
     │
     ├─ search_knowledge_base()
     │      └─ ChucksHybridSearchRetriever.hybrid_search()
     │              ├─ RRF: semantic CTE + keyword CTE → serialized_chunk_results (RRF order)
     │              ├─ [optional] adjacent expansion: ±window positional neighbours
     │              ├─ doc_map assembled in Chunk.id order
     │              └─ matched_chunk_ids re-sorted by RRF rank  ✅ (Fix 6)
     │           → search_results  (matched_chunk_ids=[11726, 11530, ...] RRF order)
     │
     ├─ Merge loop (Fix 5): promote RRF-ordered matched_chunk_ids into mentioned entry  ✅
     │        mentioned_results[doc=10].matched_chunk_ids = [11726, 11530, 11531, ...]
     │
     └─ build_scoped_filesystem()
            └─ _build_document_xml(document, matched_chunk_ids=[11726, 11530, ...])
                    ├─ Compute line ranges based on RRF-ordered content emission
                    ├─ <chunk_index>: matched entries first, in RRF rank order  ✅ (Fix 4+6)
                    │       <entry chunk_id="11726" matched="true"/>   ← RRF rank 1
                    │       <entry chunk_id="11530" matched="true"/>   ← RRF rank 2
                    │       ...
                    └─ <document_content>: matched chunks first, in RRF rank order  ✅ (Fix 6)
                            chunk 11726 content first
                            chunk 11530 content second  (Table 37 with $3,955/$2,800)
                            ...

LLM reads read_file(offset=0, limit=50)
     → sees chunk 11726 (monthly repurchase table) immediately
     → reads chunk 11530 (total repurchase table) next
     → STILL derives +$1,543 from cash flow statement  ← model behaviour, not retrieval
```

The retrieval pipeline is correct end-to-end.  The model finds its own path to the
cash flow numbers regardless of document structure.

---

## 8. Benchmark Impact

| Condition | Score |
|-----------|-------|
| Baseline (before sandwich fix) | ~90% (G3-027 wrong: `+$1,543`) |
| After sandwich chunker + empty-block fix (re-ingested) | ~93–94% (G3-027 still wrong via equity stmt: `+$1,446`) |
| + `_build_document_xml` matched-first fix (Fix 4) | G3-027 correct on **non-mentioned-doc path**: `+$1,155` ✅ |
| + Merge loop matched_chunk_ids promotion (Fix 5) | G3-027 still wrong on **mentioned-doc path**: `+$1,543` ❌ |
| + RRF ordering in `chunks_hybrid_search.py` + content reorder in `_build_document_xml` (Fix 6) | G3-027 still wrong: `+$1,543` ❌ — model ignores document order |

**Final state**: All retrieval engineering exhausted.  G3-027 requires a model that
can be directed to a specific table rather than free-reading the full document.

---

## 9. How to Re-ingest After Chunker Changes

After any change to `document_chunker_patch.py`, the target document **must** be
re-ingested so the database stores chunks with the new text.  The chunk IDs will
change on re-ingestion.

```bash
# 1. Confirm the backend is running
docker compose ps

# 2. Delete the old document via the SurfSense UI or API (document_id=10 for MSFT 10-Q)
# 3. Re-upload MSFT_FY26Q1_10Q.docx and wait for processing to complete

# 4. Verify the sandwich prefix is present on the repurchase table chunk:
conda run -n ai python3 - <<'EOF'
import asyncio, sys
sys.path.insert(0, "surfsense_backend")
from app.db import async_session_maker, Chunk
from sqlalchemy import select

async def main():
    async with async_session_maker() as s:
        q = select(Chunk).where(Chunk.content.contains("We repurchased the following shares"))
        rows = (await s.execute(q)).scalars().all()
        for r in rows:
            print(f"chunk_id={r.id}: {r.content[:200]}")

asyncio.run(main())
EOF
```

---

## 10. File Locations

| File | Purpose |
|------|---------|
| [`document_chunker_patch.py`](document_chunker_patch.py) | `chunk_text_hybrid()` — sandwich chunker implementation |
| [`rag_expansion_patch/chunks_hybrid_search.py`](rag_expansion_patch/chunks_hybrid_search.py) | `hybrid_search()` — RRF search + adjacent expansion + `matched_chunk_ids` assembly |
| [`rag_expansion_patch/knowledge_search.py`](rag_expansion_patch/knowledge_search.py) | `_build_document_xml()` (matched-first index) · `KnowledgeFSMiddleware._execute_search()` (merge loop) |
| [`scripts/run_surfsense_benchmark.py`](scripts/run_surfsense_benchmark.py) | Core benchmark runner; `--expand-adjacent-chunks` / `--adjacent-chunks-window` CLI flags |
| [`scripts/run_surfsense_benchmark_deepseekflash.py`](scripts/run_surfsense_benchmark_deepseekflash.py) | DeepSeek wrapper; passes `--document-title-contains MSFT_FY26Q1_10Q` (mentioned-doc path) |
