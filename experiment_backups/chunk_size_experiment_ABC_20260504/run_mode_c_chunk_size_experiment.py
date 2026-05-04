#!/usr/bin/env python3
"""Mode C (fully local / lexical) chunk-size comparison experiment.

Runs run_deepseek_direct_benchmark.py twice with chunk-chars ≈ 256-token
and ≈ 1024-token equivalents (at ~4 chars/token):

  256-token equiv  → chunk_chars=1024  overlap=128
  1024-token equiv → chunk_chars=4096  overlap=512

Usage (from scripts/ directory):
    python run_mode_c_chunk_size_experiment.py [--workers N] [--top-k K]

Results land in ../benchmark_results_MSFT_FY26Q1_qa/:
  deepseekflash_C_256equiv_chunk_controlled_v1.json / .md
  deepseekflash_C_1024equiv_chunk_controlled_v1.json / .md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = REPO_ROOT / "benchmark_results_MSFT_FY26Q1_qa"

BENCHMARK_FILE = REPO_ROOT / "msft_fy26q1_qa_benchmark_100_sanitized.json"
DOC_FILE = REPO_ROOT / "MSFT_FY26Q1_10Q.docx"

CHUNK_CONFIGS = [
    {
        "label": "256-token equiv",
        "chunk_chars": 1024,
        "overlap": 128,
        "run_name": "deepseekflash_C_256equiv_chunk_controlled_v1",
    },
    {
        "label": "1024-token equiv",
        "chunk_chars": 4096,
        "overlap": 512,
        "run_name": "deepseekflash_C_1024equiv_chunk_controlled_v1",
    },
]


def _load_score(run_name: str) -> dict | None:
    """Load overall score from the JSON result file."""
    result_file = OUTPUT_DIR / f"{run_name}.json"
    if not result_file.exists():
        return None
    try:
        data = json.loads(result_file.read_text())
        summary = data.get("summary", {})
        agg = data.get("aggregate", summary)
        return agg
    except Exception:
        return None


def run_config(cfg: dict, workers: int, top_k: int, max_questions: int) -> int:
    """Run a single chunk-size config. Returns subprocess returncode."""
    print("\n" + "=" * 70)
    print(f"  Mode C  |  {cfg['label']}  |  chunk_chars={cfg['chunk_chars']}  overlap={cfg['overlap']}")
    print("=" * 70)

    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_deepseek_direct_benchmark.py"),
        "--benchmark-file", str(BENCHMARK_FILE),
        "--doc-file", str(DOC_FILE),
        "--chunk-chars", str(cfg["chunk_chars"]),
        "--chunk-overlap", str(cfg["overlap"]),
        "--top-k", str(top_k),
        "--max-questions", str(max_questions),
        "--workers", str(workers),
        "--run-name", cfg["run_name"],
        "--output-dir", str(OUTPUT_DIR),
        "--thinking", "true",
        "--reasoning-effort", "high",
    ]

    print("Running:", " ".join(cmd))
    start = time.time()
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    elapsed = time.time() - start
    print(f"\n[done in {elapsed:.0f}s]  returncode={result.returncode}")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Mode C chunk-size experiment (256 vs 1024 token equiv)")
    parser.add_argument("--workers", type=int, default=10, help="Parallel threads (default: 10)")
    parser.add_argument("--top-k", type=int, default=8, help="Top-k lexical chunks per question (default: 8)")
    parser.add_argument("--max-questions", type=int, default=100, help="Questions per run (default: 100)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nMode C Chunk-Size Experiment")
    print(f"  Benchmark : {BENCHMARK_FILE}")
    print(f"  Document  : {DOC_FILE}")
    print(f"  Workers   : {args.workers}")
    print(f"  Top-k     : {args.top_k}")
    print(f"  Questions : {args.max_questions}")
    print(f"  Output dir: {OUTPUT_DIR}")

    exit_codes = []
    for cfg in CHUNK_CONFIGS:
        rc = run_config(cfg, args.workers, args.top_k, args.max_questions)
        exit_codes.append(rc)

    # Print comparison summary
    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Config':<22} {'Chunk':<8} {'Result file':}")
    print("-" * 70)
    for cfg in CHUNK_CONFIGS:
        agg = _load_score(cfg["run_name"])
        if agg:
            overall = agg.get("overall_correct", agg.get("correct", "?"))
            total = agg.get("total", "?")
            pct = agg.get("overall_accuracy", agg.get("accuracy", "?"))
            if isinstance(pct, float):
                pct = f"{pct:.1%}"
            score_str = f"{overall}/{total} ({pct})"
        else:
            score_str = "(result file not found)"
        print(f"  {cfg['label']:<20} {cfg['chunk_chars']:<8} {score_str}")
    print("=" * 70)

    return 0 if all(rc == 0 for rc in exit_codes) else 1


if __name__ == "__main__":
    sys.exit(main())
