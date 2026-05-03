#!/usr/bin/env python3
"""Run benchmark QA by calling DeepSeek API directly over local document text.

Mirrors run_openai_direct_benchmark.py but uses DeepSeek's chat/completions endpoint.
1) Load benchmark qa_pairs JSON
2) Read local document (.docx/.md/.txt)
3) Rank text chunks for each question using simple lexical overlap
4) Ask DeepSeek chat/completions for a single value-with-unit answer
5) Evaluate and write JSON/Markdown reports compatible with existing artifacts
"""

from __future__ import annotations

import argparse
import concurrent.futures
import getpass
import html
import json
import os
import re
import sys
import threading
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
        value = raw[len(prefix):].strip()
        if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
            value = value[1:-1]
        return value.strip()
    return ""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run direct DeepSeek benchmark over local document")
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
        help="DeepSeek API base URL (default: https://api.deepseek.com)",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=10,
        help="If >0, run only the first N questions",
    )
    parser.add_argument(
        "--start-question",
        type=int,
        default=1,
        help="1-based benchmark question index to start from (default: 1)",
    )
    parser.add_argument(
        "--run-name",
        default="deepseek_direct_v4flash_check10",
        help="Run name prefix for output artifacts",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results_MSFT_FY26Q1_qa",
        help="Directory for JSON/MD reports",
    )
    parser.add_argument(
        "--merge-from-json",
        default=None,
        help="Optional prior run JSON to backfill/replace by question id",
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
        default="DEEPSEEK_API_KEY",
        help="Environment variable containing DeepSeek API key",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=120.0,
        help="HTTP timeout seconds for DeepSeek request",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Optional sampling temperature",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel threads for API calls (default: 1 = sequential)",
    )
    parser.add_argument(
        "--thinking",
        default="true",
        help="Enable DeepSeek thinking mode: {\"type\": \"enabled\"} (default: true)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="high",
        help="DeepSeek reasoning_effort: low|medium|high (default: high). Empty string to omit.",
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
    selected = [it[2] for it in scored[:max(1, top_k)]]
    return selected


def call_deepseek_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    question: str,
    context_chunks: list[str],
    temperature: float | None,
    timeout: float,
    thinking_enabled: bool = True,
    reasoning_effort: str = "high",
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
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if thinking_enabled:
        body["thinking"] = {"type": "enabled"}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort

    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek request error: {exc}") from exc

    # Extract content from standard chat completions response.
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


def _merge_results_by_id(
    benchmark_qas: list[dict[str, Any]],
    existing_results: list[dict[str, Any]],
    new_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in existing_results:
        qid = str(item.get("id", "")).strip()
        if qid:
            by_id[qid] = item
    for item in new_results:
        qid = str(item.get("id", "")).strip()
        if qid:
            by_id[qid] = item

    merged: list[dict[str, Any]] = []
    for qa in benchmark_qas:
        qid = str(qa.get("id", "")).strip()
        if qid in by_id:
            merged.append(by_id[qid])
    return merged


def _count_failures_from_results(items: list[dict[str, Any]]) -> int:
    failures = 0
    for item in items:
        pred = item.get("predicted_answer")
        if not isinstance(pred, str) or not pred.strip():
            failures += 1
    return failures


def main() -> int:
    args = build_arg_parser().parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        api_key = _read_env_file_var(Path(".env"), args.api_key_env)
    if not api_key:
        api_key = getpass.getpass("Enter your DeepSeek API key: ").strip()
    if not api_key:
        print(f"ERROR: missing API key in env var {args.api_key_env}", file=sys.stderr)
        return 2

    benchmark_path = Path(args.benchmark_file)
    if not benchmark_path.exists():
        print(f"ERROR: benchmark file not found: {benchmark_path}", file=sys.stderr)
        return 2

    doc_path = Path(args.doc_file)
    if not doc_path.exists():
        print(f"ERROR: doc file not found: {doc_path}", file=sys.stderr)
        return 2

    print(f"[{_now_utc()}] Loading benchmark from {benchmark_path}")
    qas_all = load_benchmark(benchmark_path)
    total_qas = len(qas_all)
    if args.start_question < 1:
        print("ERROR: --start-question must be >= 1", file=sys.stderr)
        return 2
    start_idx = args.start_question - 1
    if start_idx >= total_qas:
        print(
            f"ERROR: --start-question {args.start_question} exceeds total questions {total_qas}",
            file=sys.stderr,
        )
        return 2

    qas = qas_all[start_idx:]
    if args.max_questions and args.max_questions > 0:
        qas = qas[:args.max_questions]

    print(f"[{_now_utc()}] Reading document text from {doc_path}")
    full_text = read_document_text(doc_path)
    chunks = chunk_text(full_text, args.chunk_chars, args.chunk_overlap)
    thinking_enabled = args.thinking.strip().lower() in {"1", "true", "yes", "y", "on"}
    reasoning_effort = args.reasoning_effort.strip()

    print(f"[{_now_utc()}] Prepared {len(chunks)} chunks for lexical retrieval")
    print(f"[{_now_utc()}] Model: {args.model} @ {args.deepseek_url}  workers={args.workers}")
    print(f"[{_now_utc()}] thinking={thinking_enabled}  reasoning_effort={reasoning_effort or '(omitted)'}")

    _print_lock = threading.Lock()

    def _run_one(indexed_qa: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        idx, qa = indexed_qa
        global_idx = start_idx + idx
        qid = str(qa.get("id", f"Q{global_idx:03d}"))
        group = str(qa.get("group", "unknown"))
        question = str(qa.get("question", "")).strip()
        gold = str(qa.get("answer", "")).strip()

        with _print_lock:
            print(f"[{_now_utc()}] ({global_idx}/{total_qas}) {qid} ...", flush=True)

        pred = ""
        failed = False
        try:
            selected = rank_chunks(question, chunks, args.top_k)
            pred = call_deepseek_chat(
                api_key=api_key,
                base_url=args.deepseek_url,
                model=args.model,
                question=question,
                context_chunks=selected,
                temperature=args.temperature,
                timeout=args.request_timeout,
                thinking_enabled=thinking_enabled,
                reasoning_effort=reasoning_effort,
            )
            if not pred:
                failed = True
        except Exception as exc:  # noqa: BLE001
            failed = True
            pred = ""
            with _print_lock:
                print(f"  warning: request failed for {qid}: {exc}", file=sys.stderr)

        metrics = evaluate_answer(gold=gold, pred=pred)
        pred_preview = metrics.cleaned_prediction.replace("\n", " ").strip()
        if len(pred_preview) > 140:
            pred_preview = pred_preview[:137] + "..."

        with _print_lock:
            print(
                f"  {qid}: "
                f"strict={'Y' if metrics.strict_correct else 'N'} "
                f"lenient={'Y' if metrics.lenient_correct else 'N'} "
                f"num={'Y' if metrics.number_match else 'N'} "
                f"unit={'Y' if metrics.unit_match else 'N'} "
                f"num_f1={metrics.numeric_f1:.3f} "
                f"pred={pred_preview!r}",
                flush=True,
            )
            print(f"    expected: {gold}", flush=True)

        return {
            "_order": global_idx,
            "_failed": failed,
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

    workers = max(1, args.workers)
    indexed = list(enumerate(qas, start=1))
    raw_results: list[dict[str, Any]]
    if workers == 1:
        raw_results = [_run_one(item) for item in indexed]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            raw_results = list(pool.map(_run_one, indexed))

    # Restore benchmark order (thread pool may complete out of order).
    raw_results.sort(key=lambda r: r["_order"])
    failures = sum(1 for r in raw_results if r.pop("_failed"))
    for r in raw_results:
        r.pop("_order", None)
    results = raw_results

    final_results = results
    if args.merge_from_json:
        merge_path = Path(args.merge_from_json)
        if not merge_path.exists():
            print(f"ERROR: merge JSON not found: {merge_path}", file=sys.stderr)
            return 2
        try:
            existing_payload = json.loads(merge_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid merge JSON {merge_path}: {exc}", file=sys.stderr)
            return 2
        existing_results = existing_payload.get("results")
        if not isinstance(existing_results, list):
            print(f"ERROR: merge JSON missing results list: {merge_path}", file=sys.stderr)
            return 2
        final_results = _merge_results_by_id(qas_all, existing_results, results)
        print(
            f"[{_now_utc()}] Backfilled {len(results)} rerun results into {merge_path} -> merged total {len(final_results)}",
            flush=True,
        )

    summary = _aggregate(final_results)
    summary["questions_total"] = total_qas
    summary["questions_run"] = len(final_results)
    summary["request_failures"] = _count_failures_from_results(final_results)
    summary["context_overflow_failures"] = 0

    by_group: dict[str, dict[str, Any]] = {}
    group_names = sorted({str(it.get("group", "unknown")) for it in final_results})
    for gname in group_names:
        items = [it for it in final_results if it.get("group") == gname]
        by_group[gname] = _aggregate(items)

    report = {
        "generated_at_utc": _now_utc(),
        "config": {
            "mode": "deepseek_direct_local_retrieval",
            "model": args.model,
            "deepseek_url": args.deepseek_url,
            "benchmark_file": str(benchmark_path),
            "doc_file": str(doc_path),
            "top_k": args.top_k,
            "chunk_chars": args.chunk_chars,
            "chunk_overlap": args.chunk_overlap,
            "workers": workers,
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort or None,
        },
        "summary": summary,
        "by_group": by_group,
        "results": final_results,
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{args.run_name}.json"
    md_path = out_dir / f"{args.run_name}.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[{_now_utc()}] Wrote JSON report: {json_path}", flush=True)

    # Markdown summary
    lines: list[str] = [
        f"# Benchmark Run: {args.run_name}",
        "",
        f"**Model:** {args.model}  ",
        f"**API:** {args.deepseek_url}  ",
        f"**Document:** {doc_path}  ",
        f"**Benchmark:** {benchmark_path}  ",
        f"**Generated:** {_now_utc()}  ",
        "",
        "## Overall Summary",
        "",
    ]

    def _fmt_summary(s: dict[str, Any], label: str) -> list[str]:
        total = s.get("total", 0)
        correct = s.get("overall_correct", 0)
        pct = (correct / total * 100) if total else 0.0
        num_match = s.get("number_match", 0)
        num_pct = (num_match / total * 100) if total else 0.0
        unit_match = s.get("unit_match", 0)
        unit_pct = (unit_match / total * 100) if total else 0.0
        mean_f1 = s.get("mean_token_f1", 0.0)
        return [
            f"### {label}",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Questions | {total} |",
            f"| Overall Correct | {correct} / {total} ({pct:.1f}%) |",
            f"| Number Match | {num_match} / {total} ({num_pct:.1f}%) |",
            f"| Unit Match | {unit_match} / {total} ({unit_pct:.1f}%) |",
            f"| Mean Token F1 | {mean_f1:.4f} |",
            "",
        ]

    lines.extend(_fmt_summary(summary, "All Groups"))
    for gname in group_names:
        lines.extend(_fmt_summary(by_group[gname], f"Group {gname}"))

    lines += [
        "## Per-Question Results",
        "",
        "| # | ID | Group | Correct | NumMatch | Pred | Gold |",
        "|---|-----|-------|---------|----------|------|------|",
    ]
    for i, item in enumerate(final_results, start=1):
        m = item.get("metrics", {})
        correct = "Y" if m.get("overall_correct") else "N"
        num_match = "Y" if m.get("number_match") else "N"
        pred = str(item.get("predicted_answer", "")).replace("|", "\\|")[:80]
        gold = str(item.get("gold_answer", "")).replace("|", "\\|")[:60]
        lines.append(f"| {i} | {item.get('id','')} | {item.get('group','')} | {correct} | {num_match} | {pred} | {gold} |")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[{_now_utc()}] Wrote Markdown report: {md_path}", flush=True)

    # Final summary to stdout
    total = summary.get("total", 0)
    correct = summary.get("overall_correct", 0)
    num_match = summary.get("number_match", 0)
    unit_match = summary.get("unit_match", 0)
    pct = (correct / total * 100) if total else 0.0
    print(
        f"\n=== FINAL: {correct}/{total} correct ({pct:.1f}%) | "
        f"number_match {num_match}/{total} | unit_match {unit_match}/{total} | "
        f"request_failures {summary.get('request_failures', 0)} ===",
        flush=True,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
