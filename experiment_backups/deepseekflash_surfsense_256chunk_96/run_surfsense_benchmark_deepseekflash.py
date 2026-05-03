#!/usr/bin/env python3
"""Run SurfSense benchmark with DeepSeek-v4-flash defaults.

This wrapper keeps the QA dataset unchanged and delegates execution to
scripts/run_surfsense_benchmark.py with a distinct run name/output set.

Prerequisites:
  1. The SurfSense backend must be running and its search space configured to use
     the DeepSeek V4 Flash LLM (id=20 in global_llm_config.yaml).
     Set agent_llm_id=20 on the target search space via the SurfSense UI or API.
  2. global_llm_config.yaml must have a valid DeepSeek API key in the id=20 entry.
  3. The backend has been restarted with CHUNKER_CHUNK_SIZE=1024 (already wired in
     docker-compose.yml via the backend_config_init_override.py volume mount).

Chunker note:
  After changing chunk_size, re-ingest the MSFT_FY26Q1_10Q.docx document so the DB
  stores the new 1024-token chunks before running this benchmark.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run DeepSeek-v4-flash SurfSense benchmark wrapper")
    parser.add_argument(
        "--benchmark-file",
        default="msft_fy26q1_qa_benchmark_100_sanitized.json",
        help="Benchmark JSON file (default: sanitized QA dataset)",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=100,
        help="Max questions to run (default: 100)",
    )
    parser.add_argument(
        "--start-question",
        type=int,
        default=1,
        help="1-based question index to start from (default: 1)",
    )
    parser.add_argument(
        "--run-name",
        default="deepseekflash_surfsense_full100",
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
        help="Document title filter to resolve mentioned_document_ids",
    )
    parser.add_argument(
        "--sanitize-questions",
        default="true",
        help="Whether to apply benchmark question rewrite (default true for DeepSeek)",
    )
    parser.add_argument(
        "--sleep-between",
        type=float,
        default=0.0,
        help="Seconds to sleep between questions (default: 0)",
    )
    parser.add_argument(
        "--delay-per-request",
        type=float,
        default=None,
        help="Seconds to sleep before each /api/v1/new_chat request",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=180.0,
        help="HTTP request timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--disabled-tools",
        default=None,
        help="Comma-separated tool names to disable (default: web_search,scrape_webpage). Pass empty string to allow all tools.",
    )
    ranked_group = parser.add_mutually_exclusive_group()
    ranked_group.add_argument(
        "--enforce-ranked-evidence-first",
        dest="enforce_ranked_evidence_first",
        action="store_true",
        help="Force matched chunks to be presented first in ranked order",
    )
    ranked_group.add_argument(
        "--no-enforce-ranked-evidence-first",
        dest="enforce_ranked_evidence_first",
        action="store_false",
        help="Keep document-native chunk order instead of matched-first ordering",
    )
    parser.set_defaults(enforce_ranked_evidence_first=None)
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
        "--start-question",
        str(args.start_question),
        "--run-name",
        args.run_name,
        "--output-dir",
        args.output_dir,
        "--document-title-contains",
        args.document_title_contains,
        "--sanitize-questions",
        str(args.sanitize_questions),
        "--sleep-between",
        str(args.sleep_between),
        "--request-timeout",
        str(args.request_timeout),
    ]

    if args.delay_per_request is not None:
        cmd += ["--delay-per-request", str(args.delay_per_request)]

    if args.disabled_tools is not None:
        cmd += ["--disabled-tools", args.disabled_tools]

    if args.enforce_ranked_evidence_first is True:
        cmd += ["--enforce-ranked-evidence-first"]
    elif args.enforce_ranked_evidence_first is False:
        cmd += ["--no-enforce-ranked-evidence-first"]

    completed = subprocess.run(cmd)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
