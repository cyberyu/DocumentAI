#!/usr/bin/env python3
"""Exhaustive 4-config benchmark sweep on 10 representative questions.

Runs four configurations of the SurfSense pipeline against the same 10
questions and produces a side-by-side HTML comparison report.

Usage:
    python3 scripts/run_sweep_benchmark.py [--skip-runs]

    --skip-runs   Skip running the benchmark; only regenerate the HTML
                  report from already-saved result files.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# ── 4 sweep configurations ──────────────────────────────────────────────────
CONFIGS = [
    dict(
        key="sweep_A_nodocpin_sanitize_noweb",
        label="A: No-docpin / Sanitize ON / Web OFF",
        docpin=False,
        sanitize=True,
        web=False,
        badge_color="#155724",
        badge_bg="#C3E6CB",
        description=(
            "Baseline — no mentioned_document_ids, question rewritten for "
            "retrieval, web search disabled.  Planner runs in recall mode: "
            "broad RRF search, matched_chunk_ids set, LLM gets relevance cues."
        ),
    ),
    dict(
        key="sweep_B_docpin_sanitize_noweb",
        label="B: Docpin / Sanitize ON / Web OFF",
        docpin=True,
        sanitize=True,
        web=False,
        badge_color="#721c24",
        badge_bg="#F5C6CB",
        description=(
            "Docpin — mentioned_document_ids set.  fetch_mentioned_documents "
            "runs first (all chunks, score=1.0, matched_chunk_ids=[]).  "
            "Same doc is then deduped out of search results, so LLM gets no "
            "relevance markers even if RRF finds the doc."
        ),
    ),
    dict(
        key="sweep_C_nodocpin_nosanit_noweb",
        label="C: No-docpin / Sanitize OFF / Web OFF",
        docpin=False,
        sanitize=False,
        web=False,
        badge_color="#004085",
        badge_bg="#CCE5FF",
        description=(
            "Raw question text — sanitize_questions=False.  The planner "
            "receives the original quoted-sentence question.  Tests whether "
            "the sanitizer's extra context prefix actually helps retrieval."
        ),
    ),
    dict(
        key="sweep_D_nodocpin_sanitize_web",
        label="D: No-docpin / Sanitize ON / Web ON",
        docpin=False,
        sanitize=True,
        web=True,
        badge_color="#856404",
        badge_bg="#FFF3CD",
        description=(
            "Web search enabled — disabled_tools excludes only scrape_webpage. "
            "Tests whether web search helps (unlikely for local 10-Q data) or "
            "introduces noise that hurts precision."
        ),
    ),
]

OUTPUT_DIR = Path("benchmark_results_MSFT_FY26Q1_qa")
BENCH_FILE = OUTPUT_DIR / "sweep10_questions.json"
CONFIG_FILE = Path("benchmark_runner_config.json")
RUNNER     = Path("scripts/run_surfsense_benchmark.py")
REPORT_OUT = OUTPUT_DIR / "sweep_comparison_report.html"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_config(cfg: dict) -> Path:
    """Run the benchmark runner for one config; returns the result JSON path."""
    out_json = OUTPUT_DIR / f"{cfg['key']}.json"

    if out_json.exists():
        print(f"[{_now()}] SKIP {cfg['key']} (already exists: {out_json})")
        return out_json

    print(f"\n{'='*70}")
    print(f"[{_now()}] Running config: {cfg['label']}")
    print(f"{'='*70}")

    base_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    username = base_cfg.get("USERNAME", "")
    password = base_cfg.get("PASSWORD", "")
    base_url = base_cfg.get("BASE_URL", "http://localhost:8929")
    delay    = str(base_cfg.get("DELAY_PER_REQUEST", 70))

    cmd = [
        sys.executable,
        str(RUNNER),
        "--base-url",        base_url,
        "--username",        username,
        "--password",        password,
        "--benchmark-file",  str(BENCH_FILE),
        "--search-space-name", str(base_cfg.get("SEARCHSPACE", "My Search Space")),
        "--output-dir",      str(OUTPUT_DIR),
        "--run-name",        cfg["key"],
        "--delay-per-request", delay,
        "--sanitize-questions", "true" if cfg["sanitize"] else "false",
    ]

    if cfg["docpin"]:
        cmd += ["--document-title-contains", "MSFT_FY26Q1_10Q"]

    if cfg["web"]:
        cmd += ["--disabled-tools", "scrape_webpage"]
    else:
        cmd += ["--disabled-tools", "web_search,scrape_webpage"]

    print(f"  CMD: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"[{_now()}] WARNING: runner exited with code {result.returncode} for {cfg['key']}", flush=True)

    return out_json


def _load_results(json_path: Path) -> dict:
    if not json_path.exists():
        return {}
    return json.loads(json_path.read_text(encoding="utf-8"))


def _metric_badge(val: bool | None) -> str:
    if val is True:
        return '<span style="color:#155724;font-weight:700;">✔</span>'
    if val is False:
        return '<span style="color:#721c24;font-weight:700;">✘</span>'
    return '<span style="color:#888;">—</span>'


def _pct(n: int, d: int) -> str:
    if d == 0:
        return "—"
    return f"{100*n//d}%"


def generate_report(configs: list[dict]) -> None:
    """Load all result JSONs and write the HTML comparison report."""
    all_data: dict[str, dict] = {}
    for cfg in configs:
        path = OUTPUT_DIR / f"{cfg['key']}.json"
        all_data[cfg["key"]] = _load_results(path)

    # Collect all question IDs in order
    question_ids: list[str] = []
    for cfg in configs:
        d = all_data.get(cfg["key"], {})
        for r in d.get("results", []):
            if r["id"] not in question_ids:
                question_ids.append(r["id"])

    # Build per-question result lookup: key -> id -> result dict
    by_config_id: dict[str, dict[str, dict]] = {}
    for cfg in configs:
        by_config_id[cfg["key"]] = {}
        for r in all_data.get(cfg["key"], {}).get("results", []):
            by_config_id[cfg["key"]][r["id"]] = r

    # ── Summary bar ──────────────────────────────────────────────────────────
    summary_rows = ""
    for cfg in configs:
        d = all_data.get(cfg["key"], {})
        sm = d.get("summary", {})
        n  = sm.get("questions_run", 0)
        ok = sm.get("overall_correct_count", 0)
        nm = sm.get("number_match_count", 0)
        f1 = sm.get("mean_token_f1", 0.0)
        summary_rows += f"""
        <tr>
          <td><span class="badge" style="background:{cfg['badge_bg']};color:{cfg['badge_color']}">{cfg['label']}</span></td>
          <td style="text-align:center">{ok}&nbsp;/&nbsp;{n}</td>
          <td style="text-align:center;font-weight:700">{_pct(ok,n)}</td>
          <td style="text-align:center">{nm}&nbsp;/&nbsp;{n}</td>
          <td style="text-align:center">{_pct(nm,n)}</td>
          <td style="text-align:center">{f1:.3f}</td>
        </tr>"""

    # ── Per-question detail ───────────────────────────────────────────────────
    detail_rows = ""
    qas = json.loads(BENCH_FILE.read_text(encoding="utf-8"))["qa_pairs"]
    qa_map = {q["id"]: q for q in qas}

    for qid in question_ids:
        qa = qa_map.get(qid, {})
        group = qa.get("group", "?")
        gold  = qa.get("answer", "?")
        q_text = qa.get("question", "")[:90]

        # header row
        detail_rows += f"""
        <tr style="background:#E8EDF5">
          <td colspan="{2 + len(configs)}" style="padding:10px 14px;font-size:15px">
            <strong>{qid}</strong>&nbsp;
            <em style="color:#555">[{group}]</em>&nbsp;&nbsp;
            {q_text}…<br>
            <span style="color:#155724;font-size:13px">&#9654; Gold: <strong>{gold}</strong></span>
          </td>
        </tr>"""

        # overall correct row
        detail_rows += "<tr><td style='padding-left:18px;font-size:13px;color:#555'>Overall correct</td><td></td>"
        for cfg in configs:
            r = by_config_id[cfg["key"]].get(qid, {})
            m = r.get("metrics", {})
            detail_rows += f"<td style='text-align:center'>{_metric_badge(m.get('overall_correct'))}</td>"
        detail_rows += "</tr>"

        # number match row
        detail_rows += "<tr><td style='padding-left:18px;font-size:13px;color:#555'>Number match</td><td></td>"
        for cfg in configs:
            r = by_config_id[cfg["key"]].get(qid, {})
            m = r.get("metrics", {})
            detail_rows += f"<td style='text-align:center'>{_metric_badge(m.get('number_match'))}</td>"
        detail_rows += "</tr>"

        # predicted answers row
        detail_rows += "<tr><td style='padding-left:18px;font-size:13px;color:#555;vertical-align:top'>Prediction</td><td></td>"
        for cfg in configs:
            r = by_config_id[cfg["key"]].get(qid, {})
            pred = r.get("metrics", {}).get("cleaned_prediction") or r.get("predicted_answer", "—")
            if len(pred) > 80:
                pred = pred[:77] + "…"
            ok_flag = r.get("metrics", {}).get("overall_correct", None)
            bg = "#C3E6CB" if ok_flag else ("#F5C6CB" if ok_flag is False else "#fff")
            detail_rows += f"<td style='font-size:12px;background:{bg};padding:4px 6px'>{pred}</td>"
        detail_rows += "</tr>"

    # ── Config descriptions ──────────────────────────────────────────────────
    config_desc_cols = ""
    for cfg in configs:
        config_desc_cols += f"""
          <td style="vertical-align:top;padding:12px;width:25%">
            <div class="badge" style="background:{cfg['badge_bg']};color:{cfg['badge_color']};margin-bottom:6px">{cfg['label']}</div>
            <div style="font-size:13px;color:#333;line-height:1.5">{cfg['description']}</div>
          </td>"""

    config_header_cols = "".join(
        f'<th style="background:{cfg["badge_bg"]};color:{cfg["badge_color"]};font-size:13px;min-width:120px">{cfg["label"]}</th>'
        for cfg in configs
    )

    generated = _now()
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SurfSense Parameter Sweep — 10Q Benchmark</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin:0; padding:0; }}
body {{
  font-family: 'Segoe UI', Arial, sans-serif;
  background: #F0F4F8;
  padding: 32px 24px 60px;
  color: #111;
}}
h1 {{ font-size:26px; font-weight:800; color:#1a1a2e; margin-bottom:6px; text-align:center; }}
h2 {{ font-size:15px; font-weight:400; font-style:italic; color:#666; text-align:center; margin-bottom:28px; }}
h3 {{ font-size:18px; font-weight:700; color:#1a1a2e; margin:28px 0 10px; }}
.badge {{
  display:inline-block; padding:3px 10px; border-radius:6px;
  font-size:13px; font-weight:700;
}}
table {{ border-collapse:collapse; width:100%; max-width:1100px; margin:0 auto; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,.08); }}
th {{ background:#1a1a2e; color:#fff; padding:10px 14px; text-align:left; font-size:14px; }}
td {{ padding:7px 12px; border-bottom:1px solid #e9ecef; font-size:14px; vertical-align:middle; }}
tr:hover td {{ background:#f8f9fa; }}
.section {{ max-width:1100px; margin:0 auto; }}
</style>
</head>
<body>

<h1>SurfSense Parameter Sweep</h1>
<h2>10 representative questions × 4 pipeline configurations &mdash; Gemma E4B via vLLM</h2>
<p style="text-align:center;font-size:13px;color:#888;margin-bottom:24px">Generated: {generated}</p>

<!-- CONFIGURATION DESCRIPTIONS -->
<div class="section">
  <h3>Configurations Tested</h3>
  <table>
    <tr>{config_desc_cols}</tr>
  </table>
</div>

<!-- SUMMARY TABLE -->
<div class="section">
  <h3>Summary Results</h3>
  <table>
    <thead>
      <tr>
        <th>Config</th>
        <th style="text-align:center">Correct</th>
        <th style="text-align:center">Correct&nbsp;%</th>
        <th style="text-align:center">Number Match</th>
        <th style="text-align:center">Num Match&nbsp;%</th>
        <th style="text-align:center">Mean&nbsp;F1</th>
      </tr>
    </thead>
    <tbody>{summary_rows}</tbody>
  </table>
</div>

<!-- PER-QUESTION BREAKDOWN -->
<div class="section">
  <h3>Per-Question Breakdown</h3>
  <table>
    <thead>
      <tr>
        <th style="width:200px">Question / Metric</th>
        <th style="width:40px"></th>
        {config_header_cols}
      </tr>
    </thead>
    <tbody>
      {detail_rows}
    </tbody>
  </table>
</div>

</body>
</html>"""

    REPORT_OUT.write_text(html, encoding="utf-8")
    print(f"\n[{_now()}] Report written to: {REPORT_OUT}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-runs", action="store_true", help="Skip running; only regenerate HTML report")
    args = parser.parse_args()

    if not BENCH_FILE.exists():
        print(f"ERROR: benchmark file not found: {BENCH_FILE}", file=sys.stderr)
        return 2

    if not args.skip_runs:
        for cfg in CONFIGS:
            _run_config(cfg)

    print(f"\n[{_now()}] Generating comparison report ...")
    generate_report(CONFIGS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
