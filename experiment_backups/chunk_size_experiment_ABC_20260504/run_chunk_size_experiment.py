#!/usr/bin/env python3
"""Controlled chunk-size experiment: 256 vs 1024 tokens with DeepSeek V4 Flash.

This script orchestrates a single controlled variable comparison:
  - ONLY changes: CHUNKER_CHUNK_SIZE (256 or 1024)
  - EVERYTHING ELSE stays fixed (see Fixed Settings below)

Fixed Settings (do not change between runs):
  - Chunker:         chonkie.RecursiveChunker(chunk_size=N)  [no explicit overlap]
  - Chunk function:  chunk_text_hybrid (Markdown-table-aware, context-sandwich)
  - Embedding:       sentence-transformers/all-MiniLM-L6-v2 (384-dim)
  - Retrieval:       Hybrid (semantic + keyword fused via RRF)
  - Fusion:          RRF  k=60, FULL OUTER JOIN
  - Semantic:        pgvector cosine distance (<=>)
  - Keyword:         PostgreSQL ts_rank_cd, normalized OR-term tsquery
  - Max chunks/doc:  20
  - Reranker:        None
  - Agent LLM:       DeepSeek V4 Flash (DB config id=22)
  - Disabled tools:  web_search, scrape_webpage

Workflow per chunk-size:
  1. Update CHUNKER_CHUNK_SIZE in docker-compose.yml
  2. Force-recreate backend + celery_worker containers
  3. Wait for backend health
  4. Set agent_llm_id=22 on the search space
  5. Delete existing document (stale chunks from old chunk size)
  6. Re-upload MSFT_FY26Q1_10Q.docx and wait for ingestion
  7. Run the benchmark (delegates to run_surfsense_benchmark.py)

Usage:
  # Run both sizes automatically:
  python3 scripts/run_chunk_size_experiment.py

  # Run just one size:
  python3 scripts/run_chunk_size_experiment.py --chunk-sizes 256
  python3 scripts/run_chunk_size_experiment.py --chunk-sizes 1024

  # Dry-run (print plan, skip docker/ingest/benchmark):
  python3 scripts/run_chunk_size_experiment.py --dry-run

  # Skip docker restart (already at correct chunk size + already ingested):
  python3 scripts/run_chunk_size_experiment.py --chunk-sizes 1024 --skip-docker --skip-ingest

  # Skip LLM update (already set to DeepSeek Flash):
  python3 scripts/run_chunk_size_experiment.py --skip-llm-update
"""

from __future__ import annotations

import argparse
import email.generator
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SURFSENSE_BASE_URL = "http://localhost:8929"
DEEPSEEK_FLASH_LLM_CONFIG_ID = 22  # DB row id in new_llm_configs for deepseek-v4-flash
SEARCH_SPACE_ID = 1
USERNAME = "shi.yu@broadridge.com"
PASSWORD = "Lexar1357!!"

DOCX_PATH = Path("MSFT_FY26Q1_10Q.docx")
DOCUMENT_TITLE_CONTAINS = "MSFT_FY26Q1_10Q"

DOCKER_COMPOSE_FILE = Path("docker-compose.yml")
BACKEND_CONTAINER = "surfsense-backend-1"
CELERY_CONTAINER = "surfsense-celery_worker-1"

BACKEND_HEALTH_POLL_SECONDS = 10
BACKEND_HEALTH_MAX_WAIT = 180  # seconds

# How long to wait for indexing to complete after upload
INGEST_POLL_SECONDS = 10
INGEST_MAX_WAIT = 600  # seconds

OUTPUT_DIR = "benchmark_results_MSFT_FY26Q1_qa"
BENCHMARK_FILE = "msft_fy26q1_qa_benchmark_100_sanitized.json"

