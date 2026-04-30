#!/usr/bin/env python3
"""Local pipeline grid-search benchmark — DeepSeek V4 API variant.

Identical retrieval pipeline as grid_search_local_pipeline.py, but calls
the DeepSeek V4 API with thinking mode enabled instead of a local vLLM server.

Key differences from the base script:
 - LLM endpoint  : https://api.deepseek.com/chat/completions
 - Model         : deepseek-v4-flash  (supports thinking mode)
 - Thinking mode : enabled  (reasoning_effort="high")
 - API key       : prompted interactively at startup (never stored in code)
 - temperature / top_p etc. are NOT sent (not supported in thinking mode)
 - Response read from choices[0].message.content (final answer, not reasoning_content)

Usage
-----
# Single best config, all 100 questions:
    conda run -n ai python3 scripts/grid_search_local_pipeline_deepseek.py \\
        --group all \\
        --configs local_nodatefilter_k60_top20_chunks20_markers \\
        --file-prefix "deepseek_v4pro_"

# Full focussed grid on G1 only:
    conda run -n ai python3 scripts/grid_search_local_pipeline_deepseek.py \\
        --group G1 \\
        --file-prefix "deepseek_v4pro_"
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, date
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from run_surfsense_benchmark import (   # noqa: E402
    _aggregate,
    _now_utc,
    _rewrite_question_for_retrieval,
    evaluate_answer,
    load_benchmark,
    write_outputs,
)

OUTPUT_DIR    = Path("benchmark_results_MSFT_FY26Q1_qa")
BENCH_FILE    = Path("msft_fy26q1_qa_benchmark_100_sanitized.json")
REPORT_OUT    = OUTPUT_DIR / "grid_local_pipeline_deepseek_report.html"

DB_HOST       = "172.19.0.4"
DB_PORT       = 5432
DB_NAME       = "surfsense"
DB_USER       = "surfsense"
DB_PASS       = "surfsense"
SEARCH_SPACE  = 1           # resolved at runtime

EMBED_MODEL        = "sentence-transformers/all-MiniLM-L6-v2"
DEEPSEEK_BASE_URL  = "https://api.deepseek.com"
DEEPSEEK_MODEL     = "deepseek-v4-flash"
DEEPSEEK_API_KEY   = ""     # set interactively in main()
DEEPSEEK_TIMEOUT   = 300.0
MAX_TOKENS         = 8192
TRUNC_TOKENS       = 28000  # matches production truncate_prompt_tokens

# ---------------------------------------------------------------------------
# Grid definition  (identical to the base script)
# ---------------------------------------------------------------------------
FOCUSSED_GRID: list[dict[str, Any]] = [
    # ── Baseline ─────────────────────────────────────────────────────────
    dict(key="local_nodatefilter_k60_top10_chunks20_markers",
         label="No-date / k=60 / top10 / chunks20 / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=10, max_chunks_per_doc=20, matched_markers=True),

    dict(key="local_forceddate_k60_top10_chunks20_markers",
         label="Forced-date / k=60 / top10 / chunks20 / markers ON",
         query_rewrite=True,  date_filter="force",
         rrf_k=60, top_k=10, max_chunks_per_doc=20, matched_markers=True),

    dict(key="local_nodatefilter_k60_top10_chunks20_nomarkers",
         label="No-date / k=60 / top10 / chunks20 / markers OFF",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=10, max_chunks_per_doc=20, matched_markers=False),

    dict(key="local_nodatefilter_k60_top10_chunks20_raw",
         label="No-date / k=60 / top10 / chunks20 / raw-Q",
         query_rewrite=False, date_filter="none",
         rrf_k=60, top_k=10, max_chunks_per_doc=20, matched_markers=True),

    # ── RRF k sweep ──────────────────────────────────────────────────────
    dict(key="local_nodatefilter_k20_top10_chunks20_markers",
         label="No-date / k=20 / top10 / chunks20 / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=20, top_k=10, max_chunks_per_doc=20, matched_markers=True),

    dict(key="local_nodatefilter_k120_top10_chunks20_markers",
         label="No-date / k=120 / top10 / chunks20 / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=120, top_k=10, max_chunks_per_doc=20, matched_markers=True),

    # ── top_k sweep ───────────────────────────────────────────────────────
    dict(key="local_nodatefilter_k60_top5_chunks20_markers",
         label="No-date / k=60 / top5 / chunks20 / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=5, max_chunks_per_doc=20, matched_markers=True),

    dict(key="local_nodatefilter_k60_top20_chunks20_markers",
         label="No-date / k=60 / top20 / chunks20 / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=20, max_chunks_per_doc=20, matched_markers=True),

    # ── max_chunks_per_doc sweep ─────────────────────────────────────────
    dict(key="local_nodatefilter_k60_top10_chunks5_markers",
         label="No-date / k=60 / top10 / chunks5 / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=10, max_chunks_per_doc=5,  matched_markers=True),

    dict(key="local_nodatefilter_k60_top10_chunks50_markers",
         label="No-date / k=60 / top10 / chunks50 / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=10, max_chunks_per_doc=50, matched_markers=True),

    dict(key="local_nodatefilter_k60_top10_chunksall_markers",
         label="No-date / k=60 / top10 / chunks-all / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=10, max_chunks_per_doc=None, matched_markers=True),

    # ── Inferred date filter ──────────────────────────────────────────────
    dict(key="local_inferdate_k60_top10_chunks20_markers",
         label="Infer-date / k=60 / top10 / chunks20 / markers ON",
         query_rewrite=True,  date_filter="infer",
         rrf_k=60, top_k=10, max_chunks_per_doc=20, matched_markers=True),

    # ── Best-guess combos ─────────────────────────────────────────────────
    dict(key="local_nodatefilter_k60_top20_chunksall_markers",
         label="No-date / k=60 / top20 / chunks-all / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=20, max_chunks_per_doc=None, matched_markers=True),

    dict(key="local_nodatefilter_k60_top10_chunks20_raw_nomarkers",
         label="No-date / k=60 / top10 / chunks20 / raw-Q / no-markers",
         query_rewrite=False, date_filter="none",
         rrf_k=60, top_k=10, max_chunks_per_doc=20, matched_markers=False),

    dict(key="local_nodatefilter_k60_top3_chunksall_markers",
         label="No-date / k=60 / top3 / chunks-all / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=60, top_k=3, max_chunks_per_doc=None, matched_markers=True),

    dict(key="local_nodatefilter_k120_top20_chunksall_markers",
         label="No-date / k=120 / top20 / chunks-all / markers ON",
         query_rewrite=True,  date_filter="none",
         rrf_k=120, top_k=20, max_chunks_per_doc=None, matched_markers=True),
]


# ---------------------------------------------------------------------------
# Database helpers  (unchanged from base script)
# ---------------------------------------------------------------------------

def _db_connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _resolve_search_space(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM searchspaces LIMIT 1")
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("No search spaces found in database")
    return int(row["id"])


# ---------------------------------------------------------------------------
# Date filter helpers  (unchanged from base script)
# ---------------------------------------------------------------------------

_FISCAL_QTR_RE = re.compile(
    r'\bFY(\d{2,4})Q([1-4])\b'
    r'|fiscal\s+(?:quarter\s+)?(?:Q([1-4])\s+)?(?:of\s+)?(?:FY\s*)?(\d{4})'
    r'|three\s+months\s+ended\s+(September|March|June|December)\s+\d{1,2},?\s+(\d{4})',
    re.IGNORECASE
)

_QTR_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
_MONTH_TO_QTR_END = {
    "september": (2026, 9, 30),
    "march":     (2026, 3, 31),
    "june":      (2026, 6, 30),
    "december":  (2025, 12, 31),
}


def _infer_date_filter(question: str) -> tuple[datetime | None, datetime | None]:
    m = _FISCAL_QTR_RE.search(question)
    if not m:
        return None, None

    if m.group(1) and m.group(2):
        yr_raw, qtr = int(m.group(1)), int(m.group(2))
        yr = yr_raw if yr_raw > 100 else 2000 + yr_raw
        mo_start, mo_end = _QTR_MONTHS[qtr]
        import calendar
        _, last_day = calendar.monthrange(yr, mo_end)
        start = datetime(yr, mo_start, 1, tzinfo=UTC)
        end   = datetime(yr, mo_end, last_day, 23, 59, 59, tzinfo=UTC)
        return start, end

    if m.group(5):
        mon_name = m.group(5).lower()
        if mon_name in _MONTH_TO_QTR_END:
            yr, mo, dy = _MONTH_TO_QTR_END[mon_name]
            import calendar
            _, last_day = calendar.monthrange(yr, mo)
            end = datetime(yr, mo, last_day, 23, 59, 59, tzinfo=UTC)
            if mo == 9:
                start = datetime(yr, 7, 1, tzinfo=UTC)
            elif mo == 3:
                start = datetime(yr, 1, 1, tzinfo=UTC)
            elif mo == 6:
                start = datetime(yr, 4, 1, tzinfo=UTC)
            else:
                start = datetime(yr - 1, 10, 1, tzinfo=UTC)
            return start, end

    return None, None


def _forced_date_filter() -> tuple[datetime, datetime]:
    return datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Embedding  (unchanged from base script)
# ---------------------------------------------------------------------------

_embed_model: SentenceTransformer | None = None

def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        print(f"[{_now_utc()}] Loading embedding model {EMBED_MODEL} ...", flush=True)
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def _embed(text: str) -> list[float]:
    return _get_embed_model().encode(text, normalize_embeddings=True).tolist()


# ---------------------------------------------------------------------------
# RRF hybrid search  (unchanged from base script)
# ---------------------------------------------------------------------------

def rrf_hybrid_search(
    conn,
    query_text: str,
    search_space_id: int,
    *,
    rrf_k: int = 60,
    top_k: int = 10,
    max_chunks_per_doc: int | None = 20,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[dict]:
    query_embedding = _embed(query_text)
    n_results = top_k * 5

    date_sql_parts = []
    date_params: list[Any] = []
    if start_date is not None:
        date_sql_parts.append("d.updated_at >= %s")
        date_params.append(start_date)
    if end_date is not None:
        date_sql_parts.append("d.updated_at <= %s")
        date_params.append(end_date)
    date_where = (" AND " + " AND ".join(date_sql_parts)) if date_sql_parts else ""

    rrf_sql = f"""
