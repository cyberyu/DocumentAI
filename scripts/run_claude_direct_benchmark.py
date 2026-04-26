#!/usr/bin/env python3
"""Run benchmark QA by calling Anthropic Claude directly over local document text.

This bypasses SurfSense chat orchestration and performs local retrieval + extraction:
1) Load benchmark qa_pairs JSON
2) Read local document (.docx/.md/.txt)
3) Rank text chunks for each question using simple lexical overlap
4) Ask Anthropic Messages API for a single value-with-unit answer
5) Evaluate and write JSON/Markdown reports compatible with existing artifacts
"""

from __future__ import annotations

import argparse
from collections import deque
import getpass
import html
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

from run_surfsense_benchmark import _aggregate, _now_utc, evaluate_answer, load_benchmark, write_outputs

DEFAULT_MODEL = "claude-3-7-sonnet-latest"


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
        value = raw[len(prefix) :].strip()
        if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
            value = value[1:-1]
        return value.strip()
    return ""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run direct Claude benchmark over local document")
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
        default=None,
        help=(
            "Claude model id (examples: claude-3-7-sonnet-latest, "
            "claude-sonnet-4-20250514, claude-opus-4-1-20250805)"
        ),
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=10,
        help="If >0, run only the first N questions",
    )
    parser.add_argument(
        "--run-name",
        default="claude_direct_check10",
        help="Run name prefix for output artifacts",
    )
    parser.add_argument(
        "--base-url",
        default="https://api.anthropic.com",
        help="Base URL for Anthropic API",
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
        help="Top lexical chunks to pass to the model per question",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=2200,
        help="Chunk size in characters for local retrieval",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=300,
        help="Overlap in characters between consecutive chunks",
    )
    parser.add_argument(
        "--sleep-between",
        type=float,
        default=0.0,
        help="Seconds to sleep between questions",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key passed directly on command line (overrides env/.env)",
    )
    parser.add_argument(
        "--no-interactive-api-key",
        action="store_true",
        help="Disable interactive API key prompt and only use --api-key/env/.env",
    )
    parser.add_argument(
        "--api-key-env",
        default="ANTHROPIC_API_KEY",
        help="Environment variable containing Anthropic API key",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=120.0,
        help="HTTP timeout seconds for API request",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature (default 0.0 for deterministic extraction)",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=128,
        help="Max output tokens from Claude",
    )
    parser.add_argument(
        "--anthropic-version",
        default="2023-06-01",
        help="Anthropic API version header value",
    )
    parser.add_argument(
        "--skip-model-query",
        action="store_true",
        help="Skip querying /v1/models and trust provided/default model",
    )
    parser.add_argument(
        "--max-input-tokens-per-minute",
        type=int,
        default=28000,
        help=(
            "Estimated input token budget per minute for pacing (0 disables). "
            "Default 28000 keeps under a 30000 TPM org limit with safety margin."
        ),
    )
    parser.add_argument(
        "--chars-per-token",
        type=float,
        default=4.0,
        help="Estimated characters per token for pacing math",
    )
    parser.add_argument(
        "--retry-429-max-attempts",
        type=int,
        default=2,
        help="Number of retries on Anthropic HTTP 429",
    )
    parser.add_argument(
        "--retry-429-wait-seconds",
        type=float,
        default=20.0,
        help="Base wait seconds before retrying after HTTP 429",
    )
    return parser


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path, "r") as zf:
        with zf.open("word/document.xml") as fp:
            xml_data = fp.read().decode("utf-8", errors="replace")

    xml_data = xml_data.replace("</w:p>", "\n")
    xml_data = xml_data.replace("<w:tab/>", "\t")
    xml_data = re.sub(r"<[^>]+>", " ", xml_data)
    plain = html.unescape(xml_data)
    plain = re.sub(r"\n\s*\n+", "\n", plain)
    return _normalize_space(plain)


def read_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9$%. ]+", " ", text)
    return [t for t in text.split() if t]


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


def rank_chunks(question: str, chunks: list[str], top_k: int) -> list[str]:
    q_tokens = set(_tokenize(question))
    scored: list[tuple[int, int, str]] = []
    for idx, chunk in enumerate(chunks):
        c_tokens = set(_tokenize(chunk))
        overlap = len(q_tokens & c_tokens)
        numeric_hint = 1 if re.search(r"\$|\b(?:million|billion|percent|%)\b|\d", chunk.lower()) else 0
        score = overlap * 10 + numeric_hint
        scored.append((score, -idx, chunk))
    scored.sort(reverse=True)
    return [it[2] for it in scored[: max(1, top_k)]]


def estimate_input_tokens(question: str, context_chunks: list[str], chars_per_token: float) -> int:
    # Approximate prompt scaffolding and JSON/system instructions overhead.
    overhead_chars = 1200
    total_chars = overhead_chars + len(question) + sum(len(c) for c in context_chunks)
    cpt = chars_per_token if chars_per_token > 0 else 4.0
    return max(1, int(total_chars / cpt))