# ---------------------------------------------------------------------------
# HTTP helpers
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
        SURFSENSE_BASE_URL + path,
        data=data,
        headers=headers,
        method=method,
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
    """Multipart upload of a single file.  Returns the list of created document records."""
    # Build multipart manually (no requests library dependency)
    boundary = b"----SurfSenseExperimentBoundary7a3f"
    body_parts: list[bytes] = []

    # -- search_space_id field
    body_parts.append(
        b"--" + boundary
        + b"\r\nContent-Disposition: form-data; name=\"search_space_id\"\r\n\r\n"
        + str(search_space_id).encode()
    )
    # -- should_summarize = false
    body_parts.append(
        b"--" + boundary
        + b"\r\nContent-Disposition: form-data; name=\"should_summarize\"\r\n\r\nfalse"
    )
    # -- use_vision_llm = false
    body_parts.append(
        b"--" + boundary
        + b"\r\nContent-Disposition: form-data; name=\"use_vision_llm\"\r\n\r\nfalse"
    )
    # -- processing_mode = basic
    body_parts.append(
        b"--" + boundary
        + b"\r\nContent-Disposition: form-data; name=\"processing_mode\"\r\n\r\nbasic"
    )
    # -- file
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
                wait = 30 + attempt * 10
                print(f"  429 on file upload, waiting {wait}s ...", flush=True)
                time.sleep(wait)
                continue
            body_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Upload failed ({e.code}): {body_text}") from e


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def _update_compose_chunk_size(compose_file: Path, new_size: int, dry_run: bool) -> None:
    """Replace CHUNKER_CHUNK_SIZE value in docker-compose.yml (all occurrences)."""
    text = compose_file.read_text(encoding="utf-8")
    pattern = r'(CHUNKER_CHUNK_SIZE:\s*")[^"]*(")'
    new_text, count = re.subn(pattern, rf'\g<1>{new_size}\g<2>', text)
    if count == 0:
        raise RuntimeError("Could not find CHUNKER_CHUNK_SIZE in docker-compose.yml")
    print(f"  Updating docker-compose.yml: CHUNKER_CHUNK_SIZE → {new_size} ({count} occurrence(s))", flush=True)
    if not dry_run:
        compose_file.write_text(new_text, encoding="utf-8")


def _docker_recreate(containers: list[str], dry_run: bool) -> None:
    """docker compose up -d --force-recreate for specified services."""
    # Map container names to service names (strip project prefix + suffix)
    services = [c.replace("surfsense-", "").rstrip("-1") for c in containers]
    cmd = ["docker", "compose", "up", "-d", "--force-recreate"] + services
    print(f"  Running: {' '.join(cmd)}", flush=True)
    if not dry_run:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"docker compose failed:\n{result.stderr}")
        if result.stdout.strip():
            print(f"  {result.stdout.strip()}", flush=True)


def _wait_for_backend(dry_run: bool) -> None:
    """Poll /health until the backend responds 200."""
    if dry_run:
        print("  [dry-run] skip wait_for_backend", flush=True)
        return
    deadline = time.time() + BACKEND_HEALTH_MAX_WAIT
    print(f"  Waiting for backend to be healthy (max {BACKEND_HEALTH_MAX_WAIT}s) ...", flush=True)
    while time.time() < deadline:
        try:
            code = urllib.request.urlopen(
                SURFSENSE_BASE_URL + "/health", timeout=5
            ).status
            if code == 200:
                print("  Backend is healthy.", flush=True)
                return
        except Exception:
            pass
        time.sleep(BACKEND_HEALTH_POLL_SECONDS)
    raise RuntimeError(f"Backend did not become healthy within {BACKEND_HEALTH_MAX_WAIT}s")


# ---------------------------------------------------------------------------
# SurfSense API helpers
# ---------------------------------------------------------------------------


def _set_agent_llm(token: str, search_space_id: int, llm_config_id: int, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] skip set agent_llm_id={llm_config_id}", flush=True)
        return
    resp = _api("PUT", f"/api/v1/search-spaces/{search_space_id}/llm-preferences",
                token, json_body={"agent_llm_id": llm_config_id})
    print(f"  agent_llm_id set → {resp.get('agent_llm_id')} "
          f"(model: {(resp.get('agent_llm') or {}).get('model_name', '?')})", flush=True)


def _list_documents(token: str, search_space_id: int) -> list[dict]:
    resp = _api("GET", f"/api/v1/documents?search_space_id={search_space_id}&page_size=-1",
                token, timeout=30)
    return resp.get("items", [])


def _delete_matching_documents(token: str, search_space_id: int, title_contains: str,
                                dry_run: bool) -> list[int]:
    """Delete all documents whose title contains title_contains. Returns deleted IDs."""
    if dry_run:
        print(f"  [dry-run] skip delete documents matching '{title_contains}'", flush=True)
        return []
    docs = _list_documents(token, search_space_id)
    needle = title_contains.lower()
    matching = [d for d in docs if needle in str(d.get("title", "")).lower()]
    ids = [d["id"] for d in matching if "id" in d]
    if not ids:
        print(f"  No existing documents matched title filter '{title_contains}'.", flush=True)
        return []
    for doc_id in ids:
        title = next((d.get("title","?") for d in matching if d.get("id") == doc_id), "?")
        print(f"  Deleting document id={doc_id} title='{title}' ...", flush=True)
        if not dry_run:
            _api("DELETE", f"/api/v1/documents/{doc_id}", token)
    return ids


