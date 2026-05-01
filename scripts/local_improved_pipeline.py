#!/usr/bin/env python3
"""Local improved pipeline benchmark — no Docker, no DB, no docling.

Replaces the Docker/DB+RRF pipeline with an in-memory approach that mirrors
the direct benchmark scripts:

  1. Read local .docx via raw XML stripping (same as run_deepseek_direct_benchmark.py)
  2. Char-chunk the plain text (default: 2200 chars / 300 overlap)
  3. Per question: lexical top-k ranking (token overlap + numeric hint)
  4. Call LLM (DeepSeek API, LM Studio, or any OpenAI-compatible endpoint)
  5. Evaluate and write JSON+Markdown reports

Grid configs sweep chunk_chars / chunk_overlap / top_k to find the best setting.

Comparison vs Docker/DB pipeline
---------------------------------
  Factor          Direct (this script)          DB pipeline
  --------------- ----------------------------- ----------------------------------------
  Context source  Plain text from docx XML      DB chunks from docling Markdown parse
  Chunk selection Lexical (token overlap)       Semantic/RRF (concept match)
  Chunk count     ~106 at 2200/300              ~1000+ at 512 tokens
  Table handling  XML tag-strip keeps table     Docling → Markdown → RecursiveChunker
                  rows in same 2200-char window  splits each row into separate chunk
  DB required     No                            Yes (PostgreSQL + pgvector)
  Embedding model Not needed                    all-MiniLM-L6-v2 (sentence-transformers)

Usage
-----
  # Single best config, all 100 questions, DeepSeek:
  python3 scripts/local_improved_pipeline.py \\
      --provider deepseek \\
      --model deepseek-v4-flash \\
      --configs direct_top8_2200_300 \\
      --group all \\
      --file-prefix "deepseekflash_direct_"

  # Full grid sweep with LM Studio:
  python3 scripts/local_improved_pipeline.py \\
      --provider lmstudio \\
      --model gemma-4-31b-it \\
      --file-prefix "gemma31b_direct_grid_"

  # OpenAI-compatible custom endpoint:
  python3 scripts/local_improved_pipeline.py \\
      --provider openai \\
      --model gpt-5-nano \\
      --api-url https://api.openai.com/v1 \\
      --file-prefix "gpt5nano_direct_grid_"
"""

from __future__ import annotations

import argparse
import getpass
import html
import json
import os
import re
import sys
import socket
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from run_surfsense_benchmark import (   # noqa: E402
    _aggregate,
    _now_utc,
    evaluate_answer,
    load_benchmark,
    write_outputs,
)

# ---------------------------------------------------------------------------
# Grid definitions
# ---------------------------------------------------------------------------

GRID: list[dict[str, Any]] = [
    # ── Baseline (mirrors existing direct benchmarks) ─────────────────────
    dict(key="direct_top8_2200_300",
         label="top8 / chunk=2200 / overlap=300",
         top_k=8, chunk_chars=2200, chunk_overlap=300),

    # ── top_k sweep ───────────────────────────────────────────────────────
    dict(key="direct_top4_2200_300",
         label="top4 / chunk=2200 / overlap=300",
         top_k=4, chunk_chars=2200, chunk_overlap=300),

    dict(key="direct_top12_2200_300",
         label="top12 / chunk=2200 / overlap=300",
         top_k=12, chunk_chars=2200, chunk_overlap=300),

    dict(key="direct_top16_2200_300",
         label="top16 / chunk=2200 / overlap=300",
         top_k=16, chunk_chars=2200, chunk_overlap=300),

    # ── chunk_chars sweep ─────────────────────────────────────────────────
    dict(key="direct_top8_1000_150",
         label="top8 / chunk=1000 / overlap=150",
         top_k=8, chunk_chars=1000, chunk_overlap=150),

    dict(key="direct_top8_1500_200",
         label="top8 / chunk=1500 / overlap=200",
         top_k=8, chunk_chars=1500, chunk_overlap=200),

    dict(key="direct_top8_3000_400",
         label="top8 / chunk=3000 / overlap=400",
         top_k=8, chunk_chars=3000, chunk_overlap=400),

    dict(key="direct_top8_4000_500",
         label="top8 / chunk=4000 / overlap=500",
         top_k=8, chunk_chars=4000, chunk_overlap=500),

    dict(key="direct_top8_5000_600",
         label="top8 / chunk=5000 / overlap=600",
         top_k=8, chunk_chars=5000, chunk_overlap=600),

    # ── Larger chunk + smaller top_k ─────────────────────────────────────
    dict(key="direct_top5_3000_400",
         label="top5 / chunk=3000 / overlap=400",
         top_k=5, chunk_chars=3000, chunk_overlap=400),

    dict(key="direct_top5_4000_500",
         label="top5 / chunk=4000 / overlap=500",
         top_k=5, chunk_chars=4000, chunk_overlap=500),
]

