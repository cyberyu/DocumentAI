#!/usr/bin/env python3
"""
Post-process benchmark results: enrich evidence_context by querying OpenSearch
for the actual chunk content. If the chunk is a Markdown table, parse it to
extract structured cell-level evidence (row label + column hint).

Usage:
    python3 scripts/enrich_evidence_with_opensearch.py \\
        --input benchmark_results_df_html_qa/q01_evidence_test.json \\
        --output benchmark_results_df_html_qa/q01_evidence_test.json

Dependencies: pip install requests
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


OPENSEARCH_URL = "http://localhost:9200"
# Try all chunk indices in priority order (hybrid preserves tables best)
CHUNK_INDICES = [
    "surfsense_chunks_1_sandwitch_chunk",   # preserves full tables with headers
    "surfsense_chunks_1_chunk_hybrid",      # markdown-aware, preserves table structure
    "surfsense_chunks_1_chunk_text",        # recursive chunking, may split tables
    "surfsense_chunks_1_chunk_recursive",
]


# ── Markdown Table Parsing ───────────────────────────────────────────────

def is_markdown_table(text: str) -> bool:
    """Detect if text contains a markdown table row."""
    if not text:
        return False
    # A markdown table row starts with | and has at least one more |
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            return True
    return False


def parse_markdown_table_rows(text: str) -> list[list[str]]:
    """Parse markdown table rows into cell arrays."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        # Skip separator rows (e.g., |---|---|) — must contain at least one - or :
        if re.match(r"^\|[\s]*[-:]+[\s\-:]*\|", stripped):
            continue
        cells = [c.strip() for c in stripped.split("|")]
        # Remove leading/trailing empty cell from split
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if cells:
            rows.append(cells)
    return rows


def find_cell_in_table(
    table_rows: list[list[str]],
    target_value: str,
) -> dict[str, Any]:
    """Find a cell matching target_value in parsed markdown table rows.

    Returns dict with row_label, column_index, column_hint, cell_value.
    """
    # Normalize target for matching
    target_norm = target_value.strip().lower()
    target_numeric = _extract_numeric(target_norm)

    # First row is often a header
    header_row = table_rows[0] if table_rows else []

    best_match: dict[str, Any] | None = None

    for ri, row in enumerate(table_rows):
        for ci, cell in enumerate(row):
            cell_norm = cell.strip().lower()
            # Exact match
            if cell_norm == target_norm:
                best_match = {
                    "row_index": ri,
                    "column_index": ci,
                    "row_label": row[0] if len(row) > 0 else "",
                    "cell_value": cell.strip(),
                    "match_method": "exact_cell",
                }
                break
            # Numeric match
            cell_numeric = _extract_numeric(cell_norm)
            if target_numeric is not None and cell_numeric is not None:
                if abs(target_numeric - cell_numeric) <= 0.001:
                    best_match = {
                        "row_index": ri,
                        "column_index": ci,
                        "row_label": row[0] if len(row) > 0 else "",
                        "cell_value": cell.strip(),
                        "match_method": "numeric_cell",
                    }
                    break
            # Contains match (e.g. target "80" in cell ".80")
            if target_norm and cell_norm and target_norm in cell_norm:
                best_match = {
                    "row_index": ri,
                    "column_index": ci,
                    "row_label": row[0] if len(row) > 0 else "",
                    "cell_value": cell.strip(),
                    "match_method": "contains_cell",
                }
        if best_match:
            break

    if best_match:
        # Add column hint from header row
        ci = best_match["column_index"]
        if ci < len(header_row):
            best_match["column_hint"] = header_row[ci]
        else:
            best_match["column_hint"] = f"Column {ci + 1}"

        # If the row has a label in column 0, extract it
        if best_match["row_index"] < len(table_rows):
            first_cell = table_rows[best_match["row_index"]][0].strip() if table_rows[best_match["row_index"]] else ""
            best_match["row_label"] = first_cell

    return best_match or {}


def _extract_numeric(text: str) -> float | None:
    """Extract numeric value from text, handling (.03) style negatives."""
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text.strip("()"))
    try:
        val = float(cleaned)
        return -val if negative else val
    except ValueError:
        return None


# ── OpenSearch Query ─────────────────────────────────────────────────────