def _upload_and_wait(token: str, file_path: Path, search_space_id: int,
                     dry_run: bool) -> list[int]:
    """Upload file and poll until all resulting documents are fully indexed."""
    if dry_run:
        print(f"  [dry-run] skip upload of {file_path}", flush=True)
        return []
    print(f"  Uploading {file_path} ...", flush=True)
    created = _upload_file(token, file_path, search_space_id)
    doc_ids = [d["id"] for d in created if isinstance(d.get("id"), int)]
    print(f"  Upload queued. Document IDs: {doc_ids}. Waiting for indexing ...", flush=True)

    deadline = time.time() + INGEST_MAX_WAIT
    pending = set(doc_ids)
    while pending and time.time() < deadline:
        time.sleep(INGEST_POLL_SECONDS)
        # Re-fetch fresh token (avoid expiry during long ingestion)
        for doc_id in list(pending):
            try:
                doc = _api("GET", f"/api/v1/documents/{doc_id}", token, timeout=30)
                status = doc.get("indexing_status") or doc.get("status") or "unknown"
                print(f"    doc {doc_id} status={status}", flush=True)
                if status in ("indexed", "completed", "done", "success"):
                    pending.discard(doc_id)
                elif status in ("failed", "error"):
                    raise RuntimeError(f"Document {doc_id} indexing failed (status={status})")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print(f"    429 rate limit polling doc {doc_id}, sleeping 30s ...", flush=True)
                    time.sleep(30)
                else:
                    raise

    # Final chunk count check
    for doc_id in doc_ids:
        try:
            doc = _api("GET", f"/api/v1/documents/{doc_id}", token, timeout=30)
            num_chunks = doc.get("num_chunks") or doc.get("chunks_count") or "?"
            title = doc.get("title", "?")
            print(f"  doc {doc_id} '{title}': num_chunks={num_chunks}", flush=True)
        except Exception as e:
            print(f"  Warning: could not fetch final doc status for {doc_id}: {e}", flush=True)

    if pending:
        raise RuntimeError(
            f"Timed out waiting for documents to be indexed: {pending}"
        )
    return doc_ids


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def _run_benchmark(run_name: str, chunk_size: int, args: argparse.Namespace, dry_run: bool) -> int:
    """Invoke run_surfsense_benchmark.py for this run."""
    cmd = [
        sys.executable,
        "scripts/run_surfsense_benchmark.py",
        "--config", args.config,
        "--benchmark-file", args.benchmark_file,
        "--max-questions", str(args.max_questions),
        "--start-question", str(args.start_question),
        "--run-name", run_name,
        "--output-dir", args.output_dir,
        "--document-title-contains", DOCUMENT_TITLE_CONTAINS,
        "--sanitize-questions", "true",
        "--sleep-between", str(args.sleep_between),
        "--request-timeout", str(args.request_timeout),
        "--workers", str(args.workers),
        "--disabled-tools", "web_search,scrape_webpage",
    ]
    if getattr(args, 'enforce_ranked_evidence_first', None) is True:
        cmd += ["--enforce-ranked-evidence-first"]
    elif getattr(args, 'enforce_ranked_evidence_first', None) is False:
        cmd += ["--no-enforce-ranked-evidence-first"]

    print(f"\n  Running: {' '.join(cmd)}", flush=True)
    if dry_run:
        print("  [dry-run] skipping subprocess", flush=True)
        return 0
    result = subprocess.run(cmd)
    return result.returncode


# ---------------------------------------------------------------------------
# Main experiment step
# ---------------------------------------------------------------------------