WITH semantic_search AS (
    SELECT c.id,
           RANK() OVER (ORDER BY c.embedding <=> %s::vector) AS rank
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE d.search_space_id = %s
      {date_where}
    ORDER BY c.embedding <=> %s::vector
    LIMIT %s
),
keyword_search AS (
    SELECT c.id,
           RANK() OVER (ORDER BY ts_rank_cd(to_tsvector('english', c.content),
                                            plainto_tsquery('english', %s)) DESC) AS rank
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE d.search_space_id = %s
      {date_where}
      AND to_tsvector('english', c.content) @@ plainto_tsquery('english', %s)
    ORDER BY ts_rank_cd(to_tsvector('english', c.content),
                        plainto_tsquery('english', %s)) DESC
    LIMIT %s
),
rrf AS (
    SELECT COALESCE(s.id, k.id) AS chunk_id,
           COALESCE(1.0 / (%s + s.rank), 0.0)
         + COALESCE(1.0 / (%s + k.rank), 0.0) AS score
    FROM semantic_search s
    FULL OUTER JOIN keyword_search k ON s.id = k.id
    ORDER BY score DESC
    LIMIT %s
)
SELECT rrf.chunk_id, rrf.score,
       c.content, c.document_id,
       d.title, d.document_metadata
FROM rrf
JOIN chunks c ON c.id = rrf.chunk_id
JOIN documents d ON d.id = c.document_id
ORDER BY rrf.score DESC
"""
    vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    params: list[Any] = (
        [vec_str, search_space_id] + date_params + [vec_str, n_results]
        + [query_text, search_space_id] + date_params + [query_text, query_text, n_results]
        + [rrf_k, rrf_k, top_k]
    )

    with conn.cursor() as cur:
        cur.execute(rrf_sql, params)
        rrf_rows = cur.fetchall()

    if not rrf_rows:
        return []

    doc_scores:   dict[int, float] = {}
    doc_order:    list[int] = []
    matched_ids:  dict[int, set[int]] = {}
    doc_meta:     dict[int, dict] = {}

    for row in rrf_rows:
        doc_id  = int(row["document_id"])
        cid     = int(row["chunk_id"])
        score   = float(row["score"])
        if doc_id not in doc_scores:
            doc_scores[doc_id] = score
            doc_order.append(doc_id)
            matched_ids[doc_id] = set()
            doc_meta[doc_id] = {
                "id": doc_id,
                "title": row["title"],
                "document_type": "FILE",
                "metadata": row["document_metadata"] or {},
            }
        else:
            doc_scores[doc_id] = max(doc_scores[doc_id], score)
        matched_ids[doc_id].add(cid)

    final_doc_ids = doc_order[:top_k]

    if max_chunks_per_doc is None:
        chunk_sql = """
            SELECT c.id AS chunk_id, c.content, c.document_id
            FROM chunks c
            WHERE c.document_id = ANY(%s)
            ORDER BY c.document_id, c.id
        """
        chunk_params = [final_doc_ids]
    else:
        all_matched = [cid for ids in matched_ids.values() for cid in ids]
        chunk_sql = """
            SELECT chunk_id, content, document_id FROM (
                SELECT c.id AS chunk_id, c.content, c.document_id,
                       ROW_NUMBER() OVER (PARTITION BY c.document_id ORDER BY c.id) AS rn
                FROM chunks c
                WHERE c.document_id = ANY(%s)
            ) sub
            WHERE rn <= %s OR chunk_id = ANY(%s)
            ORDER BY document_id, chunk_id
        """
        chunk_params = [final_doc_ids, max_chunks_per_doc, all_matched or [0]]

    with conn.cursor() as cur:
        cur.execute(chunk_sql, chunk_params)
        chunk_rows = cur.fetchall()

    doc_map: dict[int, dict] = {
        did: {
            "document_id": did,
            "score": float(doc_scores[did]),
            "chunks": [],
            "matched_chunk_ids": sorted(matched_ids.get(did, set())),
            "document": doc_meta[did],
        }
        for did in final_doc_ids
    }
    for row in chunk_rows:
        did = int(row["document_id"])
        if did in doc_map:
            doc_map[did]["chunks"].append({
                "chunk_id": int(row["chunk_id"]),
                "content": row["content"],
            })

    return [doc_map[did] for did in final_doc_ids]


# ---------------------------------------------------------------------------
# Context assembly  (unchanged from base script)
# ---------------------------------------------------------------------------

def _build_context_xml(docs: list[dict], matched_markers: bool) -> str:
    parts: list[str] = []
    for doc in docs:
        matched = set(doc.get("matched_chunk_ids", [])) if matched_markers else set()
        doc_meta = doc.get("document", {})
        doc_id   = doc_meta.get("id", doc.get("document_id", "unknown"))
        title    = doc_meta.get("title", "Untitled")
        metadata = doc_meta.get("metadata") or {}
        metadata_json = json.dumps(metadata, ensure_ascii=False)

        lines: list[str] = [
            "<document>",
            "<document_metadata>",
            f"  <document_id>{doc_id}</document_id>",
            f"  <document_type>FILE</document_type>",
            f"  <title><![CDATA[{title}]]></title>",
            f"  <metadata_json><![CDATA[{metadata_json}]]></metadata_json>",
            "</document_metadata>",
            "",
        ]

        chunks = doc.get("chunks", [])
        chunk_entries: list[tuple[int | None, str]] = []
        for chunk in chunks:
            cid     = chunk.get("chunk_id")
            content = str(chunk.get("content", "")).strip()
            if not content:
                continue
            if cid is None:
                xml = f"  <chunk><![CDATA[{content}]]></chunk>"
            else:
                xml = f"  <chunk id='{cid}'><![CDATA[{content}]]></chunk>"
            chunk_entries.append((cid, xml))

        index_overhead = 1 + len(chunk_entries) + 1 + 1 + 1
        first_chunk_line = len(lines) + index_overhead + 1
        current_line = first_chunk_line
        index_entries: list[str] = []
        for cid, xml_str in chunk_entries:
            num_lines = xml_str.count("\n") + 1
            end_line  = current_line + num_lines - 1
            matched_attr = ' matched="true"' if cid is not None and cid in matched else ""
            if cid is not None:
                index_entries.append(
                    f'  <entry chunk_id="{cid}" lines="{current_line}-{end_line}"{matched_attr}/>'
                )
            else:
                index_entries.append(
                    f'  <entry lines="{current_line}-{end_line}"{matched_attr}/>'
                )
            current_line = end_line + 1

        lines.append("<chunk_index>")
        lines.extend(index_entries)
        lines.append("</chunk_index>")
        lines.append("")
        lines.append("<document_content>")
        for _, xml_str in chunk_entries:
            lines.append(xml_str)
        lines.extend(["</document_content>", "</document>"])
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Token-budget truncation
# ---------------------------------------------------------------------------

def _truncate_to_token_budget(context: str, budget_tokens: int = TRUNC_TOKENS) -> str:
    max_chars = budget_tokens * 4
    if len(context) > max_chars:
        return context[:max_chars] + "\n... [TRUNCATED]"
    return context


# ---------------------------------------------------------------------------
# LLM call — DeepSeek V4 API with thinking mode
# ---------------------------------------------------------------------------

def _call_llm(question: str, context: str) -> str:
    """Call the DeepSeek V4 API with thinking mode enabled.

    DeepSeek thinking mode notes:
      - temperature, top_p, presence_penalty, frequency_penalty are NOT supported
        and have no effect when thinking is enabled.
      - reasoning_content  : chain-of-thought (discarded here)
      - content            : final answer (what we use)
      - thinking toggle defaults to enabled, but we set it explicitly for clarity.
    """
    system_prompt = (
        "You are a precise financial document analyst. "
        "Answer questions using only the provided document context. "
        "Return ONE final numeric value with its unit and no extra prose. "
        "If the answer is not found, return exactly: N/A"
    )
    user_msg = (
        f"Document context:\n<documents>\n{context}\n</documents>\n\n"
        f"Question: {question}\n\n"
        "Return only the final answer value with unit. No explanation."
    )

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ],
        "max_tokens": MAX_TOKENS,
        # Thinking mode parameters (OpenAI-format raw HTTP)
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        # NOTE: temperature is intentionally omitted — not supported in thinking mode
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=DEEPSEEK_TIMEOUT) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    choices = result.get("choices", [])
    if not choices:
        return ""
    msg = choices[0].get("message", {})
    # Use content (final answer); reasoning_content is the chain-of-thought
    return msg.get("content", "").strip()


# ---------------------------------------------------------------------------
# Per-question runner  (unchanged logic from base script)
# ---------------------------------------------------------------------------

def _run_question(
    conn,
    qa: dict,
    cfg: dict,
    search_space_id: int,
) -> dict:
    qid   = str(qa.get("id", ""))
    group = str(qa.get("group", "unknown"))
    raw_q = str(qa.get("question", "")).strip()
    gold  = str(qa.get("answer", "")).strip()

    retrieval_q = _rewrite_question_for_retrieval(raw_q) if cfg["query_rewrite"] else raw_q

    if cfg["date_filter"] == "none":
        start_date, end_date = None, None
    elif cfg["date_filter"] == "force":
        start_date, end_date = _forced_date_filter()
    else:
        start_date, end_date = _infer_date_filter(raw_q)

    docs = rrf_hybrid_search(
        conn,
        retrieval_q,
        search_space_id,
        rrf_k=cfg["rrf_k"],
        top_k=cfg["top_k"],
        max_chunks_per_doc=cfg["max_chunks_per_doc"],
        start_date=start_date,
        end_date=end_date,
    )

    chunk_count   = sum(len(d.get("chunks", [])) for d in docs)
    matched_count = sum(len(d.get("matched_chunk_ids", [])) for d in docs)

    context_xml = _build_context_xml(docs, matched_markers=cfg["matched_markers"])
    context_xml = _truncate_to_token_budget(context_xml)

    pred = ""
    llm_error = ""
    if docs:
        try:
            pred = _call_llm(raw_q, context_xml)
        except Exception as exc:
            llm_error = str(exc)
            pred = f"ERROR: {exc}"
    else:
        pred = "N/A (no chunks retrieved)"

    ev = evaluate_answer(gold, pred)

    return {
        "id": qid,
        "group": group,
        "question": raw_q,
        "retrieval_query": retrieval_q,
        "gold_answer": gold,
        "predicted_answer": pred,
        "pipeline_telemetry": {
            "date_filter": {
                "start": start_date.isoformat() if start_date else None,
                "end":   end_date.isoformat()   if end_date   else None,
            },
            "docs_retrieved": len(docs),
            "chunks_total":   chunk_count,
            "matched_chunks": matched_count,
            "context_chars":  len(context_xml),
            "llm_error":      llm_error,
        },
        "metrics": {
            "cleaned_prediction":  ev.cleaned_prediction,
            "answer_clean":        ev.answer_clean,
            "semantic_intent_ok":  ev.semantic_intent_ok,
            "strict_exact":        ev.strict_exact,
            "normalized_exact":    ev.normalized_exact,
            "contains_gold":       ev.contains_gold,
            "number_match":        ev.number_match,
            "unit_match":          ev.unit_match,
            "numeric_precision":   ev.numeric_precision,
            "numeric_recall":      ev.numeric_recall,
            "numeric_f1":          ev.numeric_f1,
            "primary_value_match": ev.primary_value_match,
            "token_f1":            ev.token_f1,
            "strict_correct":      ev.strict_correct,
            "lenient_correct":     ev.lenient_correct,
            "overall_correct":     ev.overall_correct,
        },
    }


# ---------------------------------------------------------------------------
# Per-config runner
# ---------------------------------------------------------------------------

def _run_config(
    conn,
    qas: list[dict],
    cfg: dict,
    search_space_id: int,
    *,
    file_prefix: str = "",
) -> dict:
    fname    = f"{file_prefix}{cfg['key']}"
    out_json = OUTPUT_DIR / f"{fname}.json"
    print(f"[{_now_utc()}] CONFIG: {cfg['label']}  [prefix={file_prefix!r}]", flush=True)
    print(f"  query_rewrite={cfg['query_rewrite']}  date_filter={cfg['date_filter']!r}", flush=True)
    print(f"  rrf_k={cfg['rrf_k']}  top_k={cfg['top_k']}  "
          f"max_chunks={cfg['max_chunks_per_doc']}  matched_markers={cfg['matched_markers']}", flush=True)
    print(f"{'='*72}", flush=True)

    results: list[dict] = []
    for idx, qa in enumerate(qas, 1):
        qid = qa.get("id", f"Q{idx:03d}")
        print(f"  [{_now_utc()}] ({idx}/{len(qas)}) {qid} ...", flush=True, end="")
        row = _run_question(conn, qa, cfg, search_space_id)
        correct   = row["metrics"]["overall_correct"]
        tel       = row["pipeline_telemetry"]
        pred_short = row["metrics"].get("cleaned_prediction", "")[:60]
        print(
            f" {'✔' if correct else '✘'}  "
            f"docs={tel['docs_retrieved']} chunks={tel['chunks_total']} "
            f"matched={tel['matched_chunks']}  "
            f"pred={pred_short!r}",
            flush=True,
        )
        results.append(row)

    by_group: dict[str, Any] = {}
    for g in sorted({r["group"] for r in results}):
        by_group[g] = _aggregate([r for r in results if r["group"] == g])

    summary = _aggregate(results)
    payload = {
        "config": cfg,
        "file_prefix": file_prefix,
        "llm_model": DEEPSEEK_MODEL,
        "llm_endpoint": DEEPSEEK_BASE_URL,
        "thinking_mode": True,
        "generated_at_utc": _now_utc(),
        "summary": summary,
        "by_group": by_group,
        "results": results,
    }

    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"[{_now_utc()}] {fname} → "
        f"{summary['overall_correct_count']}/{summary['run']} correct "
        f"({summary['overall_correct_rate']:.0%})",
        flush=True,
    )
    return payload


# ---------------------------------------------------------------------------
# HTML report  (same as base script, adapted header)
# ---------------------------------------------------------------------------

def generate_report(payloads: list[dict]) -> None:
    if not payloads:
        print("No payloads to report.", flush=True)
        return

    all_ids: list[str] = []
    seen: set[str] = set()
    for p in payloads:
        for r in p.get("results", []):
            qid = r["id"]
            if qid not in seen:
                seen.add(qid)
                all_ids.append(qid)

    idx_map = {p["config"]["key"]: {r["id"]: r for r in p.get("results", [])} for p in payloads}

    def _badge(ok: bool | None) -> str:
        if ok is True:  return '<span style="color:#0a7c0a;font-weight:700;">✔</span>'
        if ok is False: return '<span style="color:#c0392b;font-weight:700;">✘</span>'
        return '<span style="color:#999;">—</span>'

    def _pct(v: float) -> str: return f"{v:.0%}"

    header_th = "".join(
        f'<th style="background:#2c3e50;color:#ecf0f1;padding:6px 10px;font-size:0.8em;'
        f'white-space:nowrap;writing-mode:vertical-rl;transform:rotate(180deg);min-height:120px;">'
        f'{p["config"]["label"]}</th>'
        for p in payloads
    )

    def _summary_row(key: str, label: str, fmt=_pct) -> str:
        vals = [p["summary"].get(key, 0.0) for p in payloads]
        max_v = max(vals) if vals else 0.0
        cells = "".join(
            f'<td style="text-align:center;font-size:0.85em;'
            f'{"font-weight:700;background:#fffde7;" if abs(v - max_v) < 1e-9 and max_v > 0 else ""}">'
            f'{fmt(v)}</td>'
            for v in vals
        )
        return f"<tr><td style='white-space:nowrap;font-size:0.85em;'><b>{label}</b></td>{cells}</tr>"

    count_cells = "".join(
        f'<td style="text-align:center;font-size:0.85em;">'
        f'{p["summary"]["overall_correct_count"]}/{p["summary"]["run"]}</td>'
        for p in payloads
    )

    param_rows = ""
    for pname, plabel in [
        ("query_rewrite",    "Query rewrite"),
        ("date_filter",      "Date filter"),
        ("rrf_k",            "RRF k"),
        ("top_k",            "top_k"),
        ("max_chunks_per_doc", "max chunks/doc"),
        ("matched_markers",  "Matched markers"),
    ]:
        cells = "".join(
            f'<td style="text-align:center;font-size:0.75em;color:#444;">'
            f'{str(p["config"].get(pname,""))}</td>'
            for p in payloads
        )
        param_rows += f"<tr><td style='font-size:0.75em;color:#888;'>{plabel}</td>{cells}</tr>"

    summary_html = f"""
