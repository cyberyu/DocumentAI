#!/usr/bin/env python3
"""Mode B (direct pgvector) controlled chunk-size experiment: 256 vs 1024.

Mirrors run_chunk_size_experiment.py (Mode A — SurfSense agentic API) but
instead of calling the SurfSense HTTP API for retrieval+answering, this
script bypasses the API entirely:

  Retrieval  : direct psycopg2 → pgvector  (same DB the backend uses)
  LLM        : DeepSeek V4 Flash API  (thinking mode, reasoning_effort=high)
  Parallelism: ThreadPoolExecutor  (--workers, default 10)

The docker/ingest phase is identical to Mode A: we update docker-compose.yml,
force-recreate backend+celery_worker so the new CHUNKER_CHUNK_SIZE takes
effect, then delete the old document and re-ingest it.  AFTER ingestion we
skip the SurfSense API and query pgvector directly for every question.

Fixed retrieval settings (identical to best Mode B1 config from prior grid search):
  RRF k=60  top_k=10  max_chunks_per_doc=50  matched_markers=True
  query_rewrite=True  date_filter=none  embed=all-MiniLM-L6-v2

Output files:
  benchmark_results_MSFT_FY26Q1_qa/deepseekflash_B1_{chunk_size}chunk_controlled_v1.json
  benchmark_results_MSFT_FY26Q1_qa/deepseekflash_B1_{chunk_size}chunk_controlled_v1.md

Usage:
  # Full run — both sizes (docker + ingest + benchmark):
  python3 scripts/run_mode_b_chunk_size_experiment.py --workers 10

  # Single size only:
  python3 scripts/run_mode_b_chunk_size_experiment.py --chunk-sizes 256 --workers 10

  # Skip docker/ingest (DB already has correct chunks, just run benchmark):
  python3 scripts/run_mode_b_chunk_size_experiment.py --chunk-sizes 256 --skip-docker --skip-ingest --workers 10

  # Dry-run:
  python3 scripts/run_mode_b_chunk_size_experiment.py --dry-run
"""

from __future__ import annotations

import argparse
import concurrent.futures
import getpass
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from sentence_transformers import SentenceTransformer

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

# ---------------------------------------------------------------------------
# Constants — infrastructure
# ---------------------------------------------------------------------------

SURFSENSE_BASE_URL = "http://localhost:8929"
USERNAME = "shi.yu@broadridge.com"
PASSWORD = "Lexar1357!!"
SEARCH_SPACE_ID = 1
DOCUMENT_TITLE_CONTAINS = "MSFT_FY26Q1_10Q"
DOCX_PATH = Path("MSFT_FY26Q1_10Q.docx")
DOCKER_COMPOSE_FILE = Path("docker-compose.yml")
BACKEND_CONTAINER = "surfsense-backend-1"
CELERY_CONTAINER = "surfsense-celery_worker-1"
BACKEND_HEALTH_POLL_SECONDS = 10
BACKEND_HEALTH_MAX_WAIT = 180
INGEST_POLL_SECONDS = 10
INGEST_MAX_WAIT = 600

# ---------------------------------------------------------------------------
# Constants — benchmark
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("benchmark_results_MSFT_FY26Q1_qa")
BENCH_FILE = Path("msft_fy26q1_qa_benchmark_100_sanitized.json")

DB_HOST = "172.19.0.4"
DB_PORT = 5432
DB_NAME = "surfsense"
DB_USER = "surfsense"
DB_PASS = "surfsense"

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_TIMEOUT = 300.0
MAX_TOKENS = 8192
TRUNC_TOKENS = 28000

_MAX_KEYWORD_TERMS = 12
_KEYWORD_STOPWORDS = {
    "in", "the", "a", "an", "of", "for", "to", "from", "and", "or",
    "by", "on", "with", "between", "what", "was", "is", "are", "return",
    "only", "numeric", "sign", "unit", "docx",
}

# Best-known Mode B1 config from prior grid search
BEST_CONFIG = dict(
    key="nodatefilter_k60_top10_chunks50_markers",
    label="No-date / k=60 / top10 / chunks50 / markers ON",
    query_rewrite=True,
    date_filter="none",
    rrf_k=60,
    top_k=10,
    max_chunks_per_doc=50,
    matched_markers=True,
)

