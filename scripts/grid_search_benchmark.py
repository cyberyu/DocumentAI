#!/usr/bin/env python3
"""Exhaustive 2×2×2 grid-search benchmark over SurfSense retrieval parameters.

Imports benchmark infrastructure *directly* from run_surfsense_benchmark.py so
a single HTTP session is shared across all grid cells, avoiding subprocess
overhead and allowing fine-grained parameter control at the Python level.

Parameters swept:
  docpin   : mentioned_document_ids populated (True) vs empty (False)
  sanitize : _rewrite_question_for_retrieval applied (True) vs raw question (False)

  Web search is always OFF.  Full grid = 2 × 2 = 4 configurations.

Usage examples
--------------
# Run all 8 configs on the 10 representative questions:
    python3 scripts/grid_search_benchmark.py \
        --question-ids G1-001,G1-011,G1-021,G2-001,G2-011,G2-021,G2-031,G3-001,G3-011,G3-021

# Run all 8 configs on all 100 questions (takes ~16 h with 70 s delay):
    python3 scripts/grid_search_benchmark.py

# Regenerate HTML report only (no API calls):
    python3 scripts/grid_search_benchmark.py --report-only

# Skip configs whose result files already exist:
    python3 scripts/grid_search_benchmark.py --skip-existing \
        --question-ids G1-001,G1-011,G1-021,G2-001,G2-011,G2-021,G2-031,G3-001,G3-011,G3-021
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Import reusable infrastructure from the main benchmark runner.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from run_surfsense_benchmark import (  # noqa: E402
    SurfSenseClient,
    _aggregate,
    _as_bool,
    _build_force_final_question,
    _first_present,
    _looks_intermediate_answer,
    _now_utc,
    _read_json_config,
    _rewrite_question_for_retrieval,
    evaluate_answer,
    load_benchmark,
    resolve_document_ids,
    resolve_search_space_id,
    write_outputs,
)

# ---------------------------------------------------------------------------
# Grid definition — 2×2 combinations of docpin × sanitize.
# Web search is always OFF (disabled_tools = web_search,scrape_webpage).
# ---------------------------------------------------------------------------
GRID: list[dict[str, Any]] = []
for _docpin in (False, True):
    for _sanitize in (True, False):
        _key_parts = [
            "docpin" if _docpin else "nodocpin",
            "sanitize" if _sanitize else "nosanit",
        ]
        _label_parts = [
            "Docpin" if _docpin else "No-docpin",
            "Sanitize" if _sanitize else "No-sanitize",
        ]
        GRID.append(
            dict(
                key="grid_" + "_".join(_key_parts),
                label=" / ".join(_label_parts),
                docpin=_docpin,
                sanitize=_sanitize,
                web=False,
            )
        )

OUTPUT_DIR = Path("benchmark_results_MSFT_FY26Q1_qa")
DEFAULT_BENCH_FILE = "msft_fy26q1_qa_benchmark_100_sanitized.json"
REPORT_OUT = OUTPUT_DIR / "grid_search_report.html"


# ---------------------------------------------------------------------------
# Core per-question runner  (no subprocess — calls API directly)
# ---------------------------------------------------------------------------

def _run_question(
    *,
    client: SurfSenseClient,
    search_space_id: int,
    doc_ids: list[int],
    qa: dict[str, Any],
    cfg: dict[str, Any],
    run_name: str,
    delay: float,
    message_poll_timeout: float,
) -> dict[str, Any]:
    """Send one question to the API and return a result dict."""
    qid = str(qa.get("id", ""))
    group = str(qa.get("group", "unknown"))
    raw_question = str(qa.get("question", "")).strip()
    gold = str(qa.get("answer", "")).strip()

    asked_question = (
        _rewrite_question_for_retrieval(raw_question)
        if cfg["sanitize"]
        else raw_question
    )
    mentioned_ids = doc_ids if cfg["docpin"] else []

    # Disable all tools except the internal knowledge-base middleware (which is
    # not user-disableable).  This prevents the model from looping on tool calls
    # and keeps the benchmark as a pure RAG evaluation.
    _ALL_TOOLS = [
        "generate_podcast", "generate_video_presentation", "generate_report",
        "generate_resume", "generate_image", "scrape_webpage", "web_search",
        "search_surfsense_docs", "update_memory",
        "create_linear_issue", "update_linear_issue", "delete_linear_issue",
        "create_notion_page", "update_notion_page", "delete_notion_page",
        "create_google_drive_file", "delete_google_drive_file",
        "create_dropbox_file", "delete_dropbox_file",
        "create_onedrive_file", "delete_onedrive_file",
        "create_calendar_event", "update_calendar_event", "delete_calendar_event",
        "create_gmail_draft", "send_gmail_email", "trash_gmail_email", "update_gmail_draft",
        "create_jira_issue", "update_jira_issue", "delete_jira_issue",
        "create_confluence_page", "update_confluence_page", "delete_confluence_page",
    ]
    disabled_tools = _ALL_TOOLS if not cfg["web"] else [t for t in _ALL_TOOLS if t != "web_search"]

    thread_title = f"benchmark-{run_name}-{qid}"
    thread_id = client.create_thread(search_space_id=search_space_id, title=thread_title)

    def _ask(tid: int, question: str) -> str:
        return client.ask_new_chat(
            thread_id=tid,
            search_space_id=search_space_id,
            question=question,
            mentioned_document_ids=mentioned_ids,
            disabled_tools=disabled_tools,
            message_poll_timeout=message_poll_timeout,
            pre_request_delay_seconds=delay,
        )

    pred = _ask(thread_id, asked_question)

    # Retry on empty answer.
    if not pred:
        retry_tid = client.create_thread(
            search_space_id=search_space_id,
            title=f"{thread_title}-empty-retry",
        )
        pred = _ask(retry_tid, asked_question + " Final answer only.") or ""

    # Retry on intermediate / tool-status answer.
    elif _looks_intermediate_answer(pred):
        retry_tid = client.create_thread(
            search_space_id=search_space_id,
            title=f"{thread_title}-completion-retry",
        )
        pred = _ask(retry_tid, _build_force_final_question(asked_question)) or pred

    ev = evaluate_answer(gold, pred)
    return {
        "id": qid,
        "group": group,
        "question": raw_question,
        "asked_question": asked_question,
        "gold_answer": gold,
        "predicted_answer": pred,
        "metrics": {
            "cleaned_prediction": ev.cleaned_prediction,
            "answer_clean": ev.answer_clean,
            "semantic_intent_ok": ev.semantic_intent_ok,
            "strict_exact": ev.strict_exact,
            "normalized_exact": ev.normalized_exact,
            "contains_gold": ev.contains_gold,
            "number_match": ev.number_match,
            "unit_match": ev.unit_match,
            "numeric_precision": ev.numeric_precision,
            "numeric_recall": ev.numeric_recall,
            "numeric_f1": ev.numeric_f1,
            "primary_value_match": ev.primary_value_match,
            "token_f1": ev.token_f1,
            "strict_correct": ev.strict_correct,
            "lenient_correct": ev.lenient_correct,
            "overall_correct": ev.overall_correct,
        },
    }


def _run_config(
    *,
    client: SurfSenseClient,
    search_space_id: int,
    doc_ids: list[int],
    qas: list[dict[str, Any]],
    cfg: dict[str, Any],
    delay: float,
    message_poll_timeout: float,
) -> dict[str, Any]:
    """Run one grid-cell and return the full result payload (or load from disk)."""
    out_json = OUTPUT_DIR / f"{cfg['key']}.json"
    if out_json.exists():
        print(f"[{_now_utc()}] SKIP {cfg['key']} (cached: {out_json})", flush=True)
        return json.loads(out_json.read_text(encoding="utf-8"))

    print(f"\n{'='*72}", flush=True)
    print(f"[{_now_utc()}] CONFIG: {cfg['label']}", flush=True)
    print(f"  docpin={cfg['docpin']}  sanitize={cfg['sanitize']}  web={cfg['web']}", flush=True)
    print(f"{'='*72}", flush=True)

    results: list[dict[str, Any]] = []
    for idx, qa in enumerate(qas, 1):
        qid = qa.get("id", f"Q{idx:03d}")
        print(f"  [{_now_utc()}] ({idx}/{len(qas)}) {qid} ...", flush=True)
        try:
            row = _run_question(
                client=client,
                search_space_id=search_space_id,
                doc_ids=doc_ids,
                qa=qa,
                cfg=cfg,
                run_name=cfg["key"],
                delay=delay,
                message_poll_timeout=message_poll_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR: {exc}", flush=True)
            row = {
                "id": str(qid),
                "group": str(qa.get("group", "unknown")),
                "question": str(qa.get("question", "")),
                "asked_question": "",
                "gold_answer": str(qa.get("answer", "")),
                "predicted_answer": f"ERROR: {exc}",
                "metrics": {
                    "cleaned_prediction": "",
                    "answer_clean": False,
                    "semantic_intent_ok": False,
                    "strict_exact": False,
                    "normalized_exact": False,
                    "contains_gold": False,
                    "number_match": False,
                    "unit_match": False,
                    "numeric_precision": 0.0,
                    "numeric_recall": 0.0,
                    "numeric_f1": 0.0,
                    "primary_value_match": False,
                    "token_f1": 0.0,
                    "strict_correct": False,
                    "lenient_correct": False,
                    "overall_correct": False,
                },
            }
        results.append(row)
        correct = row["metrics"]["overall_correct"]
        pred_short = row["metrics"].get("cleaned_prediction", "")[:80]
        print(
            f"    {'✔' if correct else '✘'}  gold={row['gold_answer']!r}  pred={pred_short!r}",
            flush=True,
        )

    # Aggregate.
    by_group: dict[str, Any] = {}
    groups = sorted({r["group"] for r in results})
    for g in groups:
        grp_items = [r for r in results if r["group"] == g]
        by_group[g] = _aggregate(grp_items)

    summary = _aggregate(results)
    summary["questions_run"] = summary["run"]
    summary["questions_total"] = summary["run"]
    payload = {
        "config": cfg,
        "generated_at_utc": _now_utc(),
        "summary": summary,
        "by_group": by_group,
        "results": results,
    }

    # Persist JSON + MD via the existing write_outputs helper.
    write_outputs(OUTPUT_DIR, cfg["key"], payload)
    print(
        f"[{_now_utc()}] {cfg['key']} done — "
        f"{summary['overall_correct_count']}/{summary['run']} correct "
        f"({summary['overall_correct_rate']:.0%})",
        flush=True,
    )
    return payload


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def generate_report(payloads: list[dict[str, Any]]) -> None:
    """Write a side-by-side HTML comparison report for all grid cells."""
    if not payloads:
        print("No payloads to report.", flush=True)
        return

    # Collect all question IDs in stable order.
    all_ids: list[str] = []
    seen: set[str] = set()
    for p in payloads:
        for r in p.get("results", []):
            qid = r["id"]
            if qid not in seen:
                seen.add(qid)
                all_ids.append(qid)

    # Quick lookup: payload_key → {qid → result}
    idx_map: dict[str, dict[str, dict[str, Any]]] = {}
    for p in payloads:
        key = p["config"]["key"]
        idx_map[key] = {r["id"]: r for r in p.get("results", [])}

    def _badge(correct: bool | None) -> str:
        if correct is True:
            return '<span style="color:#0a7c0a;font-weight:700;font-size:1.1em;">✔</span>'
        if correct is False:
            return '<span style="color:#c0392b;font-weight:700;font-size:1.1em;">✘</span>'
        return '<span style="color:#999;">—</span>'

    def _pct(rate: float) -> str:
        return f"{rate:.0%}"

    header_cols = "".join(
        f'<th style="background:#2c3e50;color:#ecf0f1;padding:8px 12px;white-space:nowrap;">'
        f"{p['config']['label']}</th>"
        for p in payloads
    )

    summary_rows = ""
    for metric_key, label in [
        ("overall_correct_rate", "Overall Correct"),
        ("normalized_exact_rate", "Norm Exact"),
        ("number_match_rate", "Number Match"),
        ("unit_match_rate", "Unit Match"),
        ("mean_token_f1", "Mean Token F1"),
    ]:
        vals = []
        for p in payloads:
            v = p["summary"].get(metric_key, 0.0)
            vals.append(v)
        max_v = max(vals) if vals else 0.0
        cells = ""
        for v in vals:
            bold = "font-weight:700;" if abs(v - max_v) < 1e-9 and max_v > 0 else ""
            if metric_key == "mean_token_f1":
                cells += f'<td style="text-align:center;{bold}">{v:.4f}</td>'
            else:
                cells += f'<td style="text-align:center;{bold}">{_pct(v)}</td>'
        summary_rows += f"<tr><td><b>{label}</b></td>{cells}</tr>\n"

    # Count row.
    count_cells = "".join(
        f'<td style="text-align:center;">'
        f"{p['summary']['overall_correct_count']}/{p['summary']['run']}</td>"
        for p in payloads
    )
    summary_rows = f"<tr><td><b>Count</b></td>{count_cells}</tr>\n" + summary_rows

    question_rows = ""
    for qid in all_ids:
        gold = ""
        for p in payloads:
            r = idx_map[p["config"]["key"]].get(qid)
            if r:
                gold = r.get("gold_answer", "")
                break
        cells = ""
        for p in payloads:
            r = idx_map[p["config"]["key"]].get(qid)
            if r is None:
                cells += '<td style="text-align:center;color:#aaa;">—</td>'
                continue
            correct = r["metrics"].get("overall_correct")
            pred = r["metrics"].get("cleaned_prediction", "") or r.get("predicted_answer", "")
            pred_short = pred[:120] + ("…" if len(pred) > 120 else "")
            bg = "#eafaf1" if correct else "#fdecea"
            cells += (
                f'<td style="background:{bg};padding:4px 8px;font-size:0.85em;">'
                f'{_badge(correct)} {pred_short}</td>'
            )
        gold_short = gold[:60] + ("…" if len(gold) > 60 else "")
        question_rows += (
            f"<tr>"
            f'<td style="padding:4px 8px;white-space:nowrap;font-weight:600;">{qid}</td>'
            f'<td style="padding:4px 8px;color:#555;font-size:0.85em;">{gold_short}</td>'
            f"{cells}"
            f"</tr>\n"
        )

    n_cfg = len(payloads)
    col_w = max(140, 600 // n_cfg)
    table_style = f"border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:0.9em;"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Grid Search Benchmark Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; background: #f8f9fa; color: #212529; }}
h1 {{ font-size: 1.5em; margin-bottom: 4px; }}
h2 {{ font-size: 1.15em; margin-top: 24px; margin-bottom: 8px; color: #2c3e50; border-bottom: 2px solid #2c3e50; padding-bottom: 4px; }}
table {{ {table_style} }}
th, td {{ border: 1px solid #dee2e6; vertical-align: top; }}
th {{ text-align: center; }}
tr:nth-child(even) td {{ background: #f2f2f2; }}
.tag {{ display:inline-block; padding:2px 6px; border-radius:3px; font-size:0.75em; font-weight:700; margin:1px; }}
</style>
</head>
<body>
<h1>Grid Search Benchmark — 2×2 Parameter Sweep (Docpin × Sanitize)</h1>
<p style="color:#555;font-size:0.9em;">
Generated {_now_utc()} &nbsp;|&nbsp; {n_cfg} configs &nbsp;|&nbsp; {len(all_ids)} questions &nbsp;|&nbsp; web search always OFF
</p>

<h2>Configuration Key</h2>
<table style="width:auto;{table_style}">
<tr>
  <th style="background:#2c3e50;color:#ecf0f1;padding:8px;">Key</th>
  <th style="background:#2c3e50;color:#ecf0f1;padding:8px;">Label</th>
  <th style="background:#2c3e50;color:#ecf0f1;padding:8px;">Docpin</th>
  <th style="background:#2c3e50;color:#ecf0f1;padding:8px;">Sanitize</th>
</tr>
{''.join(
    f"<tr>"
    f"<td style='padding:6px 10px;font-family:monospace;font-size:0.85em;'>{p['config']['key']}</td>"
    f"<td style='padding:6px 10px;'>{p['config']['label']}</td>"
    f"<td style='text-align:center;'>{'✔' if p['config']['docpin'] else '✘'}</td>"
    f"<td style='text-align:center;'>{'✔' if p['config']['sanitize'] else '✘'}</td>"
    f"</tr>"
    for p in payloads
)}
</table>

<h2>Summary Metrics</h2>
<table style="{table_style}">
<tr>
  <th style="background:#2c3e50;color:#ecf0f1;padding:8px;">Metric</th>
  {header_cols}
</tr>
{summary_rows}
</table>

<h2>Per-Question Results</h2>
<table style="{table_style}">
<tr>
  <th style="background:#2c3e50;color:#ecf0f1;padding:8px;white-space:nowrap;">Q ID</th>
  <th style="background:#2c3e50;color:#ecf0f1;padding:8px;">Gold Answer</th>
  {header_cols}
</tr>
{question_rows}
</table>

</body>
</html>
"""

    REPORT_OUT.write_text(html, encoding="utf-8")
    print(f"[{_now_utc()}] Report written: {REPORT_OUT}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="2×2×2 grid-search benchmark over SurfSense retrieval parameters"
    )
    p.add_argument(
        "--config",
        default="benchmark_runner_config.json",
        help="Path to JSON config file (default: benchmark_runner_config.json)",
    )
    p.add_argument("--base-url", default=None)
    p.add_argument("--username", default=None)
    p.add_argument("--password", default=None)
    p.add_argument(
        "--benchmark-file",
        default=None,
        help=f"Path to benchmark JSON (default from config or {DEFAULT_BENCH_FILE})",
    )
    p.add_argument(
        "--question-ids",
        default=None,
        help="Comma-separated list of question IDs to run (e.g. G1-001,G2-001). "
             "If omitted, all questions in the benchmark file are used.",
    )
    p.add_argument(
        "--max-questions",
        type=int,
        default=0,
        help="If >0, run at most this many questions per config (applied after --question-ids filter).",
    )
    p.add_argument(
        "--search-space-name",
        default=None,
        help="Search space name (optional; falls back to config file).",
    )
    p.add_argument(
        "--document-title-contains",
        default=None,
        help="Document title fragment used to resolve docpin IDs (default: MSFT_FY26Q1_10Q).",
    )
    p.add_argument(
        "--delay-per-request",
        type=float,
        default=None,
        help="Seconds to wait before each API call (overrides config).",
    )
    p.add_argument(
        "--message-poll-timeout",
        type=float,
        default=300.0,
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip configs whose result JSON already exists.",
    )
    p.add_argument(
        "--report-only",
        action="store_true",
        help="Skip all API calls; just regenerate the HTML report from existing result files.",
    )
    p.add_argument(
        "--configs",
        default=None,
        help="Comma-separated list of config keys to run (e.g. grid_nodocpin_sanitize_noweb). "
             "If omitted, all 8 grid cells are run.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    config_path = Path(args.config) if args.config else None
    try:
        cfg_file = _read_json_config(config_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    base_url = args.base_url or _first_present(cfg_file, ["base_url", "BASE_URL"]) or "http://localhost:8929"
    username = args.username or _first_present(cfg_file, ["username", "USERNAME"]) or ""
    password = args.password or _first_present(cfg_file, ["password", "PASSWORD"]) or ""
    benchmark_file = (
        args.benchmark_file
        or _first_present(cfg_file, ["benchmark_file", "BENCHMARK_FILE"])
        or DEFAULT_BENCH_FILE
    )
    search_space_name = args.search_space_name or _first_present(
        cfg_file, ["search_space_name", "SEARCH_SPACE_NAME", "searchspace", "SEARCHSPACE"]
    )
    doc_title = args.document_title_contains or _first_present(
        cfg_file, ["document_title_contains", "DOCUMENT_TITLE_CONTAINS"]
    ) or "MSFT_FY26Q1_10Q"

    delay_raw = (
        args.delay_per_request
        if args.delay_per_request is not None
        else _first_present(cfg_file, ["delay_per_request", "DELAY_PER_REQUEST"])
    )
    delay = float(delay_raw) if delay_raw is not None else 0.0

    global OUTPUT_DIR  # noqa: PLW0603
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Select which grid cells to run.
    grid = GRID
    if args.configs:
        wanted = {k.strip() for k in args.configs.split(",")}
        grid = [c for c in GRID if c["key"] in wanted]
        if not grid:
            print(f"ERROR: no matching configs for --configs={args.configs!r}", file=sys.stderr)
            return 2

    if args.report_only:
        payloads = []
        for cfg in grid:
            out_json = OUTPUT_DIR / f"{cfg['key']}.json"
            if out_json.exists():
                payloads.append(json.loads(out_json.read_text(encoding="utf-8")))
            else:
                print(f"  Missing result file for {cfg['key']}, skipping.", flush=True)
        generate_report(payloads)
        return 0

    if not username or not password:
        print("ERROR: credentials required. Add USERNAME/PASSWORD to benchmark_runner_config.json", file=sys.stderr)
        return 2

    # Load benchmark questions.
    bench_path = Path(benchmark_file)
    if not bench_path.exists():
        print(f"ERROR: benchmark file not found: {bench_path}", file=sys.stderr)
        return 2

    all_qas = load_benchmark(bench_path)
    print(f"[{_now_utc()}] Loaded {len(all_qas)} questions from {bench_path}", flush=True)

    # Filter by explicit IDs if requested.
    if args.question_ids:
        wanted_ids = {qid.strip() for qid in args.question_ids.split(",")}
        qas = [q for q in all_qas if str(q.get("id", "")) in wanted_ids]
        print(f"[{_now_utc()}] Filtered to {len(qas)} questions matching --question-ids", flush=True)
    else:
        qas = all_qas

    if args.max_questions and args.max_questions > 0:
        qas = qas[: args.max_questions]
        print(f"[{_now_utc()}] Capped to {len(qas)} questions via --max-questions", flush=True)

    if not qas:
        print("ERROR: no questions selected — check --question-ids and benchmark file.", file=sys.stderr)
        return 2

    # Authenticate.
    client = SurfSenseClient(base_url=base_url, timeout=600.0)
    print(f"[{_now_utc()}] Logging in to {base_url} ...", flush=True)
    client.login(username, password)

    search_space_id = resolve_search_space_id(client, None, search_space_name)
    print(f"[{_now_utc()}] Using search_space_id={search_space_id}", flush=True)

    # Resolve docpin document IDs once (reused across all docpin=True configs).
    docpin_ids = resolve_document_ids(client, search_space_id, doc_title)
    if docpin_ids:
        print(f"[{_now_utc()}] Docpin document IDs: {docpin_ids}", flush=True)
    else:
        print(f"[{_now_utc()}] WARNING: no documents matched {doc_title!r} — docpin configs will run as no-docpin", flush=True)

    # Run grid.
    payloads: list[dict[str, Any]] = []
    for cfg in grid:
        if args.skip_existing:
            out_json = OUTPUT_DIR / f"{cfg['key']}.json"
            if out_json.exists():
                print(f"[{_now_utc()}] SKIP {cfg['key']} (--skip-existing)", flush=True)
                payloads.append(json.loads(out_json.read_text(encoding="utf-8")))
                continue

        payload = _run_config(
            client=client,
            search_space_id=search_space_id,
            doc_ids=docpin_ids,
            qas=qas,
            cfg=cfg,
            delay=delay,
            message_poll_timeout=args.message_poll_timeout,
        )
        payloads.append(payload)
        # Small pause between configs to let the backend settle.
        time.sleep(2.0)

    generate_report(payloads)

    # Print final summary table.
    print(f"\n{'='*72}", flush=True)
    print("GRID SEARCH SUMMARY", flush=True)
    print(f"{'='*72}", flush=True)
    col_w = 36
    print(f"{'Config':<{col_w}} {'Correct':>8} {'Rate':>8} {'NumMatch':>10} {'F1':>8}", flush=True)
    print("-" * (col_w + 40), flush=True)
    for p in payloads:
        s = p["summary"]
        print(
            f"{p['config']['label']:<{col_w}} "
            f"{s['overall_correct_count']:>4}/{s['run']:<4} "
            f"{s['overall_correct_rate']:>7.1%} "
            f"{s['number_match_rate']:>9.1%} "
            f"{s['mean_token_f1']:>8.4f}",
            flush=True,
        )
    print(flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