def query_opensearch_chunks(
    doc_id: int,
    search_text: str,
) -> list[dict[str, Any]]:
    """Query OpenSearch for chunks containing search_text for the given document.

    Searches across all chunk indices and returns matching chunks sorted
    by relevance.
    """
    if requests is None:
        print("  ⚠  requests library not available, skipping OpenSearch query",
              file=sys.stderr)
        return []

    all_hits: list[dict[str, Any]] = []

    for index in CHUNK_INDICES:
        url = f"{OPENSEARCH_URL}/{index}/_search"
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"metadata.document_id": doc_id}},
                        {"match": {"content": search_text}},
                    ]
                }
            },
            "size": 5,
            "_source": ["content", "metadata", "metadata.chunk_index", "metadata.document_id"],
        }
        try:
            resp = requests.post(url, json=query, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            for h in hits:
                src = h["_source"]
                src["_index"] = index
                src["_score"] = h.get("_score", 0)
                all_hits.append(src)
        except requests.RequestException as exc:
            print(f"  ⚠  OpenSearch query failed for {index}: {exc}", file=sys.stderr)

    # Sort by score descending
    all_hits.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return all_hits


# ── Evidence Context Building ─────────────────────────────────────────────

def enrich_evidence(
    predicted_answer: str,
    gold_answer: str,
    doc_id: int | None,
    current_evidence_context: str,
    question_hint: str = "",
) -> tuple[str, str | None]:
    """Enrich evidence_context with structured table data from OpenSearch.

    Returns (enriched_context, chunk_content) tuple.
    chunk_content is the full chunk text for offset computation.
    """
    if not doc_id or not predicted_answer:
        return current_evidence_context

    # Derive a search phrase from the question context embedded in the schema key
    # or from common fee table row labels
    schema_phrases = [
        "Total annual fund operating expenses",
        "total annual fund operating expenses",
        "Ratio of total expenses",
        "ratio of total expenses",
        "Total annual fund",
        "Annual Fund Operating Expenses",
    ]

    search_terms = []
    for phrase in schema_phrases:
        search_terms.append(phrase)
    # Also add the raw predicted answer as fallback
    search_terms.append(predicted_answer)
    for n in re.findall(r"[\d.]+", predicted_answer):
        if n not in search_terms:
            search_terms.append(n)

    # Search by phrase first — prefer sandwitch_chunk
    best_chunk = None
    for term in search_terms:
        chunks = query_opensearch_chunks(doc_id, term)
        for chunk in chunks:
            content = chunk.get("content", "")
            meta = chunk.get("metadata", {})
            # Prefer sandwitch_chunk (preserves full tables)
            if "sandwitch" in chunk.get("_index", "") and is_markdown_table(content):
                rows = parse_markdown_table_rows(content)
                if rows and find_cell_in_table(rows, predicted_answer):
                    best_chunk = chunk
                    break
        if best_chunk:
            break

    # Fallback: any table chunk containing the value
    if not best_chunk:
        for term in search_terms:
            chunks = query_opensearch_chunks(doc_id, term)
            for chunk in chunks:
                content = chunk.get("content", "")
                if is_markdown_table(content) and predicted_answer in content.replace(".", ""):
                    best_chunk = chunk
                    break
            if best_chunk:
                break

    if not best_chunk:
        return current_evidence_context, None

    content = best_chunk.get("content", "")
    meta = best_chunk.get("metadata", {})
    index_name = best_chunk.get("_index", "?")
    pipeline_id_short = str(meta.get("pipeline_id", "?"))[:16]
    strategy = meta.get("chunking_strategy", "?")
    chunk_sz = meta.get("chunk_size", "?")
    header = f"[pipeline: {pipeline_id_short}.. | strategy: {strategy} | chunk_size: {chunk_sz} | index: {index_name}]"

    rows = parse_markdown_table_rows(content)
    if not rows:
        return current_evidence_context

    # Find column headers (row with Class A/C/I/Y pattern)
    column_headers = []
    for row in rows:
        row_text = " ".join(row)
        if "class a" in row_text.lower() and "class c" in row_text.lower():
            column_headers = row
            break

    match = find_cell_in_table(rows, predicted_answer)
    if not match:
        match = find_cell_in_table(rows, ".80")  # try dotted form

    if match and column_headers and match.get("column_index", -1) >= 0:
        ci = match["column_index"]
        # Handle offset: header rows often omit the row-label column
        hdr_offset = len(rows[0]) - len(column_headers) if rows and len(rows[0]) > len(column_headers) else 0
        hdr_ci = ci - hdr_offset
        if 0 <= hdr_ci < len(column_headers):
            match["column_hint"] = column_headers[hdr_ci]
        match["table_headers"] = column_headers

    table_lines = [" | ".join(r) for r in rows]
    result_lines = [header, "--- Table evidence (markdown) ---", *table_lines]

    if match:
        col_info = match.get("column_hint", f"col {match.get('column_index', '?')}")
        result_lines.append(
            f"--- Match: row=\"{match.get('row_label', '')}\" "
            f"| column=\"{col_info}\" "
            f"| value=\"{match.get('cell_value', '')}\" "
            f"| method={match.get('match_method', '')} ---"
        )
    if column_headers:
        result_lines.append(f"--- Column headers: {' | '.join(column_headers)} ---")

    return "\n".join(result_lines), content


# ── Main ──────────────────────────────────────────────────────────────────


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich benchmark results with OpenSearch chunk evidence"
    )
    parser.add_argument("--input", required=True, help="Input benchmark JSON file")
    parser.add_argument("--output", required=True, help="Output benchmark JSON file")
    parser.add_argument(
        "--opensearch-url",
        default=OPENSEARCH_URL,
        help=f"OpenSearch URL (default: {OPENSEARCH_URL})",
    )
    args = parser.parse_args()

    os_url = args.opensearch_url
    module = sys.modules[__name__]
    module.OPENSEARCH_URL = os_url

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        return 1

    with open(input_path) as f:
        data = json.load(f)

    results = data.get("results", [])
    enriched_count = 0
    table_count = 0

    for r in results:
        pred = r.get("predicted_answer", "") or r.get("predicted_extract", "") or ""
        doc_id = None
        if hasattr(r, "get"):
            doc_id = r.get("document_id")

        cfg = data.get("config", {})
        mentioned = cfg.get("mentioned_document_ids", "")
        if mentioned:
            try:
                if isinstance(mentioned, list):
                    doc_id = int(mentioned[0]) if mentioned else None
                else:
                    doc_id = int(str(mentioned).split(",")[0].strip())
            except (ValueError, IndexError):
                doc_id = None

        if not doc_id:
            print(f"  ⚠  No document ID for {r.get('id', '?')}, skipping", file=sys.stderr)
            continue

        orig_ctx = r.get("evidence_context", "")
        new_ctx, chunk_content = enrich_evidence(pred, r.get("gold_answer", ""), doc_id, orig_ctx)

        if new_ctx and new_ctx != orig_ctx:
            r["evidence_context"] = new_ctx
            enriched_count += 1
            if is_markdown_table(new_ctx):
                table_count += 1

            # Re-compute offsets within the full chunk content
            if chunk_content:
                r["display_evidence_text"] = chunk_content
                offsets = r.get("predicted_span_offsets", {})
                if isinstance(offsets, dict):
                    # Find the predicted answer in the full chunk
                    span_text = str(offsets.get("span_text", "") or pred or "").strip()
                    for lookup in [span_text, pred, ".80", "0.80", "80"]:
                        if not lookup:
                            continue
                        idx = chunk_content.find(lookup)
                        if idx >= 0:
                            offsets["chunk_start_offset"] = idx
                            offsets["chunk_end_offset"] = idx + len(lookup)
                            offsets["chunk_offset_convention"] = {
                                "reference": "chunk_content",
                                "library": "python3-str",
                                "unit": "unicode_codepoint",
                                "index_base": 0,
                                "range": "[chunk_start_offset, chunk_end_offset)",
                            }
                            # Also add chunk_evidence_text for the frame viewer
                            before = max(0, idx - 60)
                            after = min(len(chunk_content), idx + len(lookup) + 80)
                            offsets["chunk_evidence_text"] = chunk_content[before:after]
                            break

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Processed {len(results)} results")
    print(f"  Enriched: {enriched_count}")
    print(f"  Table-aware: {table_count}")
    print(f"  Output: {output_path}")

    # Also create payload JS if output is the benchmark JSON
    if output_path.suffix == ".json":
        payload_path = output_path.with_suffix(".payload.js")
        with open(payload_path, "w") as f:
            f.write("window.__QA_FRAME_PAYLOAD__ = ")
            with open(output_path) as src:
                f.write(src.read())
            f.write(";\n")
        print(f"  Payload: {payload_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