# ---------------------------------------------------------------------------
# Globals (thread-safe)
# ---------------------------------------------------------------------------

_DEEPSEEK_API_KEY: str = ""
_embed_model: SentenceTransformer | None = None
_embed_lock: threading.Lock = threading.Lock()


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    with _embed_lock:
        if _embed_model is None:
            print(f"[{_now_utc()}] Loading embedding model {EMBED_MODEL} ...", flush=True)
            _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def _embed(text: str) -> list[float]:
    return _get_embed_model().encode(text, normalize_embeddings=True).tolist()


# ---------------------------------------------------------------------------
# SurfSense HTTP helpers (docker/ingest phase only)
# ---------------------------------------------------------------------------


def _login(base_url: str, username: str, password: str) -> str:
    req = urllib.request.Request(
        base_url + "/auth/jwt/login",
        data=urllib.parse.urlencode({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    for attempt in range(8):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=20).read())["access_token"]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 7:
                wait = 30 + attempt * 10
                print(f"  429 rate-limited on login, waiting {wait}s ...", flush=True)
                time.sleep(wait)
                continue
            raise


def _api(method: str, path: str, token: str, *, json_body=None, timeout: int = 60) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body).encode()
    req = urllib.request.Request(
        SURFSENSE_BASE_URL + path, data=data, headers=headers, method=method,
    )
    for attempt in range(8):
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 7:
                wait = 30 + attempt * 10
                print(f"  429 on {method} {path}, waiting {wait}s ...", flush=True)
                time.sleep(wait)
                continue
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} on {method} {path}: {body}") from e


def _upload_file(token: str, file_path: Path, search_space_id: int) -> list[dict]:
    boundary = b"----SurfSenseBoundaryModeB"
    body_parts: list[bytes] = []
    body_parts.append(
        b"--" + boundary
        + b"\r\nContent-Disposition: form-data; name=\"search_space_id\"\r\n\r\n"
        + str(search_space_id).encode()
    )
    body_parts.append(
        b"--" + boundary
        + b"\r\nContent-Disposition: form-data; name=\"should_summarize\"\r\n\r\nfalse"
    )
    body_parts.append(
        b"--" + boundary
        + b"\r\nContent-Disposition: form-data; name=\"use_vision_llm\"\r\n\r\nfalse"
    )
    body_parts.append(
        b"--" + boundary
        + b"\r\nContent-Disposition: form-data; name=\"processing_mode\"\r\n\r\nbasic"
    )
    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_data = file_path.read_bytes()
    body_parts.append(
        b"--" + boundary
        + f"\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{filename}\"\r\n"
          f"Content-Type: {content_type}\r\n\r\n".encode()
        + file_data
    )
    body = b"\r\n".join(body_parts) + b"\r\n--" + boundary + b"--\r\n"
    req = urllib.request.Request(
        SURFSENSE_BASE_URL + "/api/v1/documents/fileupload",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
        },
        method="POST",
    )
    for attempt in range(8):
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
            return resp if isinstance(resp, list) else [resp]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 7:
                time.sleep(30 + attempt * 10)
                continue
            raise RuntimeError(f"Upload failed ({e.code}): {e.read().decode()}") from e


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def _update_compose_chunk_size(compose_file: Path, new_size: int, dry_run: bool) -> None:
    text = compose_file.read_text(encoding="utf-8")
    pattern = r'(CHUNKER_CHUNK_SIZE:\s*")[^"]*(")'
    new_text, count = re.subn(pattern, rf'\g<1>{new_size}\g<2>', text)
    if count == 0:
        raise RuntimeError("Could not find CHUNKER_CHUNK_SIZE in docker-compose.yml")
    print(f"  Updating docker-compose.yml: CHUNKER_CHUNK_SIZE → {new_size} ({count} occurrence(s))", flush=True)
    if not dry_run:
        compose_file.write_text(new_text, encoding="utf-8")


