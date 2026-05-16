# Number Table Verbatim Match & Highlighting

**Version:** 1.0  
**Date:** 2026-05-15  
**Scope:** End-to-end pipeline from LLM number extraction → coerced verbatim match → OpenSearch evidence enrichment → DOM table highlighting in a framed HTML viewer

---

## 1. The `.80` Normalization Problem

### The Issue

LLMs tend to normalize `.80` to `0.80` or `80` in their response. The benchmark question suffix instructs:

```
Return the value exactly as it appears in the source. Do not normalize, convert, or reformat.
```

Despite this instruction, models often strip the leading dot because `.80` is a non-standard numeric representation.

### How the Benchmark Runner Handles It

The runner in `scripts/run_surfsense_benchmark.py` uses two layers:

**Layer A — `_clean_predicted_answer()`** (line ~120)
Strips trailing concatenation artifacts first, then uses `_extract_final_value_candidate()` to pull the last numeric-looking token:

```python
# Handle trailing "..80" or ".80.80" artifacts
cleaned = re.sub(r'\.\.\d+(?:\.\d+)*$', '', cleaned).strip()
cleaned = re.sub(r'\.\d+\.\d+$', '', cleaned).strip()
```

The regex `r"\.\d+"` is critical — it matches `.80`, `.70`, etc. as valid numbers. Without this leading-dot pattern the regex would skip `.80` entirely and return an empty candidate.

**Layer B — `_prepare_prediction_for_scoring()`** (line ~450)
For `amount`, `rate`, `ratio`, `delta` types, it re-extracts via `_extract_final_numeric_candidate()` which uses:

```python
re.finditer(r"\.\d+"  # <-- matches ".80", ".70"
    r"|[$\u20ac...]?[-+]?\d+(?:\.\d+)?(?:...)?",
    cleaned, re.IGNORECASE)
```

The leading `\.\d+` alternative ensures `.80` is captured before `0.80`.

---

## 2. Verbatim Text Matching

### Source of the Verbatim Text

Two sources are tried in order:

1. **Inline evidence text** — parsed from the LLM response via `_extract_inline_evidence_text()`:
   ```python
   re.search(r"(?im)^\s*(?:evidence|verbatim)\s*:\s*(.+)$", text)
   ```

2. **Post-hoc verbatim stage** — when the answer type is `boolean` with eligibility, and no inline evidence was found, a second LLM call is made using `_build_verbatim_support_question()`:
   ```
   Find the shortest exact verbatim source span that supports the candidate answer...
   Return exactly one line in this format: VERBATIM: <text>.
   ```
   The result is parsed via `_extract_verbatim_text()` using:
   ```python
   re.search(r"VERBATIM\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
   ```

### Span Offset Computation — `_coerce_prediction_to_source_span()`

Located at line ~601 in `run_surfsense_benchmark.py`. This function:

1. Reads `qa.get("evidence", {}).get("text", "")` — the **document-level evidence text** from the original benchmark file
2. Tries to find the coerced prediction within that evidence text using `_find_text_span()`:
   - **Exact match** — `haystack.find(needle)`
   - **Case-insensitive match** — `haystack.lower().find(needle.lower())`
3. Falls back to `_find_entity_aligned_span()` — numeric entity matching for values like `.80` vs `0.80`

The output `predicted_span_offsets` contains:
```json
{
    "found": true,
    "match_method": "exact",
    "start_offset": 0,
    "end_offset": 3,
    "span_text": ".80",
    "offset_convention": {
        "reference": "evidence_text",
        "library": "python3-str",
        "unit": "unicode_codepoint",
        "index_base": 0,
        "range": "[start_offset, end_offset)"
    }
}
```

**Important caveat:** The reference for these offsets is `"evidence_text"` — a short string (typically `.80`), not the full document. The original document-level offsets in `df_santic_qa.json` (e.g., 35180–35183) are **stale** — they were generated during an earlier document indexing run and do not match the current chunk text.

---

## 3. Post-Matching Enrichment via OpenSearch Chunks