<table style="border-collapse:collapse;font-family:Arial,sans-serif;width:100%;">
<thead>
  <tr>
    <th style="background:#2c3e50;color:#ecf0f1;padding:6px 10px;text-align:left;">Metric / Config</th>
    {header_th}
  </tr>
</thead>
<tbody>
  {param_rows}
  <tr><td colspan="{1+len(payloads)}" style="background:#eee;font-size:0.7em;padding:2px 6px;"><b>─── METRICS ───</b></td></tr>
  <tr><td style="white-space:nowrap;font-size:0.85em;"><b>Count correct</b></td>{count_cells}</tr>
  {_summary_row("overall_correct_rate",  "Overall correct %")}
  {_summary_row("normalized_exact_rate", "Norm exact %")}
  {_summary_row("number_match_rate",     "Number match %")}
  {_summary_row("unit_match_rate",       "Unit match %")}
  {_summary_row("mean_token_f1",         "Mean token F1", fmt=lambda v: f"{v:.4f}")}
</tbody>
</table>"""

    q_header = "".join(
        f'<th style="background:#34495e;color:#ecf0f1;padding:4px 6px;font-size:0.75em;'
        f'white-space:nowrap;">{p["config"]["key"].replace("local_","")[:30]}</th>'
        for p in payloads
    )
    q_rows = ""
    for qid in all_ids:
        gold = next((idx_map[p["config"]["key"]][qid]["gold_answer"]
                     for p in payloads if qid in idx_map[p["config"]["key"]]), "")
        cells = ""
        for p in payloads:
            r = idx_map[p["config"]["key"]].get(qid)
            if r is None:
                cells += '<td style="color:#aaa;text-align:center;">—</td>'
                continue
            ok    = r["metrics"].get("overall_correct")
            pred  = (r["metrics"].get("cleaned_prediction") or r.get("predicted_answer",""))[:80]
            tel   = r.get("pipeline_telemetry", {})
            bg    = "#eafaf1" if ok else "#fdecea"
            cells += (
                f'<td style="background:{bg};padding:3px 6px;font-size:0.75em;">'
                f'{_badge(ok)} {pred}<br>'
                f'<span style="color:#888;font-size:0.7em;">'
                f'd={tel.get("docs_retrieved",0)} c={tel.get("chunks_total",0)} '
                f'm={tel.get("matched_chunks",0)}</span></td>'
            )
        gold_s = gold[:50] + ("…" if len(gold) > 50 else "")
        q_rows += (
            f"<tr>"
            f'<td style="padding:3px 6px;font-weight:600;font-size:0.8em;white-space:nowrap;">{qid}</td>'
            f'<td style="padding:3px 6px;font-size:0.8em;color:#555;">{gold_s}</td>'
            f"{cells}"
            f"</tr>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Local Pipeline Grid Search Report — DeepSeek V4</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; background: #f8f9fa; color: #212529; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.1em; margin-top: 24px; color: #2c3e50;
     border-bottom: 2px solid #2c3e50; padding-bottom: 4px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #dee2e6; vertical-align: top; }}
</style>
</head>
<body>
<h1>Local Pipeline Grid Search — DeepSeek V4 (thinking) — {len(payloads)} configs × {len(all_ids)} questions</h1>
<p style="color:#555;font-size:0.9em;">
Generated {_now_utc()} &nbsp;|&nbsp;
DB: {DB_HOST}:{DB_PORT}/{DB_NAME} &nbsp;|&nbsp;
Embed: {EMBED_MODEL} &nbsp;|&nbsp;
LLM: {DEEPSEEK_MODEL} @ {DEEPSEEK_BASE_URL} (thinking=enabled) &nbsp;|&nbsp;
Web search: always OFF
</p>

<h2>Summary — all configs</h2>
{summary_html}

<h2>Per-question results</h2>
<table>
<thead>
  <tr>
    <th style="background:#2c3e50;color:#ecf0f1;padding:4px 8px;">Q ID</th>
    <th style="background:#2c3e50;color:#ecf0f1;padding:4px 8px;">Gold</th>
    {q_header}
  </tr>
</thead>
<tbody>
{q_rows}
</tbody>
</table>
</body>
</html>
"""
    REPORT_OUT.write_text(html, encoding="utf-8")
    print(f"[{_now_utc()}] Report: {REPORT_OUT}", flush=True)