def _docker_recreate(containers: list[str], dry_run: bool) -> None:
    services = [c.replace("surfsense-", "").rstrip("-1") for c in containers]
    cmd = ["docker", "compose", "up", "-d", "--force-recreate"] + services
    print(f"  Running: {' '.join(cmd)}", flush=True)
    if not dry_run:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"docker compose failed:\n{result.stderr}")


def _wait_for_backend(dry_run: bool) -> None:
    if dry_run:
        print("  [dry-run] skip wait_for_backend", flush=True)
        return
    deadline = time.time() + BACKEND_HEALTH_MAX_WAIT
    print(f"  Waiting for backend health (max {BACKEND_HEALTH_MAX_WAIT}s) ...", flush=True)
    while time.time() < deadline:
        try:
            code = urllib.request.urlopen(SURFSENSE_BASE_URL + "/health", timeout=5).status
            if code == 200:
                print("  Backend is healthy.", flush=True)
                return
        except Exception:
            pass
        time.sleep(BACKEND_HEALTH_POLL_SECONDS)
    raise RuntimeError(f"Backend did not become healthy within {BACKEND_HEALTH_MAX_WAIT}s")


def _delete_matching_documents(token: str, dry_run: bool) -> list[int]:
    if dry_run:
        print(f"  [dry-run] skip delete documents matching '{DOCUMENT_TITLE_CONTAINS}'", flush=True)
        return []
    resp = _api("GET", f"/api/v1/documents?search_space_id={SEARCH_SPACE_ID}&page_size=-1",
                token, timeout=30)
    docs = resp.get("items", [])
    needle = DOCUMENT_TITLE_CONTAINS.lower()
    matching = [d for d in docs if needle in str(d.get("title", "")).lower()]
    ids = [d["id"] for d in matching if "id" in d]
    if not ids:
        print(f"  No existing documents matched '{DOCUMENT_TITLE_CONTAINS}'.", flush=True)
        return []
    for doc_id in ids:
        title = next((d.get("title", "?") for d in matching if d.get("id") == doc_id), "?")
        print(f"  Deleting document id={doc_id} title='{title}' ...", flush=True)
        _api("DELETE", f"/api/v1/documents/{doc_id}", token)
    return ids


def _upload_and_wait(token: str, file_path: Path, dry_run: bool) -> list[int]:
    if dry_run:
        print(f"  [dry-run] skip upload of {file_path}", flush=True)
        return []
    print(f"  Uploading {file_path} ...", flush=True)
    created = _upload_file(token, file_path, SEARCH_SPACE_ID)
    # The API may return either  [{"id": 19, ...}]   or
    # [{"document_ids": [19], ...}]  depending on the backend version.
    doc_ids: list[int] = []
    for d in created:
        if isinstance(d.get("id"), int):
            doc_ids.append(d["id"])
        elif isinstance(d.get("document_ids"), list):
            doc_ids.extend(x for x in d["document_ids"] if isinstance(x, int))
    print(f"  Upload response: {created!r}  (IDs: {doc_ids})", flush=True)

    deadline = time.time() + INGEST_MAX_WAIT

    # If the upload returned no IDs (async queue), poll the document list until the
    # new document with the matching title appears.
    if not doc_ids:
        print(f"  Upload returned no doc IDs — polling document list for '{DOCUMENT_TITLE_CONTAINS}' ...", flush=True)
        while time.time() < deadline:
            time.sleep(INGEST_POLL_SECONDS)
            try:
                resp = _api("GET", f"/api/v1/documents?search_space_id={SEARCH_SPACE_ID}&page_size=-1",
                            token, timeout=30)
                docs = resp.get("items", [])
                needle = DOCUMENT_TITLE_CONTAINS.lower()
                matches = [d for d in docs if needle in str(d.get("title", "")).lower()]
                if matches:
                    doc_ids = [d["id"] for d in matches if isinstance(d.get("id"), int)]
                    print(f"  Found document(s) in list: IDs={doc_ids}", flush=True)
                    break
            except Exception as e:
                print(f"  Warning polling document list: {e}", flush=True)
        if not doc_ids:
            raise RuntimeError(f"Timed out waiting for document to appear in list ({DOCUMENT_TITLE_CONTAINS})")

    # Poll DB chunk count until chunks appear (more reliable than API status field)
    print(f"  Polling DB chunk count for doc IDs {doc_ids} ...", flush=True)
    while time.time() < deadline:
        try:
            db_conn = _db_connect(DB_HOST)
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM chunks c WHERE c.document_id = ANY(%s)",
                    (doc_ids,),
                )
                n_chunks = cur.fetchone()["n"]
            db_conn.close()
            print(f"    chunks in DB: {n_chunks}", flush=True)
            if n_chunks > 0:
                print(f"  Indexing complete: {n_chunks} chunks for doc IDs {doc_ids}", flush=True)
                break
        except Exception as e:
            print(f"  Warning polling DB chunks: {e}", flush=True)
        time.sleep(INGEST_POLL_SECONDS)
    else:
        raise RuntimeError(f"Timed out waiting for chunks to appear in DB for doc IDs {doc_ids}")

    # Confirm chunk count via direct DB query
    try:
        conn = _db_connect(DB_HOST)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM chunks c JOIN documents d ON c.document_id=d.id "
                "WHERE d.search_space_id=%s",
                (SEARCH_SPACE_ID,),
            )
            n = cur.fetchone()["n"]
        conn.close()
        print(f"  DB chunk count after ingest: {n}", flush=True)
    except Exception as e:
        print(f"  Warning: could not count chunks in DB: {e}", flush=True)

    return doc_ids