def wait_for_tpm_budget(
    usage_window: deque[tuple[float, int]],
    *,
    estimated_tokens: int,
    max_tpm: int,
) -> None:
    if max_tpm <= 0:
        return

    while True:
        now = time.time()
        while usage_window and now - usage_window[0][0] >= 60.0:
            usage_window.popleft()

        used = sum(tokens for _, tokens in usage_window)
        if used + estimated_tokens <= max_tpm:
            return

        sleep_for = max(0.25, 60.0 - (now - usage_window[0][0])) if usage_window else 1.0
        print(
            f"  pacing: sleeping {sleep_for:.1f}s to stay within ~{max_tpm} input tokens/min "
            f"(used={used}, next~={estimated_tokens})",
            flush=True,
        )
        time.sleep(sleep_for)


def _extract_answer_from_text(raw_text: str) -> str:
    if not raw_text.strip():
        return ""
    candidate = raw_text.strip()

    # Prefer JSON answer if the model follows instructions.
    json_blob = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if json_blob:
        maybe = json_blob.group(0)
        try:
            obj = json.loads(maybe)
            if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
                return obj["answer"].strip()
        except json.JSONDecodeError:
            pass

    # Fallback: strip markdown code fences and return text.
    candidate = re.sub(r"^```(?:json)?", "", candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r"```$", "", candidate).strip()
    return candidate


def call_claude_messages(
    *,
    base_url: str,
    api_key: str,
    anthropic_version: str,
    model: str,
    question: str,
    context_chunks: list[str],
    temperature: float,
    max_output_tokens: int,
    timeout: float,
) -> str:
    context_blob = "\n\n".join([f"[chunk {i + 1}]\n{chunk}" for i, chunk in enumerate(context_chunks)])

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
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": max_output_tokens,
        "temperature": temperature,
    }

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": anthropic_version,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Anthropic request error: {exc}") from exc

    content = payload.get("content")
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            text_parts.append(item["text"])

    return _extract_answer_from_text("\n".join(text_parts).strip())


def _is_http_429_rate_limit(exc: Exception) -> bool:
    if not isinstance(exc, RuntimeError):
        return False
    text = str(exc).lower()
    return "http 429" in text or "rate_limit" in text or "rate limit" in text


def query_anthropic_models(
    *,
    base_url: str,
    api_key: str,
    anthropic_version: str,
    timeout: float,
) -> list[str]:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/models",
        method="GET",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": anthropic_version,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic model query HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Anthropic model query error: {exc}") from exc

    items = payload.get("data")
    if not isinstance(items, list):
        raise RuntimeError("Anthropic model query returned unexpected payload (missing data list)")

    models: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            models.append(item["id"].strip())
    return models


def _pick_model(preferred: str | None, available_models: list[str]) -> str:
    if preferred:
        return preferred
    if available_models:
        # Prefer Sonnet, then Opus, then first returned.
        for token in ("sonnet", "opus"):
            for name in available_models:
                if token in name.lower():
                    return name
        return available_models[0]
    return DEFAULT_MODEL