DEFAULT_CONFIG_KEY = "direct_top8_2200_300"


# ---------------------------------------------------------------------------
# Document reading
# ---------------------------------------------------------------------------

def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _read_docx_text(path: Path) -> str:
    """Extract plain text from .docx by stripping XML tags.

    Tables come out as space-separated columns — header and data rows land
    in the same 2200-char window because no structural splitting is applied.
    """
    with zipfile.ZipFile(path, "r") as zf:
        with zf.open("word/document.xml") as fp:
            xml_data = fp.read().decode("utf-8", errors="replace")

    xml_data = xml_data.replace("</w:p>", "\n")
    xml_data = xml_data.replace("<w:tab/>", "\t")
    xml_data = re.sub(r"<[^>]+>", " ", xml_data)
    plain = html.unescape(xml_data)
    plain = re.sub(r"\n\s*\n+", "\n", plain)
    return _normalize_space(plain)


def read_docling_structured(json_path: Path) -> str:
    """Reconstruct full document text from msft_docx_structured.json.

    Paragraphs and table rows are interleaved in page/line order.
    Table rows are emitted as pipe-format markdown (already stored in row_text).
    This mirrors what SurfSense stores after docling ETL.
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # Build a unified list of (page, line, text) entries
    entries: list[tuple[int, int, str]] = []
    for p in data.get("paragraph_entries", []):
        text = str(p.get("text", "")).strip()
        if text:
            entries.append((p.get("page_number", 0), p.get("line_number", 0), text))
    for t in data.get("table_entries", []):
        for row in t.get("rows", []):
            row_text = str(row.get("row_text", "")).strip()
            if row_text:
                entries.append((row.get("page_number", 0), row.get("line_number", 0), row_text))

    entries.sort(key=lambda e: (e[0], e[1]))
    return "\n".join(e[2] for e in entries)


def read_docling_chunks(json_path: Path) -> list[str]:
    """Return docling's natural segments as individual chunks.

    Each paragraph entry becomes one chunk; each table's rows are grouped
    together into one chunk per table (preserving the table as a unit).
    This mirrors how SurfSense stores data in its DB after docling ETL:
    one DB row per paragraph / one DB row per table.
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # Collect paragraphs as individual (page, line, text) entries
    para_chunks: list[tuple[int, int, str]] = []
    for p in data.get("paragraph_entries", []):
        text = str(p.get("text", "")).strip()
        if text:
            para_chunks.append((p.get("page_number", 0), p.get("line_number", 0), text))

    # Collect each table as one combined chunk (all rows joined)
    table_chunks: list[tuple[int, int, str]] = []
    for t in data.get("table_entries", []):
        rows = t.get("rows", [])
        if not rows:
            continue
        row_texts = [str(r.get("row_text", "")).strip() for r in rows if str(r.get("row_text", "")).strip()]
        if row_texts:
            # Use the page/line of the first row to order the table
            first = rows[0]
            combined = "\n".join(row_texts)
            table_chunks.append((first.get("page_number", 0), first.get("line_number", 0), combined))

    all_chunks = sorted(para_chunks + table_chunks, key=lambda e: (e[0], e[1]))
    return [e[2] for e in all_chunks]


