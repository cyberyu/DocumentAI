#!/usr/bin/env python3
"""Run benchmark QA against DeepSeek using the /v1/batches (OpenAI-compatible) API.

Workflow:
  1. Load benchmark qa_pairs and local document text.
  2. Rank document chunks per question (same lexical ranker as the direct script).
  3. Write a JSONL file containing one chat/completions request per question.
  4. Upload the JSONL to /v1/files (purpose=batch).
  5. Submit the batch via /v1/batches.
  6. Poll /v1/batches/{id} until status == "completed".
  7. Download the output JSONL from /v1/files/{output_file_id}/content.
  8. Parse responses, evaluate and write JSON/Markdown reports.

Usage:
    export DEEPSEEK_API_KEY=sk-...
    python3 scripts/run_deepseek_batch_benchmark.py \\
        --run-name deepseekflash_batch_full100_v1 \\
        --max-questions 100

The output artifacts are written to benchmark_results_MSFT_FY26Q1_qa/ and are
compatible with all existing analysis scripts.
"""

from __future__ import annotations

import argparse
import email.generator
import email.mime.multipart
import email.mime.base
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

# Allow running from both the repo root and backup folders.
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from run_surfsense_benchmark import (
    _aggregate,
    _now_utc,
    _rewrite_question_for_retrieval,
    evaluate_answer,
    load_benchmark,
    write_outputs,
)

# ---------------------------------------------------------------------------
# Document helpers (shared with run_deepseek_direct_benchmark.py)
# ---------------------------------------------------------------------------

def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _read_docx_text(path: Path) -> str:
    import html as _html
    with zipfile.ZipFile(path, "r") as zf:
        with zf.open("word/document.xml") as fp:
            xml_data = fp.read().decode("utf-8", errors="replace")
    xml_data = xml_data.replace("</w:p>", "\n").replace("<w:tab/>", "\t")
    xml_data = re.sub(r"<[^>]+>", " ", xml_data)
    plain = _html.unescape(xml_data)
    plain = re.sub(r"\n\s*\n+", "\n", plain)
    return _normalize_space(plain)


def read_document_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return _read_docx_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


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


def _tokenize_lex(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9$%. ]+", " ", text)
    return [t for t in text.split() if t]


def rank_chunks(question: str, chunks: list[str], top_k: int) -> list[str]:
    q_tokens = set(_tokenize_lex(question))
    scored: list[tuple[int, int, str]] = []
    for idx, chunk in enumerate(chunks):
        c_tokens = set(_tokenize_lex(chunk))
        overlap = len(q_tokens & c_tokens)
        numeric_hint = 1 if re.search(r"\$|\b(?:million|billion|percent|%)\b|\d", chunk.lower()) else 0
        scored.append((overlap * 10 + numeric_hint, -idx, chunk))
    scored.sort(reverse=True)
    return [it[2] for it in scored[: max(1, top_k)]]


# ---------------------------------------------------------------------------
# JSONL batch request builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You extract one financial value from provided context. "
    "Answer from context only. "
    "Return strict JSON: {\"answer\": \"<one value with unit>\"}. "
    "If unavailable, return {\"answer\": \"\"}. "
    "Do not include explanations or extra keys."
)


def _build_user_prompt(question: str, context_chunks: list[str]) -> str:
    context_blob = "\n\n".join(
        f"[chunk {i + 1}]\n{chunk}" for i, chunk in enumerate(context_chunks)
    )
    return (
        f"Question:\n{question}\n\n"
        f"Context:\n{context_blob}\n\n"
        "Output JSON only."
    )