# ---------------------------------------------------------------------------
# Full grid builder  (unchanged from base script)
# ---------------------------------------------------------------------------

def _build_full_grid() -> list[dict]:
    grid = []
    for qr in (True, False):
        for df in ("none", "force", "infer"):
            for k in (20, 60, 120):
                for tk in (5, 10, 20):
                    for mc in (5, 20, None):
                        for mm in (True, False):
                            key = (
                                f"local_{'rewrite' if qr else 'raw'}"
                                f"_{df}_k{k}_top{tk}"
                                f"_chunks{'all' if mc is None else mc}"
                                f"_{'markers' if mm else 'nomarkers'}"
                            )
                            grid.append(dict(
                                key=key,
                                label=key.replace("local_","").replace("_"," / "),
                                query_rewrite=qr, date_filter=df,
                                rrf_k=k, top_k=tk,
                                max_chunks_per_doc=mc, matched_markers=mm,
                            ))
    return grid


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    global OUTPUT_DIR, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY, DB_HOST

    ap = argparse.ArgumentParser(
        description="Local pipeline grid search benchmark — DeepSeek V4 API with thinking mode"
    )
    ap.add_argument("--benchmark-file", default=str(BENCH_FILE))
    ap.add_argument("--max-questions", type=int, default=10,
                    help="Number of questions from top of file (ignored when --group is set)")
    ap.add_argument("--group", default=None, choices=["G1", "G2", "G3", "all"],
                    help="Filter questions to a specific group (or 'all' for G1+G2+G3)")
    ap.add_argument("--question-ids", default=None,
                    help="Comma-separated IDs to run instead of top-N")
    ap.add_argument("--output-dir", default=str(OUTPUT_DIR))
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--full-grid", action="store_true",
                    help="Run all 108 parameter combinations (slow + expensive)")
    ap.add_argument("--configs", default=None,
                    help="Comma-separated config keys to run")
    ap.add_argument("--db-host", default=DB_HOST)
    ap.add_argument("--deepseek-url", default=DEEPSEEK_BASE_URL,
                    help="DeepSeek API base URL (default: https://api.deepseek.com)")
    ap.add_argument("--deepseek-model", default=DEEPSEEK_MODEL,
                    help="DeepSeek model name (default: deepseek-v4-flash)")
    ap.add_argument("--file-prefix", default="deepseek_",
                    help="Prefix for output filenames (default: 'deepseek_')")
    args = ap.parse_args()

    OUTPUT_DIR        = Path(args.output_dir)
    DEEPSEEK_BASE_URL = args.deepseek_url
    DEEPSEEK_MODEL    = args.deepseek_model
    DB_HOST           = args.db_host
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── API key: env-var first, then interactive prompt ────────────────────
    import os
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    print("DeepSeek API — thinking mode benchmark")
    print(f"  Model   : {DEEPSEEK_MODEL}")
    print(f"  Endpoint: {DEEPSEEK_BASE_URL}")
    print()
    if DEEPSEEK_API_KEY:
        print("  API key : (from DEEPSEEK_API_KEY environment variable)")
    else:
        DEEPSEEK_API_KEY = getpass.getpass("Enter your DeepSeek API key: ").strip()
        if not DEEPSEEK_API_KEY:
            print("ERROR: API key cannot be empty.", file=sys.stderr)
            return 1
    print()

    # Select grid
    grid = FOCUSSED_GRID
    if args.full_grid:
        grid = _build_full_grid()
    if args.configs:
        wanted = {k.strip() for k in args.configs.split(",")}
        grid = [c for c in grid if c["key"] in wanted]
        if not grid:
            print(f"ERROR: no configs matched --configs={args.configs!r}", file=sys.stderr)
            return 2

    if args.report_only:
        payloads = []
        for cfg in grid:
            p = OUTPUT_DIR / f"{args.file_prefix}{cfg['key']}.json"
            if p.exists():
                payloads.append(json.loads(p.read_text("utf-8")))
        generate_report(payloads)
        return 0

    bench_path = Path(args.benchmark_file)
    if not bench_path.exists():
        print(f"ERROR: {bench_path} not found", file=sys.stderr)
        return 2

    all_qas = load_benchmark(bench_path)

    def _group_qas(group: str) -> list[dict]:
        return [q for q in all_qas if str(q.get("id", "")).startswith(f"{group}-")]

    if args.group == "all":
        groups_to_run = ["G1", "G2", "G3"]
    elif args.group:
        groups_to_run = [args.group]
    else:
        groups_to_run = []

    if not groups_to_run:
        if args.question_ids:
            wanted_ids = {q.strip() for q in args.question_ids.split(",")}
            qas = [q for q in all_qas if str(q.get("id", "")) in wanted_ids]
        else:
            qas = all_qas[:args.max_questions]
        print(f"[{_now_utc()}] {len(qas)} questions selected from {bench_path}", flush=True)
        if not qas:
            print("ERROR: no questions selected", file=sys.stderr)
            return 2
        group_runs = [(qas, args.file_prefix)]
    else:
        group_runs = []
        for g in groups_to_run:
            gq = _group_qas(g)
            print(f"[{_now_utc()}] {g}: {len(gq)} questions", flush=True)
            if not gq:
                print(f"WARNING: no questions found for group {g}", file=sys.stderr)
            else:
                group_runs.append((gq, f"{args.file_prefix}{g}_"))

    print(f"[{_now_utc()}] Connecting to DB {DB_HOST}:{DB_PORT}/{DB_NAME} ...", flush=True)
    conn = _db_connect()
    search_space_id = _resolve_search_space(conn)
    print(f"[{_now_utc()}] search_space_id={search_space_id}", flush=True)
    _get_embed_model()

    all_payloads: list[dict] = []
    for qas, file_prefix in group_runs:
        grp_label = file_prefix.rstrip("_") or "ungrouped"
        print(f"\n{'#'*72}", flush=True)
        print(f"# GROUP: {grp_label} ({len(qas)} questions)", flush=True)
        print(f"{'#'*72}", flush=True)
        for cfg in grid:
            payload = _run_config(conn, qas, cfg, search_space_id, file_prefix=file_prefix)
            all_payloads.append(payload)

    conn.close()

    generate_report(all_payloads)

    print(f"\n{'='*72}", flush=True)
    print("GRID SEARCH SUMMARY  (DeepSeek V4 — thinking mode)", flush=True)
    print(f"{'='*72}", flush=True)
    W = 52
    print(f"{'Config':<{W}} {'OK':>4} {'Rate':>7} {'NumM':>7} {'F1':>8}", flush=True)
    print("-" * (W + 30), flush=True)
    for p in all_payloads:
        s = p["summary"]
        prefix = p.get("file_prefix", "")
        label = f"[{prefix.rstrip('_')}] {p['config']['label']}" if prefix else p["config"]["label"]
        print(
            f"{label:<{W}} "
            f"{s['overall_correct_count']:>2}/{s['run']:<2} "
            f"{s['overall_correct_rate']:>6.1%} "
            f"{s['number_match_rate']:>6.1%} "
            f"{s['mean_token_f1']:>8.4f}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