# ---------------------------------------------------------------------------
# pgvector helpers
# ---------------------------------------------------------------------------

def _db_connect(db_host: str) -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=db_host, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _resolve_search_space(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM searchspaces LIMIT 1")
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("No search spaces found in database")
    return int(row["id"])


def _build_keyword_tsquery(query_text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_.-]+", query_text.lower())
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in tokens:
        token = raw.strip("._-")
        if not token or token in seen:
            continue
        if "." in raw and any(ch.isalpha() for ch in raw):
            continue
        if len(token) < 2 or token in _KEYWORD_STOPWORDS:
            continue
        seen.add(token)
        normalized.append(token)
        if len(normalized) >= _MAX_KEYWORD_TERMS:
            break
    return " | ".join(normalized)


def rrf_hybrid_search(
    conn,
    query_text: str,
    search_space_id: int,
    *,
    rrf_k: int = 60,
    top_k: int = 10,
    max_chunks_per_doc: int | None = 50,
) -> list[dict]:
    query_embedding = _embed(query_text)
    keyword_tsquery = _build_keyword_tsquery(query_text)
    if not keyword_tsquery:
        return []
    n_results = top_k * 5

    rrf_sql = f"""
WITH semantic_search AS (
    SELECT c.id,
           RANK() OVER (ORDER BY c.embedding <=> %s::vector) AS rank
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE d.search_space_id = %s
    ORDER BY c.embedding <=> %s::vector
    LIMIT %s
),
keyword_search AS (
    SELECT c.id,
           RANK() OVER (ORDER BY ts_rank_cd(to_tsvector('english', c.content),
                                            to_tsquery('english', %s)) DESC) AS rank
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE d.search_space_id = %s
      AND ts_rank_cd(to_tsvector('english', c.content),
                     to_tsquery('english', %s)) > 0
    ORDER BY ts_rank_cd(to_tsvector('english', c.content),
                        to_tsquery('english', %s)) DESC
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
        [vec_str, search_space_id, vec_str, n_results]
        + [keyword_tsquery, search_space_id, keyword_tsquery, keyword_tsquery, n_results]
        + [rrf_k, rrf_k, top_k]
    )

    with conn.cursor() as cur:
        cur.execute(rrf_sql, params)
        rrf_rows = cur.fetchall()

    if not rrf_rows:
        return []

    doc_scores:  dict[int, float] = {}
    doc_order:   list[int] = []
    matched_ids: dict[int, set[int]] = {}
    doc_meta:    dict[int, dict] = {}

    for row in rrf_rows:
        doc_id = int(row["document_id"])
        cid    = int(row["chunk_id"])
        score  = float(row["score"])
        if doc_id not in doc_scores:
            doc_scores[doc_id] = score
            doc_order.append(doc_id)
            matched_ids[doc_id] = set()
            doc_meta[doc_id] = {
                "id": doc_id, "title": row["title"],
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
# Context assembly
# ---------------------------------------------------------------------------

def _build_context_xml(docs: list[dict], matched_markers: bool) -> str:
    parts: list[str] = []
    for doc in docs:
        matched  = set(doc.get("matched_chunk_ids", [])) if matched_markers else set()
        doc_meta = doc.get("document", {})
        doc_id   = doc_meta.get("id", doc.get("document_id", "unknown"))
        title    = doc_meta.get("title", "Untitled")
        metadata = doc_meta.get("metadata") or {}

        lines: list[str] = [
            "<document>",
            "<document_metadata>",
            f"  <document_id>{doc_id}</document_id>",
            f"  <document_type>FILE</document_type>",
            f"  <title><![CDATA[{title}]]></title>",
            f"  <metadata_json><![CDATA[{json.dumps(metadata, ensure_ascii=False)}]]></metadata_json>",
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


def _truncate_to_token_budget(context: str, budget_tokens: int = TRUNC_TOKENS) -> str:
    max_chars = budget_tokens * 4
    if len(context) > max_chars:
        return context[:max_chars] + "\n... [TRUNCATED]"
    return context


# ---------------------------------------------------------------------------
# LLM call — DeepSeek V4 API with thinking mode (thread-safe, read global key)
# ---------------------------------------------------------------------------

def _call_llm(question: str, context: str) -> str:
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
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {_DEEPSEEK_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=DEEPSEEK_TIMEOUT) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    choices = result.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "").strip()


# ---------------------------------------------------------------------------
# Per-question benchmark (called from worker threads)
# ---------------------------------------------------------------------------

# Thread-local DB connections (each worker gets its own connection)
_tl = threading.local()


def _get_thread_conn(db_host: str) -> psycopg2.extensions.connection:
    if not hasattr(_tl, "conn") or _tl.conn.closed:
        _tl.conn = _db_connect(db_host)
        _tl.search_space_id = _resolve_search_space(_tl.conn)
    return _tl.conn


def _run_question_b1(qa: dict, cfg: dict, db_host: str) -> dict:
    qid   = str(qa.get("id", ""))
    group = str(qa.get("group", "unknown"))
    raw_q = str(qa.get("question", "")).strip()
    gold  = str(qa.get("answer", "")).strip()

    retrieval_q = _rewrite_question_for_retrieval(raw_q) if cfg["query_rewrite"] else raw_q

    conn = _get_thread_conn(db_host)
    ssid = _tl.search_space_id

    docs = rrf_hybrid_search(
        conn,
        retrieval_q,
        ssid,
        rrf_k=cfg["rrf_k"],
        top_k=cfg["top_k"],
        max_chunks_per_doc=cfg["max_chunks_per_doc"],
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
            "mode": "B1",
            "docs_retrieved":  len(docs),
            "chunks_total":    chunk_count,
            "matched_chunks":  matched_count,
            "context_chars":   len(context_xml),
            "llm_error":       llm_error,
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
# Benchmark runner — parallel workers
# ---------------------------------------------------------------------------

def _run_b1_benchmark(
    qas: list[dict],
    cfg: dict,
    chunk_size: int,
    run_name: str,
    workers: int,
    db_host: str,
) -> dict:
    """Run all questions in parallel, return payload dict."""
    total = len(qas)
    print(f"[{_now_utc()}] Mode B1 benchmark: {total} questions, {workers} worker(s)", flush=True)
    print(f"  Config: {cfg['label']}", flush=True)
    print(f"  chunk_size={chunk_size}  rrf_k={cfg['rrf_k']}  top_k={cfg['top_k']}  "
          f"max_chunks={cfg['max_chunks_per_doc']}  markers={cfg['matched_markers']}", flush=True)
    print("=" * 72, flush=True)

    results: list[dict | None] = [None] * total
    lock = threading.Lock()
    done_count = 0

    def _worker(idx: int, qa: dict) -> None:
        nonlocal done_count
        qid = qa.get("id", f"Q{idx+1:03d}")
        try:
            row = _run_question_b1(qa, cfg, db_host)
        except Exception as exc:
            row = {
                "id": str(qid),
                "group": str(qa.get("group", "unknown")),
                "question": str(qa.get("question", "")),
                "retrieval_query": "",
                "gold_answer": str(qa.get("answer", "")),
                "predicted_answer": f"ERROR: {exc}",
                "pipeline_telemetry": {"mode": "B1", "llm_error": str(exc)},
                "metrics": {
                    k: False for k in [
                        "semantic_intent_ok", "strict_exact", "normalized_exact",
                        "contains_gold", "number_match", "unit_match",
                        "primary_value_match", "strict_correct", "lenient_correct",
                        "overall_correct",
                    ]
                } | {k: 0.0 for k in [
                    "numeric_precision", "numeric_recall", "numeric_f1", "token_f1",
                ]} | {"cleaned_prediction": "", "answer_clean": ""},
            }

        with lock:
            results[idx] = row
            done_count += 1
            correct = row["metrics"].get("overall_correct", False)
            tel = row.get("pipeline_telemetry", {})
            err = tel.get("llm_error", "")
            pred_short = (row["metrics"].get("cleaned_prediction") or "")[:60]
            print(
                f"  [{_now_utc()}] ({done_count}/{total}) {row['id']} "
                f"{'✔' if correct else '✘'}  "
                f"docs={tel.get('docs_retrieved', 0)} chunks={tel.get('chunks_total', 0)}  "
                f"pred={pred_short!r}"
                + (f"  ERR={err[:80]}" if err else ""),
                flush=True,
            )

    if workers == 1:
        for i, qa in enumerate(qas):
            _worker(i, qa)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_worker, i, qa): i for i, qa in enumerate(qas)}
            for fut in concurrent.futures.as_completed(futures):
                fut.result()  # re-raise any uncaught exceptions

    results_final = [r for r in results if r is not None]
    failures = sum(
        1 for r in results_final
        if str(r.get("predicted_answer", "")).startswith("ERROR:")
    )

    summary = _aggregate(results_final)
    summary["request_failures"] = failures

    by_group: dict[str, Any] = {}
    for g in sorted({r["group"] for r in results_final}):
        grp_results = [r for r in results_final if r["group"] == g]
        by_group[g] = _aggregate(grp_results)
        by_group[g]["request_failures"] = sum(
            1 for r in grp_results
            if str(r.get("predicted_answer", "")).startswith("ERROR:")
        )

    payload = {
        "generated_at_utc": _now_utc(),
        "run_name": run_name,
        "mode": "B1",
        "chunk_size": chunk_size,
        "config": {
            **cfg,
            "embed_model": EMBED_MODEL,
            "llm_model": DEEPSEEK_MODEL,
            "llm_endpoint": DEEPSEEK_BASE_URL,
            "thinking_mode": True,
        },
        "summary": summary,
        "by_group": by_group,
        "results": results_final,
    }

    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{run_name}.json"
    md_path   = output_dir / f"{run_name}.md"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Write markdown summary
    lines = [
        f"# Mode B1 Benchmark: {run_name}",
        f"",
        f"Generated: {payload['generated_at_utc']}  ",
        f"Mode: B1 (direct pgvector, no SurfSense API)  ",
        f"Chunk size: {chunk_size}  ",
        f"LLM: {DEEPSEEK_MODEL} (thinking=high)  ",
        f"",
        f"## Overall",
        f"",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Overall correct | {summary['overall_correct_count']}/{summary['run']} ({summary['overall_correct_rate']:.0%}) |",
        f"| Number match | {summary['number_match_count']}/{summary['run']} ({summary['number_match_rate']:.0%}) |",
        f"| Unit match | {summary['unit_match_count']}/{summary['run']} ({summary['unit_match_rate']:.0%}) |",
        f"| Mean token F1 | {summary['mean_token_f1']:.4f} |",
        f"| Request failures | {failures} |",
        f"",
        f"## Per Group",
        f"",
        f"| Group | Correct | Num Match | Unit Match | F1 |",
        f"|---|---|---|---|---|",
    ]
    for g, gs in sorted(by_group.items()):
        lines.append(
            f"| {g} | {gs['overall_correct_count']}/{gs['run']} "
            f"({gs['overall_correct_rate']:.0%}) | "
            f"{gs['number_match_rate']:.0%} | "
            f"{gs['unit_match_rate']:.0%} | "
            f"{gs['mean_token_f1']:.3f} |"
        )
    lines += [
        f"",
        f"## Config",
        f"",
        f"| Setting | Value |",
        f"|---|---|",
        f"| rrf_k | {cfg['rrf_k']} |",
        f"| top_k | {cfg['top_k']} |",
        f"| max_chunks_per_doc | {cfg['max_chunks_per_doc']} |",
        f"| matched_markers | {cfg['matched_markers']} |",
        f"| query_rewrite | {cfg['query_rewrite']} |",
        f"| date_filter | {cfg['date_filter']} |",
        f"| embed_model | {EMBED_MODEL} |",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[{_now_utc()}] Wrote {json_path}", flush=True)
    print(f"[{_now_utc()}] Wrote {md_path}", flush=True)
    print(
        f"[{_now_utc()}] RESULT: {summary['overall_correct_count']}/{summary['run']} "
        f"({summary['overall_correct_rate']:.0%})  "
        f"num={summary['number_match_rate']:.0%}  "
        f"f1={summary['mean_token_f1']:.4f}  failures={failures}",
        flush=True,
    )
    return payload


# ---------------------------------------------------------------------------
# Per-chunk-size experiment step
# ---------------------------------------------------------------------------

def run_experiment_for_chunk_size(
    chunk_size: int,
    args: argparse.Namespace,
    qas: list[dict],
    run_name: str,
    dry_run: bool,
) -> dict | None:
    sep = "=" * 70
    print(f"\n{sep}", flush=True)
    print(f"  MODE B1 CHUNK SIZE EXPERIMENT: chunk_size={chunk_size}  run_name={run_name}", flush=True)
    print(sep, flush=True)

    # 1–3. Docker update + recreate + health check
    if not args.skip_docker:
        print(f"\n[1/5] Updating docker-compose.yml → CHUNKER_CHUNK_SIZE={chunk_size}", flush=True)
        _update_compose_chunk_size(DOCKER_COMPOSE_FILE, chunk_size, dry_run)

        print(f"\n[2/5] Force-recreating backend + celery_worker ...", flush=True)
        _docker_recreate([BACKEND_CONTAINER, CELERY_CONTAINER], dry_run)

        print(f"\n[3/5] Waiting for backend health ...", flush=True)
        if not dry_run:
            time.sleep(15)
        _wait_for_backend(dry_run)
    else:
        print(f"\n[1-3/5] Skipping docker restart (--skip-docker)", flush=True)

    # 4. Delete stale document + re-ingest
    if not args.skip_ingest:
        print(f"\n  Logging in to SurfSense API ...", flush=True)
        token = _login(SURFSENSE_BASE_URL, USERNAME, PASSWORD) if not dry_run else "dry-run"

        print(f"\n[4/5] Deleting stale documents + re-ingesting ...", flush=True)
        _delete_matching_documents(token, dry_run)
        if not dry_run:
            time.sleep(5)  # brief pause after deletion
        _upload_and_wait(token, DOCX_PATH, dry_run)

        if not dry_run:
            print("  Waiting 60s after indexing confirmed before querying pgvector ...", flush=True)
            time.sleep(60)
    else:
        print(f"\n[4/5] Skipping delete/ingest (--skip-ingest)", flush=True)

    # 5. Run Mode B1 benchmark
    print(f"\n[5/5] Running Mode B1 benchmark ({len(qas)} questions, {args.workers} workers) ...", flush=True)
    if dry_run:
        print("  [dry-run] skipping benchmark", flush=True)
        return None

    return _run_b1_benchmark(
        qas,
        BEST_CONFIG,
        chunk_size,
        run_name,
        workers=args.workers,
        db_host=args.db_host,
    )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mode B1 controlled chunk-size experiment: 256 vs 1024 with DeepSeek V4 Flash",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--chunk-sizes", nargs="+", type=int, default=[256, 1024], metavar="N",
        help="Chunk sizes to test in order (default: 256 1024)",
    )
    parser.add_argument(
        "--run-name-template",
        default="deepseekflash_B1_{chunk_size}chunk_controlled_v1",
        help="Run name template; {chunk_size} is substituted",
    )
    parser.add_argument("--benchmark-file", default=str(BENCH_FILE))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--workers", type=int, default=10,
        help="Parallel LLM call workers (default: 10)",
    )
    parser.add_argument(
        "--db-host", default=DB_HOST,
        help=f"pgvector DB host (default: {DB_HOST})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print all steps without executing docker/ingest/benchmark",
    )
    parser.add_argument(
        "--skip-docker", action="store_true",
        help="Skip docker-compose update and container restart",
    )
    parser.add_argument(
        "--skip-ingest", action="store_true",
        help="Skip document delete+upload (assume already ingested at correct chunk size)",
    )
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    global _DEEPSEEK_API_KEY, OUTPUT_DIR

    args = build_arg_parser().parse_args()
    dry_run = args.dry_run
    OUTPUT_DIR = Path(args.output_dir)

    print("=" * 70, flush=True)
    print("MODE B1 CONTROLLED CHUNK SIZE EXPERIMENT", flush=True)
    print(f"  Chunk sizes:  {args.chunk_sizes}", flush=True)
    print(f"  LLM:          {DEEPSEEK_MODEL} (thinking=high)", flush=True)
    print(f"  Workers:      {args.workers}", flush=True)
    print(f"  DB host:      {args.db_host}", flush=True)
    print(f"  Output dir:   {args.output_dir}", flush=True)
    print(f"  Config:       {BEST_CONFIG['label']}", flush=True)
    if dry_run:
        print("  *** DRY RUN — no changes will be made ***", flush=True)
    print("=" * 70, flush=True)

    # ── API key  ───────────────────────────────────────────────────────────
    if not dry_run:
        _DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if _DEEPSEEK_API_KEY:
            print("DeepSeek API key: (from DEEPSEEK_API_KEY env var)", flush=True)
        else:
            _DEEPSEEK_API_KEY = getpass.getpass("Enter your DeepSeek API key: ").strip()
            if not _DEEPSEEK_API_KEY:
                print("ERROR: API key cannot be empty.", file=sys.stderr)
                return 1
        print()

    # ── Load benchmark  ────────────────────────────────────────────────────
    bench_path = Path(args.benchmark_file)
    if not bench_path.exists():
        print(f"ERROR: {bench_path} not found", file=sys.stderr)
        return 2
    qas = load_benchmark(bench_path)
    print(f"[{_now_utc()}] Loaded {len(qas)} questions from {bench_path}", flush=True)

    # ── Warm up embedding model (before threading) ─────────────────────────
    if not dry_run:
        _get_embed_model()

    # ── Run each chunk size  ───────────────────────────────────────────────
    payloads: list[dict] = []
    for chunk_size in args.chunk_sizes:
        run_name = args.run_name_template.format(chunk_size=chunk_size)
        result = run_experiment_for_chunk_size(chunk_size, args, qas, run_name, dry_run)
        if result is not None:
            payloads.append(result)

    # ── Final summary  ─────────────────────────────────────────────────────
    print("\n" + "=" * 70, flush=True)
    print("EXPERIMENT COMPLETE — MODE B1 SUMMARY", flush=True)
    print("=" * 70, flush=True)
    for p in payloads:
        s = p["summary"]
        print(
            f"  chunk_size={p['chunk_size']:>4}  "
            f"{s['overall_correct_count']}/{s['run']} ({s['overall_correct_rate']:.0%})  "
            f"num={s['number_match_rate']:.0%}  "
            f"f1={s['mean_token_f1']:.4f}  "
            f"failures={s.get('request_failures', 0)}  "
            f"[{p['run_name']}]",
            flush=True,
        )
        bg = p.get("by_group", {})
        for g, gs in sorted(bg.items()):
            print(
                f"    {g}: {gs['overall_correct_count']}/{gs['run']} "
                f"({gs['overall_correct_rate']:.0%})  "
                f"num={gs['number_match_rate']:.0%}  "
                f"unit={gs['unit_match_rate']:.0%}  "
                f"f1={gs['mean_token_f1']:.3f}",
                flush=True,
            )
    print("=" * 70, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