def build_batch_jsonl(
    qas: list[dict[str, Any]],
    *,
    chunks: list[str],
    top_k: int,
    model: str,
    temperature: float | None,
    sanitize_questions: bool,
    thinking_enabled: bool = True,
    reasoning_effort: str | None = "high",
) -> bytes:
    """Return JSONL bytes — one request line per question."""
    lines: list[str] = []
    for qa in qas:
        qid = str(qa.get("id", ""))
        question = str(qa.get("question", "")).strip()
        asked = _rewrite_question_for_retrieval(question) if sanitize_questions else question
        top_chunks = rank_chunks(asked, chunks, top_k)
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(asked, top_chunks)},
            ],
            "stream": False,
        }
        if thinking_enabled:
            body["thinking"] = {"type": "enabled"}
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort
        if temperature is not None:
            body["temperature"] = temperature
        lines.append(json.dumps({
            "custom_id": qid,
            "method": "POST",
            "url": "/chat/completions",
            "body": body,
        }))
    return ("\n".join(lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# DeepSeek Batch API client
# ---------------------------------------------------------------------------

class DeepSeekBatchClient:
    def __init__(self, api_key: str, base_url: str, timeout: float = 120.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _json_request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=self._headers({"Content-Type": "application/json"} if data else None),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {method} {path}: {detail}") from exc

    def _raw_get(self, path: str) -> bytes:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} GET {path}: {detail}") from exc

    # -- Files API -----------------------------------------------------------

    def upload_file(self, jsonl_bytes: bytes, filename: str = "batch_input.jsonl") -> str:
        """Upload a JSONL file with purpose=batch. Returns file_id."""
        boundary = "----BatchBoundary7f3a9b2e"
        body_parts: list[bytes] = []

        def part(name: str, value: str) -> bytes:
            return (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")

        body_parts.append(part("purpose", "batch"))
        body_parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: application/jsonl\r\n\r\n"
            ).encode("utf-8")
            + jsonl_bytes
            + b"\r\n"
        )
        body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(body_parts)

        url = f"{self.base_url}/v1/files"
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers=self._headers({
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            }),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} POST /v1/files: {detail}") from exc

        file_id = payload.get("id") or payload.get("file_id")
        if not file_id:
            raise RuntimeError(f"File upload response missing id: {payload}")
        return str(file_id)

    def delete_file(self, file_id: str) -> None:
        try:
            self._json_request("DELETE", f"/v1/files/{file_id}")
        except RuntimeError:
            pass  # Best-effort cleanup.

    def download_file(self, file_id: str) -> bytes:
        return self._raw_get(f"/v1/files/{file_id}/content")

    # -- Batches API ---------------------------------------------------------

    def create_batch(self, input_file_id: str, completion_window: str = "24h") -> dict[str, Any]:
        return self._json_request("POST", "/v1/batches", {
            "input_file_id": input_file_id,
            "endpoint": "/chat/completions",
            "completion_window": completion_window,
        })

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        return self._json_request("GET", f"/v1/batches/{batch_id}")

    def cancel_batch(self, batch_id: str) -> dict[str, Any]:
        return self._json_request("POST", f"/v1/batches/{batch_id}/cancel")

    def poll_until_done(
        self,
        batch_id: str,
        *,
        poll_interval: float = 10.0,
        max_wait: float = 7200.0,
        terminal_statuses: frozenset[str] = frozenset({"completed", "failed", "expired", "cancelled"}),
    ) -> dict[str, Any]:
        deadline = time.time() + max_wait
        while True:
            batch = self.get_batch(batch_id)
            status = batch.get("status", "unknown")
            counts = batch.get("request_counts", {})
            print(
                f"  [{_now_utc()}] batch {batch_id} status={status} "
                f"completed={counts.get('completed', '?')} "
                f"failed={counts.get('failed', '?')} "
                f"total={counts.get('total', '?')}",
                flush=True,
            )
            if status in terminal_statuses:
                return batch
            if time.time() > deadline:
                raise TimeoutError(f"Batch {batch_id} did not finish within {max_wait}s (last status: {status})")
            time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_output_jsonl(raw: bytes) -> dict[str, str]:
    """Parse output JSONL, returning {custom_id: answer_text}."""
    results: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        custom_id = str(obj.get("custom_id", ""))
        # Standard OpenAI batch output format:
        # {"id": "...", "custom_id": "...", "response": {"status_code": 200, "body": {...}}}
        response = obj.get("response") or {}
        status_code = response.get("status_code", 0)
        if status_code != 200:
            results[custom_id] = ""
            continue
        body = response.get("body") or {}
        try:
            raw_text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raw_text = (body.get("error") or {}).get("message", "")

        # Parse strict JSON answer from model output.
        answer = ""
        candidate = raw_text.strip()
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if match:
            candidate = match.group(0)
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
                answer = parsed["answer"].strip()
        except json.JSONDecodeError:
            answer = candidate.strip()
        results[custom_id] = answer
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run DeepSeek batch benchmark over local document")
    parser.add_argument(
        "--benchmark-file",
        default="msft_fy26q1_qa_benchmark_100_sanitized.json",
        help="Path to benchmark JSON with qa_pairs",
    )
    parser.add_argument(
        "--doc-file",
        default="MSFT_FY26Q1_10Q.docx",
        help="Local document path (.docx/.md/.txt)",
    )
    parser.add_argument(
        "--model",
        default="deepseek-v4-flash",
        help="DeepSeek model id: deepseek-v4-flash | deepseek-v4-pro (default: deepseek-v4-flash)",
    )
    parser.add_argument(
        "--deepseek-url",
        default="https://api.deepseek.com",
        help="DeepSeek API base URL (default: https://api.deepseek.com). No /v1 suffix.",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=100,
        help="Max questions to submit (0 = all)",
    )
    parser.add_argument(
        "--start-question",
        type=int,
        default=1,
        help="1-based question index to start from (default: 1)",
    )
    parser.add_argument(
        "--run-name",
        default="deepseekflash_batch_full100_v1",
        help="Output filename prefix",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results_MSFT_FY26Q1_qa",
        help="Directory for JSON/MD reports",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="Top lexical chunks per question (default: 8)",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=2200,
        help="Chunk size in characters for local retrieval (default: 2200)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=300,
        help="Overlap in characters between consecutive chunks (default: 300)",
    )
    parser.add_argument(
        "--api-key-env",
        default="DEEPSEEK_API_KEY",
        help="Environment variable with DeepSeek API key (default: DEEPSEEK_API_KEY)",
    )
    parser.add_argument(
        "--completion-window",
        default="24h",
        help="Batch completion window accepted by the API (default: 24h)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=15.0,
        help="Seconds between batch status polls (default: 15)",
    )
    parser.add_argument(
        "--max-wait",
        type=float,
        default=7200.0,
        help="Max seconds to wait for batch to finish (default: 7200)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Optional sampling temperature",
    )
    parser.add_argument(
        "--thinking",
        default="true",
        help="Enable DeepSeek thinking mode: {\"type\": \"enabled\"} (default: true)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="high",
        help="DeepSeek reasoning_effort value: low|medium|high (default: high). Pass empty string to omit.",
    )
    parser.add_argument(
        "--sanitize-questions",
        default="true",
        help="Apply _rewrite_question_for_retrieval() before building prompts (default: true)",
    )
    parser.add_argument(
        "--save-jsonl",
        default=None,
        help="If set, also write the batch input JSONL to this path (for inspection)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=120.0,
        help="HTTP timeout for individual API calls (default: 120)",
    )
    return parser


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> int:
    args = build_arg_parser().parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        # Try reading from .env file in repo root.
        env_path = _REPO_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith(f"{args.api_key_env}="):
                    api_key = line.split("=", 1)[1].strip().strip("\"'")
    if not api_key:
        print(f"ERROR: set {args.api_key_env} env var to your DeepSeek API key", file=sys.stderr)
        return 2

    benchmark_path = Path(args.benchmark_file)
    if not benchmark_path.exists():
        print(f"ERROR: benchmark file not found: {benchmark_path}", file=sys.stderr)
        return 2
    doc_path = Path(args.doc_file)
    if not doc_path.exists():
        print(f"ERROR: document file not found: {doc_path}", file=sys.stderr)
        return 2

    sanitize = _as_bool(args.sanitize_questions)

    print(f"[{_now_utc()}] Loading benchmark from {benchmark_path}")
    qas_all = load_benchmark(benchmark_path)
    total_qas = len(qas_all)
    if args.start_question < 1 or args.start_question > total_qas:
        print(f"ERROR: --start-question {args.start_question} out of range 1..{total_qas}", file=sys.stderr)
        return 2
    qas = qas_all[args.start_question - 1 :]
    if args.max_questions and args.max_questions > 0:
        qas = qas[: args.max_questions]

    print(f"[{_now_utc()}] Reading document from {doc_path}")
    full_text = read_document_text(doc_path)
    chunks = chunk_text(full_text, args.chunk_chars, args.chunk_overlap)
    print(f"[{_now_utc()}] {len(chunks)} chunks @ {args.chunk_chars} chars, overlap {args.chunk_overlap}")
    print(f"[{_now_utc()}] Building {len(qas)} batch requests (model={args.model}, top_k={args.top_k})")

    thinking_enabled = _as_bool(args.thinking)
    reasoning_effort = args.reasoning_effort.strip() or None

    # Build JSONL payload.
    jsonl_bytes = build_batch_jsonl(
        qas,
        chunks=chunks,
        top_k=args.top_k,
        model=args.model,
        temperature=args.temperature,
        sanitize_questions=sanitize,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )

    if args.save_jsonl:
        Path(args.save_jsonl).write_bytes(jsonl_bytes)
        print(f"[{_now_utc()}] Saved input JSONL to {args.save_jsonl}")

    client = DeepSeekBatchClient(api_key=api_key, base_url=args.deepseek_url, timeout=args.request_timeout)

    # Step 1: Upload file.
    print(f"[{_now_utc()}] Uploading input JSONL ({len(jsonl_bytes):,} bytes) to /v1/files ...")
    input_file_id = client.upload_file(jsonl_bytes, filename=f"{args.run_name}_input.jsonl")
    print(f"[{_now_utc()}] input_file_id={input_file_id}")

    # Step 2: Create batch.
    print(f"[{_now_utc()}] Creating batch (completion_window={args.completion_window}) ...")
    batch = client.create_batch(input_file_id, completion_window=args.completion_window)
    batch_id = batch.get("id")
    if not batch_id:
        print(f"ERROR: batch create response missing id: {batch}", file=sys.stderr)
        return 2
    print(f"[{_now_utc()}] batch_id={batch_id}  status={batch.get('status')}")

    # Step 3: Poll until done.
    print(f"[{_now_utc()}] Polling (interval={args.poll_interval}s, max_wait={args.max_wait}s) ...")
    try:
        batch = client.poll_until_done(
            batch_id,
            poll_interval=args.poll_interval,
            max_wait=args.max_wait,
        )
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"\n[{_now_utc()}] Interrupted — cancelling batch {batch_id} ...")
        try:
            client.cancel_batch(batch_id)
        except Exception:
            pass
        return 130

    final_status = batch.get("status")
    if final_status != "completed":
        errors = batch.get("errors") or {}
        print(f"ERROR: batch ended with status={final_status}  errors={errors}", file=sys.stderr)
        return 2

    # Step 4: Download output file.
    output_file_id = batch.get("output_file_id")
    if not output_file_id:
        print("ERROR: batch has no output_file_id", file=sys.stderr)
        return 2
    print(f"[{_now_utc()}] Downloading output file {output_file_id} ...")
    output_bytes = client.download_file(output_file_id)
    print(f"[{_now_utc()}] Downloaded {len(output_bytes):,} bytes")

    # Step 5: Parse responses.
    answers_by_id = parse_output_jsonl(output_bytes)
    print(f"[{_now_utc()}] Parsed {len(answers_by_id)} answers")

    # Step 6: Evaluate.
    results: list[dict[str, Any]] = []
    failures = 0
    for qa in qas:
        qid = str(qa.get("id", ""))
        group = str(qa.get("group", "unknown"))
        question = str(qa.get("question", "")).strip()
        asked = _rewrite_question_for_retrieval(question) if sanitize else question
        gold = str(qa.get("answer", "")).strip()
        pred = answers_by_id.get(qid, "")

        if not pred:
            failures += 1

        metrics = evaluate_answer(gold=gold, pred=pred)
        pred_preview = metrics.cleaned_prediction.replace("\n", " ")[:140]
        print(
            f"  {qid}: num={'Y' if metrics.number_match else 'N'} "
            f"unit={'Y' if metrics.unit_match else 'N'} "
            f"correct={'Y' if metrics.overall_correct else 'N'} "
            f"pred={pred_preview!r}",
            flush=True,
        )

        results.append({
            "id": qid,
            "group": group,
            "question": question,
            "asked_question": asked,
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

    # Aggregate by group.
    by_group: dict[str, Any] = {}
    groups_seen: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        g = item["group"]
        groups_seen.setdefault(g, []).append(item)
    for g, items in sorted(groups_seen.items()):
        by_group[g] = _aggregate(items)
        by_group[g]["questions_total"] = len(items)

    summary = _aggregate(results)
    summary["questions_total"] = total_qas
    summary["questions_run"] = len(qas)
    summary["request_failures"] = failures

    payload: dict[str, Any] = {
        "generated_at_utc": _now_utc(),
        "config": {
            "model": args.model,
            "deepseek_url": args.deepseek_url,
            "benchmark_file": args.benchmark_file,
            "doc_file": args.doc_file,
            "top_k": args.top_k,
            "chunk_chars": args.chunk_chars,
            "chunk_overlap": args.chunk_overlap,
            "sanitize_questions": sanitize,
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort,
            "completion_window": args.completion_window,
            "batch_id": batch_id,
            "input_file_id": input_file_id,
            "output_file_id": output_file_id,
        },
        "summary": summary,
        "by_group": by_group,
        "results": results,
    }

    output_dir = Path(args.output_dir)
    json_path, md_path = write_outputs(output_dir, args.run_name, payload)
    print(f"\n[{_now_utc()}] Results written to:")
    print(f"  JSON: {json_path}")
    print(f"  MD  : {md_path}")
    print(
        f"\nSummary: {summary['overall_correct_count']}/{summary['questions_run']} correct "
        f"({summary['overall_correct_rate']:.2%})  "
        f"num_match={summary['number_match_rate']:.2%}  "
        f"failures={failures}"
    )

    # Clean up uploaded input file (best-effort).
    try:
        client.delete_file(input_file_id)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