def read_db_chunks(
    db_host: str = "172.19.0.4",
    db_port: int = 5432,
    db_name: str = "surfsense",
    db_user: str = "surfsense",
    db_pass: str = "surfsense",
) -> list[str]:
    """Fetch all chunk content rows from the SurfSense PostgreSQL DB.

    This is what the old pipeline used as its data source after docling ETL.
    Chunks are returned in document + chunk-id order (same as old pipeline).
    No RRF, no embeddings — just the raw stored text fed into lexical ranking.
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:
        raise RuntimeError(
            "psycopg2 is required for --ablation db_source. "
            "Install it with: pip install psycopg2-binary"
        ) from exc

    conn = psycopg2.connect(
        host=db_host, port=db_port, dbname=db_name, user=db_user, password=db_pass,
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=15,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM searchspaces LIMIT 1")
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("No search spaces found in DB")
            space_id = int(row["id"])

            cur.execute(
                """
                SELECT c.content
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.search_space_id = %s
                ORDER BY c.document_id, c.id
                """,
                (space_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [str(r["content"]) for r in rows if r["content"]]


def read_document_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return _read_docx_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_chars: int, overlap: int) -> list[str]:
    if chunk_chars <= 0:
        return [text]
    overlap = max(0, min(overlap, chunk_chars - 1))
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + chunk_chars)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = end - overlap
    return chunks


_recursive_chunkers: dict[int, Any] = {}

def _get_recursive_chunker(chunk_size: int = 5000):
    """Lazy-load chonkie.RecursiveChunker with the given chunk_size (character tokenizer)."""
    if chunk_size not in _recursive_chunkers:
        from chonkie import RecursiveChunker
        _recursive_chunkers[chunk_size] = RecursiveChunker(tokenizer="character", chunk_size=chunk_size)
    return _recursive_chunkers[chunk_size]


def chunk_text_hybrid(text: str, chunk_chars: int, overlap: int) -> list[str]:
    """Markdown-aware chunker that mirrors the Docker document_chunker_patch.py.

    - Each contiguous block of pipe-table lines is kept as ONE chunk (whole
      table = header + all data rows together).
    - Prose sections are split with chonkie.RecursiveChunker(chunk_size=256)
      — exactly what SurfSense uses at ETL time after docling.

    This reproduces the server-side hybrid chunker without requiring the full
    SurfSense app stack.
    """
    _TABLE_LINE = re.compile(r"^\s*\|")

    blocks: list[tuple[str, str]] = []
    current_lines: list[str] = []
    in_table = False

    for line in text.splitlines(keepends=True):
        is_table_line = bool(_TABLE_LINE.match(line))
        if is_table_line != in_table:
            if current_lines:
                blocks.append(("table" if in_table else "prose", "".join(current_lines)))
            current_lines = []
            in_table = is_table_line
        current_lines.append(line)

    if current_lines:
        blocks.append(("table" if in_table else "prose", "".join(current_lines)))

    chunker = _get_recursive_chunker(chunk_size=chunk_chars)
    chunks: list[str] = []
    for kind, block in blocks:
        if kind == "table":
            stripped = block.strip()
            if stripped:
                chunks.append(stripped)
        else:
            prose_chunks = [c.text for c in chunker.chunk(block) if c.text.strip()]
            chunks.extend(prose_chunks)

    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Lexical retrieval
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9$%. ]+", " ", text)
    return [t for t in text.split() if t]


def chunk_text_paragraphs(text: str) -> list[str]:
    """Split on blank lines — mimics docling paragraph-level boundaries."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


_embed_model = None

def _rank_chunks_embedding(question: str, chunks: list[str], top_k: int) -> list[str]:
    """Rank chunks by cosine similarity using SentenceTransformer on CPU."""
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        print("  [ablation=ranking] Loading sentence-transformers/all-MiniLM-L6-v2 on CPU ...", flush=True)
        _embed_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    import numpy as np
    q_emb = _embed_model.encode([question], normalize_embeddings=True)
    c_embs = _embed_model.encode(chunks, normalize_embeddings=True)
    scores = (c_embs @ q_emb.T).flatten()
    top_indices = scores.argsort()[::-1][:max(1, top_k)]
    return [chunks[i] for i in top_indices]


_STOPWORDS = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "of", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "it", "its", "this", "that", "these", "those", "with", "by", "from",
    "as", "into", "through", "during", "about", "against", "between",
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "not", "no", "nor", "so", "yet", "both", "either", "neither",
    "only", "own", "same", "than", "too", "very", "just", "return",
    "per", "each", "any", "all", "most", "other", "also",
})


def rank_chunks(question: str, chunks: list[str], top_k: int) -> list[str]:
    q_tokens = set(_tokenize(question)) - _STOPWORDS
    scored: list[tuple[int, int, str]] = []
    for idx, chunk in enumerate(chunks):
        c_tokens = set(_tokenize(chunk)) - _STOPWORDS
        overlap = len(q_tokens & c_tokens)
        numeric_hint = 1 if re.search(
            r"\$|\b(?:million|billion|percent|%)\b|\d", chunk.lower()
        ) else 0
        score = overlap * 10 + numeric_hint
        scored.append((score, -idx, chunk))
    scored.sort(reverse=True)
    return [it[2] for it in scored[:max(1, top_k)]]


# ---------------------------------------------------------------------------
# LLM call (OpenAI-compatible chat/completions)
# ---------------------------------------------------------------------------

