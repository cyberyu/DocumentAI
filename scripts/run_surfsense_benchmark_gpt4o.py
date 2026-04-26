#!/usr/bin/env python3
"""Run SurfSense benchmark with GPT-4o-oriented defaults.

This wrapper keeps the QA dataset unchanged and delegates execution to
scripts/run_surfsense_benchmark.py with a distinct run name/output set.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run GPT-4o benchmark wrapper")
    parser.add_argument(
        "--benchmark-file",
        default="msft_fy26q1_qa_benchmark_100_sanitized.json",
        help="Benchmark JSON file (default keeps existing sanitized QA dataset)",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=100,
        help="Max questions to run (default: 100)",
    )
    parser.add_argument(
        "--run-name",
        default="openai_gpt4o_full100",
        help="Run name prefix for output artifacts",
    )
    parser.add_argument(
        "--config",
        default="benchmark_runner_config.json",
        help="Config file path for shared benchmark settings",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results_MSFT_FY26Q1_qa",
        help="Output directory for json/md artifacts",
    )
    parser.add_argument(
        "--document-title-contains",
        default="MSFT_FY26Q1_10Q",
        help="Document title filter to resolve mentioned_document_ids for GPT-4o runs",
    )
    parser.add_argument(
        "--sanitize-questions",
        default="false",
        help="Whether to apply benchmark question rewrite (default false for GPT-4o)",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    cmd = [
        sys.executable,
        "scripts/run_surfsense_benchmark.py",
        "--config",
        args.config,
        "--benchmark-file",
        args.benchmark_file,
        "--max-questions",
        str(args.max_questions),
        "--run-name",
        args.run_name,
        "--output-dir",
        args.output_dir,
        "--document-title-contains",
        args.document_title_contains,
        "--sanitize-questions",
        str(args.sanitize_questions),
    ]

    completed = subprocess.run(cmd)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
