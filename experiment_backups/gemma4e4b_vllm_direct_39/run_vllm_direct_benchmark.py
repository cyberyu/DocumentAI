#!/usr/bin/env python3
"""Run benchmark QA by calling a local vLLM model directly over local document text.

This bypasses SurfSense chat orchestration and performs local retrieval + extraction:
1) Load benchmark qa_pairs JSON
2) Read local document (.docx/.md/.txt)
3) Rank text chunks for each question using simple lexical overlap
4) Ask vLLM OpenAI-compatible API for a single value-with-unit answer
5) Evaluate and write JSON/Markdown reports compatible with existing artifacts
"""

from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description="Run direct vLLM benchmark over local document")
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
        help="vLLM served model id; if omitted, auto-select first model from /v1/models",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=10,
        help="If >0, run only the first N questions",
    )
    parser.add_argument(
        "--run-name",
        default="vllm_direct_gemma4_check10",
        help="Run name prefix for output artifacts",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL for local vLLM OpenAI-compatible server",
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
        "--api-key-env",
        default="VLLM_API_KEY",
        help="Optional environment variable for Bearer token if vLLM server requires auth",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=120.0,
        help="HTTP timeout seconds for OpenAI request",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Optional sampling temperature; omitted by default for deterministic extraction",
    )
    return parser


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path, "r") as zf:
        with zf.open("word/document.xml") as fp:
            xml_data = fp.read().decode("utf-8", errors="replace")

    # Keep paragraph boundaries before removing tags.
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
        # Secondary signal: keep chunks that contain key numerics/signs likely used in answers.
        numeric_hint = 1 if re.search(r"\$|\b(?:million|billion|percent|%)\b|\d", chunk.lower()) else 0
        score = overlap * 10 + numeric_hint
        scored.append((score, -idx, chunk))
    scored.sort(reverse=True)
    selected = [it[2] for it in scored[: max(1, top_k)]]
    return selected


def _extract_output_text(payload: dict[str, Any]) -> str:
    # Responses API often includes output_text in nested content blocks.
    pieces: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key in ("output_text", "text"):
                val = obj.get(key)
                if isinstance(val, str):
                    pieces.append(val)
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return "\n".join([p.strip() for p in pieces if p and p.strip()]).strip()


def call_vllm_chat_completions(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    question: str,
    context_chunks: list[str],
    temperature: float | None,
    timeout: float,
) -> str:
    context_blob = "\n\n".join(
        [f"[chunk {i + 1}]\n{chunk}" for i, chunk in enumerate(context_chunks)]
    )

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
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    }
    if temperature is not None:
        body["temperature"] = temperature

    data = json.dumps(body).encode("utf-8")
    base = base_url.rstrip("/")
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"vLLM HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"vLLM request error: {exc}") from exc

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    raw_text = message.get("content") if isinstance(message, dict) else ""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return ""
    raw_text = raw_text.strip()

    # Try strict JSON parse first.
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

    # Fallback: best effort raw text.
    return candidate.strip()


def query_vllm_models(base_url: str, api_key: str | None, timeout: float) -> list[str]:
    base = base_url.rstrip("/")
    req = urllib.request.Request(
        f"{base}/v1/models",
        method="GET",
        headers={"Content-Type": "application/json"},
    )
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"vLLM model query HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"vLLM model query error: {exc}") from exc

    items = payload.get("data")
    if not isinstance(items, list):
        raise RuntimeError("vLLM model query returned unexpected payload (missing data list)")

    models: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            models.append(item["id"].strip())
    if not models:
        raise RuntimeError("No models returned by vLLM /v1/models")
    return models


def main() -> int:
    args = build_arg_parser().parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        api_key = _read_env_file_var(Path(".env"), args.api_key_env)
    if not api_key:
        # Local vLLM often runs without auth; keep empty token in that case.
        api_key = ""

    try:
        available_models = query_vllm_models(
            base_url=args.base_url,
            api_key=api_key or None,
            timeout=args.request_timeout,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to query vLLM models from {args.base_url}/v1/models: {exc}", file=sys.stderr)
        return 2

    if args.model:
        if args.model not in available_models:
            print(
                "ERROR: requested model not found in vLLM model list: "
                f"{args.model}. Available: {', '.join(available_models)}",
                file=sys.stderr,
            )
            return 2
        model_name = args.model
    else:
        model_name = available_models[0]

    print(f"[{_now_utc()}] vLLM models: {available_models}")
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

    for idx, qa in enumerate(qas, start=1):
        qid = str(qa.get("id", f"Q{idx:03d}"))
        group = str(qa.get("group", "unknown"))
        question = str(qa.get("question", "")).strip()
        gold = str(qa.get("answer", "")).strip()

        print(f"[{_now_utc()}] ({idx}/{len(qas)}) {qid} ...", flush=True)

        pred = ""
        try:
            selected = rank_chunks(question, chunks, args.top_k)
            pred = call_vllm_chat_completions(
                base_url=args.base_url,
                api_key=api_key or None,
                model=model_name,
                question=question,
                context_chunks=selected,
                temperature=args.temperature,
                timeout=args.request_timeout,
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
            "mode": "vllm_direct_local_retrieval",
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