def call_llm(
    *,
    api_key: str,
    base_url: str,
    model: str,
    question: str,
    context_chunks: list[str],
    temperature: float | None,
    timeout: float,
    ablation: str = "none",
) -> str:
    context_blob = "\n\n".join(
        f"[chunk {i + 1}]\n{chunk}" for i, chunk in enumerate(context_chunks)
    )
    if ablation == "prompt":
        # Legacy free-text prompt (kept for reference, not an official ablation choice)
        system_prompt = (
            "You are a financial analyst assistant. "
            "Answer the question using only the provided context. "
            "Give a concise answer with the value and unit."
        )
        user_prompt = (
            f"Question: {question}\n\n"
            f"Context:\n{context_blob}\n\n"
            "Answer:"
        )
    else:
        system_prompt = (
            "You extract one financial value from provided context. "
            "Answer from context only. "
            "Return strict JSON: {\"answer\": \"<one value with unit>\"}. "
            "If unavailable, return {\"answer\": \"\"}. "
            "Do not include explanations or extra keys."
        )
        user_prompt = (
            f"Question:\n{question}\n\n"
            "Context:\n"
            f"{context_blob}\n\n"
            "Output JSON only."
        )

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    if temperature is not None:
        body["temperature"] = temperature

    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    payload = None
    _retry_delays = [5.0, 15.0]  # wait before 2nd and 3rd attempts
    for attempt in range(3):
        print(f"  -> POST {url} (timeout={timeout}s, attempt={attempt+1}) ...", flush=True)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            print(f"  -> response received", flush=True)
            break  # success
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            if attempt < 2:
                wait = _retry_delays[attempt]
                print(f"  -> request failed ({exc}), retrying in {wait:.0f}s ...", flush=True)
                time.sleep(wait)
            else:
                raise RuntimeError(f"LLM request error after 3 attempts: {exc}") from exc
    if payload is None:
        raise RuntimeError("LLM request failed: no payload received")

    try:
        raw_text = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raw_text = ""

    if not raw_text:
        return ""

    candidate = raw_text.strip()
    match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if match:
        candidate = match.group(0)
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
            return obj["answer"].strip()
    except json.JSONDecodeError:
        pass
    return candidate.strip()


# ---------------------------------------------------------------------------
# .env helper
# ---------------------------------------------------------------------------

def _read_env_file_var(env_path: Path, key: str) -> str:
    if not env_path.exists():
        return ""
    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    prefix = f"{key}="
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or not raw.startswith(prefix):
            continue
        value = raw[len(prefix):].strip()
        if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
            value = value[1:-1]
        return value.strip()
    return ""


# ---------------------------------------------------------------------------
# Single config run
# ---------------------------------------------------------------------------