def main() -> int:
    args = build_arg_parser().parse_args()

    api_key = (args.api_key or "").strip()
    if not api_key and not args.no_interactive_api_key:
        # Prompt at startup so users can paste key directly in terminal.
        entered = getpass.getpass("Anthropic API key: ").strip()
        if entered:
            api_key = entered
    if not api_key:
        api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        api_key = _read_env_file_var(Path(".env"), args.api_key_env)
    if not api_key:
        print(
            f"ERROR: missing API key. Set {args.api_key_env} in env or .env.",
            file=sys.stderr,
        )
        return 2

    available_models: list[str] = []
    if not args.skip_model_query:
        try:
            available_models = query_anthropic_models(
                base_url=args.base_url,
                api_key=api_key,
                anthropic_version=args.anthropic_version,
                timeout=args.request_timeout,
            )
            print(f"[{_now_utc()}] Anthropic models: {available_models}")
        except Exception as exc:  # noqa: BLE001
            print(f"warning: could not query Anthropic models: {exc}", file=sys.stderr)

    model_name = _pick_model(args.model, available_models)
    if args.model and available_models and args.model not in available_models:
        print(
            "warning: requested model was not found in /v1/models; continuing anyway: "
            f"{args.model}",
            file=sys.stderr,
        )

    print(f"[{_now_utc()}] Using model={model_name}")

    benchmark_path = Path(args.benchmark_file)
    if not benchmark_path.exists():
        print(f"ERROR: benchmark file not found: {benchmark_path}", file=sys.stderr)
        return 2

    doc_path = Path(args.doc_file)
    if not doc_path.exists():
        print(f"ERROR: doc file not found: {doc_path}", file=sys.stderr)
        return 2

    print(f"[{_now_utc()}] Loading benchmark from {benchmark_path}")
    qas = load_benchmark(benchmark_path)
    total_qas = len(qas)
    if args.max_questions and args.max_questions > 0:
        qas = qas[: args.max_questions]

    print(f"[{_now_utc()}] Reading document text from {doc_path}")
    full_text = read_document_text(doc_path)
    chunks = chunk_text(full_text, args.chunk_chars, args.chunk_overlap)
    print(f"[{_now_utc()}] Prepared {len(chunks)} chunks for lexical retrieval")

    results: list[dict[str, Any]] = []
    failures = 0
    usage_window: deque[tuple[float, int]] = deque()

    for idx, qa in enumerate(qas, start=1):
        qid = str(qa.get("id", f"Q{idx:03d}"))
        group = str(qa.get("group", "unknown"))
        question = str(qa.get("question", "")).strip()
        gold = str(qa.get("answer", "")).strip()

        print(f"[{_now_utc()}] ({idx}/{len(qas)}) {qid} ...", flush=True)

        pred = ""
        try:
            selected = rank_chunks(question, chunks, args.top_k)

            est_tokens = estimate_input_tokens(question, selected, args.chars_per_token)
            wait_for_tpm_budget(
                usage_window,
                estimated_tokens=est_tokens,
                max_tpm=args.max_input_tokens_per_minute,
            )

            attempt = 0
            while True:
                attempt += 1
                try:
                    pred = call_claude_messages(
                        base_url=args.base_url,
                        api_key=api_key,
                        anthropic_version=args.anthropic_version,
                        model=model_name,
                        question=question,
                        context_chunks=selected,
                        temperature=args.temperature,
                        max_output_tokens=args.max_output_tokens,
                        timeout=args.request_timeout,
                    )
                    usage_window.append((time.time(), est_tokens))
                    break
                except Exception as exc:  # noqa: BLE001
                    if _is_http_429_rate_limit(exc) and attempt <= args.retry_429_max_attempts:
                        backoff = args.retry_429_wait_seconds * attempt
                        print(
                            f"  warning: rate-limited on {qid}, retry {attempt}/{args.retry_429_max_attempts} "
                            f"after {backoff:.1f}s",
                            file=sys.stderr,
                            flush=True,
                        )
                        time.sleep(backoff)
                        continue
                    raise

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

        results.append(
            {
                "id": qid,
                "group": group,
                "question": question,
                "asked_question": question,
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
            }
        )

        if args.sleep_between > 0:
            time.sleep(args.sleep_between)

    summary = _aggregate(results)
    summary["questions_total"] = total_qas
    summary["questions_run"] = len(results)
    summary["request_failures"] = failures
    summary["context_overflow_failures"] = 0

    by_group: dict[str, dict[str, Any]] = {}
    group_names = sorted({str(it.get("group", "unknown")) for it in results})
    for gname in group_names:
        items = [it for it in results if it.get("group") == gname]
        by_group[gname] = _aggregate(items)

    report = {
        "generated_at_utc": _now_utc(),
        "config": {
            "mode": "anthropic_direct_local_retrieval",
            "base_url": args.base_url,
            "model": model_name,
            "available_models": available_models,
            "benchmark_file": str(benchmark_path),
            "doc_file": str(doc_path),
            "max_questions": args.max_questions,
            "top_k": args.top_k,
            "chunk_chars": args.chunk_chars,
            "chunk_overlap": args.chunk_overlap,
            "sleep_between": args.sleep_between,
            "anthropic_version": args.anthropic_version,
            "max_output_tokens": args.max_output_tokens,
            "max_input_tokens_per_minute": args.max_input_tokens_per_minute,
            "chars_per_token": args.chars_per_token,
            "retry_429_max_attempts": args.retry_429_max_attempts,
            "retry_429_wait_seconds": args.retry_429_wait_seconds,
        },
        "summary": summary,
        "by_group": by_group,
        "thread_ids_used": [],
        "results": results,
    }

    out_json, out_md = write_outputs(Path(args.output_dir), args.run_name, report)

    print("\nBenchmark complete")
    print(
        f"  overall_correct: {summary['overall_correct_count']} / {summary['questions_run']} "
        f"({summary['overall_correct_rate']:.2%})"
    )
    print(
        f"  normalized_exact: {summary['normalized_exact_count']} / {summary['questions_run']} "
        f"({summary['normalized_exact_rate']:.2%})"
    )
    print(
        f"  number_match: {summary['number_match_count']} / {summary['questions_run']} "
        f"({summary['number_match_rate']:.2%})"
    )
    print(
        f"  unit_match: {summary['unit_match_count']} / {summary['questions_run']} "
        f"({summary['unit_match_rate']:.2%})"
    )
    print(f"  mean_token_f1: {summary['mean_token_f1']:.4f}")
    print(f"  request_failures: {summary['request_failures']}")
    print(f"  output_json: {out_json}")
    print(f"  output_md: {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