def run_experiment_for_chunk_size(
    chunk_size: int,
    args: argparse.Namespace,
    run_name: str,
    dry_run: bool,
) -> int:
    """Full experiment run for one chunk size: docker + ingest + benchmark."""
    sep = "=" * 70
    print(f"\n{sep}", flush=True)
    print(f"  CHUNK SIZE EXPERIMENT: chunk_size={chunk_size}  run_name={run_name}", flush=True)
    print(sep, flush=True)

    # 1. Update docker-compose.yml
    if not args.skip_docker:
        print(f"\n[1/6] Updating docker-compose.yml → CHUNKER_CHUNK_SIZE={chunk_size}", flush=True)
        _update_compose_chunk_size(DOCKER_COMPOSE_FILE, chunk_size, dry_run)

        # 2. Recreate containers
        print(f"\n[2/6] Force-recreating backend + celery_worker ...", flush=True)
        _docker_recreate([BACKEND_CONTAINER, CELERY_CONTAINER], dry_run)

        # 3. Wait for health
        print(f"\n[3/6] Waiting for backend health ...", flush=True)
        # Give containers a moment to start shutting down before polling
        if not dry_run:
            time.sleep(15)
        _wait_for_backend(dry_run)
    else:
        print(f"\n[1-3/6] Skipping docker restart (--skip-docker)", flush=True)

    # Login
    print(f"\n  Logging in ...", flush=True)
    token = _login(SURFSENSE_BASE_URL, USERNAME, PASSWORD) if not dry_run else "dry-run-token"

    # 4. Set agent LLM
    if not args.skip_llm_update:
        print(f"\n[4/6] Setting agent_llm_id={DEEPSEEK_FLASH_LLM_CONFIG_ID} ...", flush=True)
        _set_agent_llm(token, SEARCH_SPACE_ID, DEEPSEEK_FLASH_LLM_CONFIG_ID, dry_run)
    else:
        print(f"\n[4/6] Skipping LLM update (--skip-llm-update)", flush=True)

    # 5. Delete stale document + re-ingest
    if not args.skip_ingest:
        print(f"\n[5/6] Deleting stale documents matching '{DOCUMENT_TITLE_CONTAINS}' ...", flush=True)
        _delete_matching_documents(token, SEARCH_SPACE_ID, DOCUMENT_TITLE_CONTAINS, dry_run)

        print(f"\n[6/6] Re-uploading {DOCX_PATH} ...", flush=True)
        _upload_and_wait(token, DOCX_PATH, SEARCH_SPACE_ID, dry_run)
    else:
        print(f"\n[5-6/6] Skipping delete/ingest (--skip-ingest)", flush=True)

    # 7. Run benchmark
    print(f"\n[7/7] Running benchmark run_name={run_name} ...", flush=True)
    rc = _run_benchmark(run_name, chunk_size, args, dry_run)
    if rc != 0:
        print(f"  WARNING: benchmark process exited with code {rc}", flush=True)

    return rc


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controlled chunk-size experiment: 256 vs 1024 with DeepSeek V4 Flash",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--chunk-sizes",
        nargs="+",
        type=int,
        default=[256, 1024],
        metavar="N",
        help="Chunk sizes to test in order (default: 256 1024)",
    )
    parser.add_argument(
        "--run-name-template",
        default="deepseekflash_{chunk_size}chunk_controlled_v1",
        help="Run name template; {chunk_size} is substituted (default: deepseekflash_{chunk_size}chunk_controlled_v1)",
    )
    parser.add_argument("--benchmark-file", default=BENCHMARK_FILE)
    parser.add_argument("--max-questions", type=int, default=100)
    parser.add_argument("--start-question", type=int, default=1)
    parser.add_argument("--config", default="benchmark_runner_config.json")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--sleep-between", type=float, default=0.0)
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all steps without executing docker/ingest/benchmark",
    )
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip docker-compose update and container restart (assume already at correct chunk size)",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip document delete+upload (assume document already ingested at correct chunk size)",
    )
    parser.add_argument(
        "--skip-llm-update",
        action="store_true",
        help="Skip updating the search space LLM preference (assume already set to DeepSeek Flash)",
    )
    ranked_group = parser.add_mutually_exclusive_group()
    ranked_group.add_argument("--enforce-ranked-evidence-first", dest="enforce_ranked_evidence_first", action="store_true")
    ranked_group.add_argument("--no-enforce-ranked-evidence-first", dest="enforce_ranked_evidence_first", action="store_false")
    parser.set_defaults(enforce_ranked_evidence_first=None)
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    args = build_arg_parser().parse_args()
    dry_run = args.dry_run

    print("=" * 70, flush=True)
    print("CONTROLLED CHUNK SIZE EXPERIMENT", flush=True)
    print(f"  Chunk sizes to test: {args.chunk_sizes}", flush=True)
    print(f"  Agent LLM:          DeepSeek V4 Flash (DB id={DEEPSEEK_FLASH_LLM_CONFIG_ID})", flush=True)
    print(f"  Document:           {DOCX_PATH}", flush=True)
    print(f"  Output dir:         {args.output_dir}", flush=True)
    if dry_run:
        print("  *** DRY RUN — no changes will be made ***", flush=True)
    print("=" * 70, flush=True)

    overall_rc = 0
    for chunk_size in args.chunk_sizes:
        run_name = args.run_name_template.format(chunk_size=chunk_size)
        rc = run_experiment_for_chunk_size(chunk_size, args, run_name, dry_run)
        if rc != 0:
            overall_rc = rc

    print("\n" + "=" * 70, flush=True)
    print("EXPERIMENT COMPLETE", flush=True)
    for chunk_size in args.chunk_sizes:
        run_name = args.run_name_template.format(chunk_size=chunk_size)
        json_path = Path(args.output_dir) / f"{run_name}.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text())
                s = data.get("summary", {})
                correct = s.get("correct", s.get("num_correct", "?"))
                total = s.get("questions_run", "?")
                pct = s.get("score_percent", s.get("percent_correct", "?"))
                print(f"  chunk_size={chunk_size:>4}  score={correct}/{total}  ({pct}%)  [{run_name}]")
            except Exception:
                print(f"  chunk_size={chunk_size:>4}  [results not readable: {json_path}]")
        else:
            print(f"  chunk_size={chunk_size:>4}  [no results file: {json_path}]")
    print("=" * 70, flush=True)

    return overall_rc


if __name__ == "__main__":
    sys.exit(main())