def run_config(
    *,
    cfg: dict[str, Any],
    qas: list[dict[str, Any]],
    qas_all: list[dict[str, Any]],
    chunks: list[str],
    api_key: str,
    base_url: str,
    model: str,
    temperature: float | None,
    request_timeout: float,
    sleep_between: float,
    file_prefix: str,
    output_dir: Path,
    benchmark_path: Path,
    doc_path: Path,
    group_label: str,
    start_idx: int,
    ablation: str = "none",
) -> dict[str, Any]:
    key = cfg["key"]
    top_k = cfg["top_k"]
    chunk_chars = cfg["chunk_chars"]
    chunk_overlap = cfg["chunk_overlap"]
    total_qas = len(qas_all)

    config_chunks = chunks

    results: list[dict[str, Any]] = []
    failures = 0

    for idx, qa in enumerate(qas, start=1):
        global_idx = start_idx + idx
        qid = str(qa.get("id", f"Q{global_idx:03d}"))
        group = str(qa.get("group", "unknown"))
        question = str(qa.get("question", "")).strip()
        gold = str(qa.get("answer", "")).strip()

        print(f"[{_now_utc()}] ({global_idx}/{total_qas}) {qid} [{key}] ...", flush=True)

        pred = ""
        try:
            if ablation == "ranking":
                selected = _rank_chunks_embedding(question, config_chunks, top_k)
            elif ablation in ("coverage", "combined"):
                selected = rank_chunks(question, config_chunks, top_k * 2)
            else:
                selected = rank_chunks(question, config_chunks, top_k)
            pred = call_llm(
                api_key=api_key,
                base_url=base_url,
                model=model,
                question=question,
                context_chunks=selected,
                temperature=temperature,
                timeout=request_timeout,
                ablation=ablation,
            )
            if not pred:
                failures += 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            pred = ""
            print(f"  warning: request failed for {qid}: {exc}", file=sys.stderr)

        metrics = evaluate_answer(gold=gold, pred=pred)
        pred_preview = metrics.cleaned_prediction.replace("\n", " ").strip()
        if len(pred_preview) > 140:
            pred_preview = pred_preview[:137] + "..."

        print(
            "  eval: "
            f"strict={'Y' if metrics.strict_correct else 'N'} "
            f"lenient={'Y' if metrics.lenient_correct else 'N'} "
            f"num={'Y' if metrics.number_match else 'N'} "
            f"unit={'Y' if metrics.unit_match else 'N'} "
            f"clean={'Y' if metrics.answer_clean else 'N'} "
            f"intent={'Y' if metrics.semantic_intent_ok else 'N'} "
            f"num_f1={metrics.numeric_f1:.3f} "
            f"pred={pred_preview!r}",
            flush=True,
        )
        print(f"  expected: {gold}", flush=True)
        print(f"  predicted_exact: {pred}", flush=True)

        results.append({
            "id": qid,
            "group": group,
            "question": question,
            "gold_answer": gold,
            "predicted_answer": pred,
            "metrics": {
                "answer_clean": metrics.answer_clean,
                "semantic_intent_ok": metrics.semantic_intent_ok,
                "strict_exact": metrics.strict_exact,
                "normalized_exact": metrics.normalized_exact,
                "contains_gold": metrics.contains_gold,
                "number_match": metrics.number_match,
                "unit_match": metrics.unit_match,
                "numeric_precision": metrics.numeric_precision,
                "numeric_recall": metrics.numeric_recall,
                "numeric_f1": metrics.numeric_f1,
                "primary_value_match": metrics.primary_value_match,
                "token_f1": metrics.token_f1,
                "strict_correct": metrics.strict_correct,
                "lenient_correct": metrics.lenient_correct,
                "overall_correct": metrics.overall_correct,
            },
        })

        if sleep_between > 0:
            time.sleep(sleep_between)

    summary = _aggregate(results)
    summary["questions_total"] = total_qas
    summary["questions_run"] = len(results)
    summary["request_failures"] = failures
    summary["context_overflow_failures"] = 0

    by_group: dict[str, dict[str, Any]] = {}
    for gname in sorted({str(it.get("group", "unknown")) for it in results}):
        items = [it for it in results if it.get("group") == gname]
        by_group[gname] = _aggregate(items)

    run_name = f"{file_prefix}{group_label}_{key}"
    report = {
        "generated_at_utc": _now_utc(),
        "config": key,
        "config_label": cfg["label"],
        "file_prefix": file_prefix,
        "llm_model": model,
        "llm_endpoint": base_url,
        "retrieval_mode": "local_direct_lexical",
        "top_k": top_k,
        "chunk_chars": chunk_chars,
        "chunk_overlap": chunk_overlap,
        "benchmark_file": str(benchmark_path),
        "doc_file": str(doc_path),
        "summary": summary,
        "by_group": by_group,
        "results": results,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{run_name}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown summary
    total = summary.get("run", summary.get("questions_run", summary.get("total", 0)))
    correct = summary.get("overall_correct_count", summary.get("overall_correct", 0))
    num_match = summary.get("number_match_count", summary.get("number_match", 0))
    pct = (correct / total * 100) if total else 0.0
    nm_pct = (num_match / total * 100) if total else 0.0

    md_lines: list[str] = [
        f"# Benchmark Run: {run_name}",
        "",
        f"**Model:** {model}  ",
        f"**Endpoint:** {base_url}  ",
        f"**Document:** {doc_path}  ",
        f"**Retrieval:** lexical top-{top_k}, chunk={chunk_chars}/{chunk_overlap}  ",
        f"**Generated:** {_now_utc()}  ",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Questions | {total} |",
        f"| Overall Correct | {correct}/{total} ({pct:.1f}%) |",
        f"| Number Match | {num_match}/{total} ({nm_pct:.1f}%) |",
        f"| Mean Token F1 | {summary.get('mean_token_f1', 0.0):.4f} |",
        f"| Request Failures | {failures} |",
        "",
    ]
    for gname, gs in sorted(by_group.items()):
        gt = gs.get("total", 0)
        gc = gs.get("overall_correct_count", gs.get("overall_correct", 0))
        gnm = gs.get("number_match_count", gs.get("number_match", 0))
        md_lines += [
            f"### Group {gname}",
            "",
            f"| Metric | Value |",
            "|--------|-------|",
            f"| Correct | {gc}/{gt} ({(gc/gt*100) if gt else 0:.1f}%) |",
            f"| Num Match | {gnm}/{gt} ({(gnm/gt*100) if gt else 0:.1f}%) |",
            "",
        ]
    md_lines += [
        "## Per-Question Results",
        "",
        "| # | ID | Group | Correct | NumMatch | Pred | Gold |",
        "|---|-----|-------|---------|----------|------|------|",
    ]
    for i, item in enumerate(results, start=1):
        m = item.get("metrics", {})
        pred_cell = str(item.get("predicted_answer", "")).replace("|", "\\|")[:80]
        gold_cell = str(item.get("gold_answer", "")).replace("|", "\\|")[:60]
        md_lines.append(
            f"| {i} | {item.get('id','')} | {item.get('group','')} "
            f"| {'Y' if m.get('overall_correct') else 'N'} "
            f"| {'Y' if m.get('number_match') else 'N'} "
            f"| {pred_cell} | {gold_cell} |"
        )

    md_path = output_dir / f"{run_name}.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(
        f"\n[{_now_utc()}] [{key}] {group_label}: "
        f"{correct}/{total} correct ({pct:.1f}%) | "
        f"num_match={num_match}/{total} ({nm_pct:.1f}%)  → {json_path}",
        flush=True,
    )

    return report


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local improved pipeline benchmark — no DB required"
    )
    # Provider / model
    parser.add_argument(
        "--provider",
        choices=["deepseek", "lmstudio", "openai"],
        default="deepseek",
        help="API provider: deepseek | lmstudio | openai (default: deepseek)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name. Default: deepseek-v4-flash / gemma-4-31b-it / gpt-5-nano",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="Override API base URL (default per provider)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key value directly (overrides env var and .env file)",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="Env var name for API key (optional; auto-detected per provider)",
    )
    # Files
    parser.add_argument(
        "--benchmark-file",
        default="msft_fy26q1_qa_benchmark_100_sanitized.json",
        help="Path to benchmark JSON",
    )
    parser.add_argument(
        "--doc-file",
        default="MSFT_FY26Q1_10Q.docx",
        help="Local document (.docx/.md/.txt)",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results_MSFT_FY26Q1_qa",
        help="Directory for JSON/MD reports",
    )
    parser.add_argument(
        "--file-prefix",
        default="direct_",
        help="Output filename prefix",
    )
    # Questions
    parser.add_argument(
        "--group",
        default="all",
        help="Question group to run: all | G1 | G2 | G3 (default: all)",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=0,
        help="If >0, cap at first N questions",
    )
    parser.add_argument(
        "--start-question",
        type=int,
        default=1,
        help="1-based question index to start from",
    )
    # Configs
    parser.add_argument(
        "--configs",
        default=None,
        help=(
            "Comma-separated config keys to run (default: all). "
            f"Available: {', '.join(c['key'] for c in GRID)}"
        ),
    )
    # LLM params
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="LLM temperature (default: not sent)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=180.0,
        help="HTTP request timeout in seconds (per attempt; up to 3 attempts)",
    )
    parser.add_argument(
        "--sleep-between",
        type=float,
        default=0.0,
        help="Seconds to sleep between questions",
    )
    # Ablation
    parser.add_argument(
        "--ablation",
        default="none",
        choices=["none", "context_source", "ranking", "coverage", "table_markdown", "combined", "db_source", "table_hybrid"],
        help=(
            "Swap ONE component to old-pipeline behavior: "
            "context_source=use docling MD file + paragraph-level splitting, "
            "ranking=embedding cosine similarity (SentenceTransformer CPU) instead of lexical overlap, "
            "coverage=top_k x2 (e.g. 16 instead of 8) to match old-pipeline coverage fraction, "
            "table_markdown=use docling MD file (pipe tables intact) but keep char-window chunking, "
            "combined=docling natural segments (context_source) + top_k x2 (coverage), "
            "db_source=chunks pre-stored in PostgreSQL by SurfSense docling ETL (requires running DB), "
            "table_hybrid=docling MD text with document_chunker_patch logic: whole tables + RecursiveChunker(256) for prose"
        ),
    )
    # DB connection options (used only with --ablation db_source)
    parser.add_argument("--db-host", default="172.19.0.4", help="PostgreSQL host (default: 172.19.0.4)")
    parser.add_argument("--db-port", type=int, default=5432, help="PostgreSQL port (default: 5432)")
    parser.add_argument("--db-name", default="surfsense", help="PostgreSQL database name (default: surfsense)")
    parser.add_argument("--db-user", default="surfsense", help="PostgreSQL user (default: surfsense)")
    parser.add_argument("--db-pass", default="surfsense", help="PostgreSQL password (default: surfsense)")
    parser.add_argument(
        "--md-file",
        default="MSFT_FY26Q1_10Q_content.md",
        help="Docling markdown file used when --ablation context_source or table_markdown",
    )
    parser.add_argument(
        "--structured-json",
        default="msft_docx_structured.json",
        help="Docling structured JSON (paragraphs + tables) used for context_source / table_markdown ablation",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_PROVIDER_DEFAULTS = {
    "deepseek": {
        "url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "key_env": "DEEPSEEK_API_KEY",
        "key_prompt": "Enter your DeepSeek API key: ",
    },
    "lmstudio": {
        "url": "http://localhost:1234/v1",
        "model": "gemma-4-31b-it",
        "key_env": None,
        "key_prompt": None,
    },
    "openai": {
        "url": "https://api.openai.com/v1",
        "model": "gpt-5-nano",
        "key_env": "OPENAI_API_KEY",
        "key_prompt": "Enter your OpenAI API key: ",
    },
}


def main() -> int:
    args = build_arg_parser().parse_args()

    prov = _PROVIDER_DEFAULTS[args.provider]
    base_url = args.api_url or prov["url"]
    model = args.model or prov["model"]

    # Resolve API key
    api_key = ""
    if args.api_key:
        api_key = args.api_key.strip()
    else:
        key_env = args.api_key_env or prov["key_env"]
        if key_env:
            api_key = os.environ.get(key_env, "").strip()
            if not api_key:
                api_key = _read_env_file_var(Path(".env"), key_env)
            if not api_key and prov["key_prompt"]:
                api_key = input(prov["key_prompt"]).strip()
            if not api_key:
                print(f"ERROR: missing API key (env var {key_env})", file=sys.stderr)
                return 2

    # Files
    benchmark_path = Path(args.benchmark_file)
    doc_path = Path(args.doc_file)
    output_dir = Path(args.output_dir)

    if not benchmark_path.exists():
        print(f"ERROR: benchmark file not found: {benchmark_path}", file=sys.stderr)
        return 2
    if not doc_path.exists():
        print(f"ERROR: doc file not found: {doc_path}", file=sys.stderr)
        return 2

    # Configs to run
    if args.configs:
        wanted = {k.strip() for k in args.configs.split(",")}
        configs_to_run = [c for c in GRID if c["key"] in wanted]
        missing = wanted - {c["key"] for c in configs_to_run}
        if missing:
            print(f"ERROR: unknown config keys: {', '.join(sorted(missing))}", file=sys.stderr)
            print(f"Available: {', '.join(c['key'] for c in GRID)}", file=sys.stderr)
            return 2
    else:
        configs_to_run = GRID

    # Load benchmark
    print(f"[{_now_utc()}] Loading benchmark: {benchmark_path}", flush=True)
    qas_all = load_benchmark(benchmark_path)
    total_qas = len(qas_all)

    if args.start_question < 1:
        print("ERROR: --start-question must be >= 1", file=sys.stderr)
        return 2
    start_idx = args.start_question - 1
    if start_idx >= total_qas:
        print(f"ERROR: --start-question {args.start_question} exceeds total {total_qas}", file=sys.stderr)
        return 2

    qas_filtered = qas_all[start_idx:]
    if args.group.lower() != "all":
        qas_filtered = [q for q in qas_filtered if str(q.get("group", "")) == args.group]
        group_label = args.group
    else:
        group_label = "all"
    if args.max_questions and args.max_questions > 0:
        qas_filtered = qas_filtered[:args.max_questions]

    print(f"[{_now_utc()}] Questions to run: {len(qas_filtered)} (group={group_label})", flush=True)
    print(f"[{_now_utc()}] Model: {model} @ {base_url}", flush=True)
    print(f"[{_now_utc()}] Configs: {[c['key'] for c in configs_to_run]}", flush=True)

    # Run each config
    all_reports: list[dict[str, Any]] = []
    for cfg in configs_to_run:
        print(f"\n{'='*70}", flush=True)
        print(f"[{_now_utc()}] Config: {cfg['key']} — {cfg['label']}", flush=True)
        print(f"{'='*70}", flush=True)

        # Build chunks for this config's chunk params
        if args.ablation in ("context_source", "combined"):
            structured_path = Path(args.structured_json)
            if not structured_path.exists():
                print(f"ERROR: --structured-json not found: {structured_path}", file=sys.stderr)
                return 2
            print(f"[{_now_utc()}] Reading document (ablation={args.ablation}): {structured_path}", flush=True)
        elif args.ablation in ("table_markdown", "table_hybrid"):
            structured_path = Path(args.structured_json)
            if not structured_path.exists():
                print(f"ERROR: --structured-json not found: {structured_path}", file=sys.stderr)
                return 2
            print(f"[{_now_utc()}] Reading document (ablation={args.ablation}): {structured_path}", flush=True)
            full_text = read_docling_structured(structured_path)
        elif args.ablation == "db_source":
            print(
                f"[{_now_utc()}] Connecting to PostgreSQL "
                f"{args.db_host}:{args.db_port}/{args.db_name} (ablation=db_source) ...",
                flush=True,
            )
        else:
            print(f"[{_now_utc()}] Reading document: {doc_path}", flush=True)
            full_text = read_document_text(doc_path)

        if args.ablation in ("context_source", "combined"):
            # Use docling's natural segmentation: one chunk per paragraph/table
            # as stored in the SurfSense DB after docling ETL.
            chunks = read_docling_chunks(structured_path)
            print(
                f"[{_now_utc()}] Chunks: {len(chunks)} "
                f"(ablation={args.ablation}: docling natural segments — paragraphs + tables)",
                flush=True,
            )
        elif args.ablation == "db_source":
            # Fetch raw chunk content from PostgreSQL as stored by SurfSense docling ETL.
            # All other components (lexical ranking, top_k) remain unchanged.
            chunks = read_db_chunks(
                db_host=args.db_host,
                db_port=args.db_port,
                db_name=args.db_name,
                db_user=args.db_user,
                db_pass=args.db_pass,
            )
            print(
                f"[{_now_utc()}] Chunks: {len(chunks)} "
                f"(ablation=db_source: raw DB rows from SurfSense PostgreSQL ETL)",
                flush=True,
            )
        elif args.ablation == "table_hybrid":
            # Whole tables as single chunks + RecursiveChunker(256 tokens) for prose.
            # Mirrors document_chunker_patch.py (the server-side fix to the standard ETL).
            print(
                f"[{_now_utc()}] Loading chonkie.RecursiveChunker(256) for prose sections ...",
                flush=True,
            )
            chunks = chunk_text_hybrid(full_text, cfg["chunk_chars"], cfg["chunk_overlap"])
            print(
                f"[{_now_utc()}] Chunks: {len(chunks)} "
                f"(ablation=table_hybrid: whole tables + RecursiveChunker(256) prose)",
                flush=True,
            )
        else:
            # Baseline char-window chunking (also used for table_markdown, ranking, coverage)
            chunks = chunk_text(full_text, cfg["chunk_chars"], cfg["chunk_overlap"])
            print(
                f"[{_now_utc()}] Chunks: {len(chunks)} "
                f"(chars={cfg['chunk_chars']}, overlap={cfg['chunk_overlap']})",
                flush=True,
            )

        report = run_config(
            cfg=cfg,
            qas=qas_filtered,
            qas_all=qas_all,
            chunks=chunks,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=args.temperature,
            request_timeout=args.request_timeout,
            sleep_between=args.sleep_between,
            file_prefix=args.file_prefix,
            output_dir=output_dir,
            benchmark_path=benchmark_path,
            doc_path=doc_path,
            group_label=group_label,
            start_idx=start_idx,
            ablation=args.ablation,
        )
        all_reports.append(report)

    # Final leaderboard
    print(f"\n{'='*70}", flush=True)
    print(f"[{_now_utc()}] LEADERBOARD ({group_label}, {model})", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"{'Config':<45} {'Correct':>10} {'NumMatch':>10} {'Failures':>10}", flush=True)
    print("-" * 80, flush=True)
    for rep in sorted(
        all_reports,
        key=lambda r: r["summary"].get("overall_correct_count", r["summary"].get("overall_correct", 0)),
        reverse=True,
    ):
        s = rep["summary"]
        total = s.get("run", s.get("questions_run", s.get("total", 0)))
        correct = s.get("overall_correct_count", s.get("overall_correct", 0))
        nm = s.get("number_match_count", s.get("number_match", 0))
        fail = s.get("request_failures", 0)
        pct = (correct / total * 100) if total else 0.0
        nm_pct = (nm / total * 100) if total else 0.0
        print(
            f"{rep['config']:<45} {correct}/{total} ({pct:.0f}%)  "
            f"{nm}/{total} ({nm_pct:.0f}%)  fail={fail}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