The script `scripts/enrich_evidence_with_opensearch.py` adds `evidence_context` and `display_evidence_text` fields to benchmark results.

### How It Works

**Step 1 — Search OpenSearch** (function `query_opensearch_chunks()`)

Queries all chunk indices in priority order:
```python
CHUNK_INDICES = [
    "surfsense_chunks_1_sandwitch_chunk",   # preserves full tables with headers
    "surfsense_chunks_1_chunk_hybrid",      # markdown-aware, preserves table structure
    "surfsense_chunks_1_chunk_text",        # recursive chunking, may split tables
    "surfsense_chunks_1_chunk_recursive",
]
```

Builds a boolean query: `term metadata.document_id AND match content <search_term>`. The search terms are derived from schema phrases like `"Total annual fund operating expenses"` plus the predicted answer itself.

**Step 2 — Prefer sandwitch_chunk**  

If a chunk from `sandwitch_chunk` contains a markdown table that includes the predicted answer value, it wins immediately. Falls back to any index.

**Step 3 — Parse the markdown table** (`parse_markdown_table_rows()`)

Splits lines starting with `|`, skips separator rows (`|---|---|`), returns a 2D list of cell strings.

**Step 4 — Find the matching cell** (`find_cell_in_table()`)

Matches in this order:
1. **Exact cell** — `cell_norm == target_norm`
2. **Numeric cell** — `abs(float(cell) - float(target)) <= 0.001` (handles `(.03)` via `_extract_numeric()`)
3. **Contains cell** — `target in cell` (e.g., `"80" in ".80"`)

Returns row label, column index, column hint (from header row), and match method.

**Step 5 — Build the structured evidence context string**

```
[pipeline: ba4de1d3a4a73d98.. | strategy: sandwitch_chunk | chunk_size: 256 | index: surfsense_chunks_1_sandwitch_chunk]
--- Table evidence (markdown) ---
 |  |  |  |
 | Class A | Class C | Class I | Class Y
Management fees | .70 | .70 | .70 | .70
...
Total annual fund operating expenses | 1.02 | 1.81 | .80 | .75
...
--- Match: row="Total annual fund operating expenses" | column="Class I" | value=".80" | method=exact_cell ---
--- Column headers:  | Class A | Class C | Class I | Class Y ---
```

The `display_evidence_text` is the raw table markdown (used for sidebar display).

---

## 4. DOM Highlighting in the Framed HTML Viewer

The viewer (`benchmark_results_df_html_qa/df_qa_frame_5q.html`) loads:

- A **sidebar frame** (`df_qa_frame_5q.html` itself) with QA cards and action links
- A **main iframe** showing the rendered document (`df.html`)

### Three-Level Highlighting

| Level | Link | Target | Highlight |
|-------|------|--------|-----------|
| `extraction` | 🔍 Extraction | Single cell value | `<mark>` around `.80` (yellow) |
| `row` | 📋 Evidence text | Row + column header | Blue background on target row + adjacent rows |
| `table` | 📊 Evidence context | Entire table | Blue overlay on full table |

### Matching Strategy — `highlightByTableEvidence()`

Parses the `evidence_context` metadata:
```js
const rowMatch = evidenceCtx.match(/row="([^"]+)"/);
const colMatch = evidenceCtx.match(/column="([^"]+)"/);
const valMatch = evidenceCtx.match(/value="([^"]+)"/);
const headersMatch = evidenceCtx.match(/--- Column headers: (.+) ---/);
```

Then searches the iframe DOM:

1. **Query all `<table>` elements** in the document
2. **Find target row** — scan each row's cells for text containing the row label (whitespace-normalized)
3. **Find column header** — scan all rows for cell text containing the column hint (whitespace-normalized)
4. **Value fallback** — if column header not found, match target row cells by value (exact, contains, or leading-dot)
5. **Apply highlight classes** to the found cell/row/table element(s)

### Critical: Whitespace Normalization

The HTML in `df.html` has newlines inside `<p>` elements:
```html
<p>Class
        I</p>
```

Without normalization, `textContent` produces `"Class\n        I"` and `.includes("class i")` returns `false`. The fix is the `norm()` helper:

```js
const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
```

This collapses all whitespace sequences (`\n`, tabs, multiple spaces) into single spaces, so `norm("Class\n        I")` → `"class i"`.

### Hover vs Click Behavior

- **Hover** (`onmouseenter`) — calls `handleLevelClick(target, level, false)` which highlights without scrolling
- **Mouse leave** (`onmouseleave`) — calls `handleLevelLeave()` → `clearAllHighlights(doc)`
- **Click** — calls `handleLevelClick(target, level, true)` which highlights + scrolls

### The `clearAllHighlights()` Fix

The original code had a sequence bug:
```js
// BUG: class removed BEFORE style reset — the second querySelectorAll found nothing
doc.querySelectorAll('.qa-table-highlight')
    .forEach(el => el.classList.remove('qa-table-highlight'));
doc.querySelectorAll('.qa-table-highlight')  // ← empty!
    .forEach(el => el.style.cssText = '');
```

Fixed by combining into a single pass:
```js
doc.querySelectorAll('.qa-evidence-context, .qa-evidence-context-target, .qa-evidence-col-header, .qa-table-highlight')
    .forEach(el => {
        el.classList.remove(...);
        el.style.cssText = '';  // same element, still referenced
    });
```

### CSS Class Summary

| Class | Effect |
|-------|--------|
| `qa-hit-pred` | Yellow `<mark>` background for cell value match |
| `qa-hit-active` | Cyan glow outline on active mark |
| `qa-hit-muted` | Dimmed inactive marks |
| `qa-evidence-context` | Subtle blue background on adjacent rows |
| `qa-evidence-context-target` | Stronger blue background on target row/cell |
| `qa-evidence-col-header` | Blue background on matching column header |
| `qa-table-highlight` | Blue overlay + outline on entire table |

---

## 5. Data Flow Summary

```
LLM Response (".80" or "0.80")
    │
    ▼
Benchmark Runner (_clean_predicted_answer → _prepare_prediction_for_scoring)
    │  • Extracts last numeric token, preserves leading dot
    │  • Computes span offsets against evidence_text
    ▼
Benchmark Result JSON
    │  Contains: predicted_answer, predicted_span_offsets, intermediate_verbatim_text
    │
    ▼
OpenSearch Enrichment (scripts/enrich_evidence_with_opensearch.py)
    │  • Queries OpenSearch for chunks containing the predicted value
    │  • Parses markdown table, finds matching cell
    │  • Builds structured evidence_context with row/column/value metadata
    ▼
Enriched Result JSON + Payload JS
    │  Contains: evidence_context, display_evidence_text (added)
    │
    ▼
QA Viewer (df_qa_frame_5q.html)
    │  • Reads evidence_context from payload
    │  • highlightByTableEvidence() parses metadata, searches DOM
    │  • norm() handles whitespace normalization
    │  • Three levels: cell/row/table highlighting
    │  • Hover shows, mouse leave clears
    ▼
User sees highlighted table/row/cell in the iframe
```

---

## 6. Key Lessons

1. **Document-level offsets are fragile** — they come from the indexing pipeline and go stale when documents are re-ingested. Do not rely on them for DOM matching.

2. **`norm()` is essential** — PDF→HTML conversion produces `<p>` elements with embedded newlines. Always normalize `\s+` → single space before comparing `textContent`.

3. **Inline `!important` styles are dangerous** — they survive `clearAllHighlights` because the class-based clearing runs first and removes the class, making the subsequent style-reset querySelectorAll miss the element. Use CSS classes, not inline styles.

4. **Table-aware matching beats blind text search** — searching for `.80` in the document finds the wrong occurrence. Using the structured row/column/value metadata from the evidence context is far more reliable.

5. **OpenSearch chunk indices matter** — `sandwitch_chunk` preserves full table structure best. Other indices (recursive, text) may split tables across chunks.

6. **The `.80` → `0.80` normalization** is a persistent LLM behavior. The regex `\.\d+` alternative in numeric extraction is critical to recover the original format.
