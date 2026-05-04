#!/usr/bin/env python3
"""Run SurfSense benchmark with Gemma-3-12B-IT via LM Studio.

Sets SurfSense LLM config id=24 to gemma-3-12b-it (LMStudio port 1234)
and delegates to scripts/run_surfsense_benchmark.py.

Prerequisites:
  1. LM Studio must be running on port 1234 with gemma-3-12b-it loaded.
  2. The SurfSense backend must be running (http://localhost:8929).
  3. Search space 1 must have agent_llm_id=24.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request


SURFSENSE_BASE_URL = "http://localhost:8929"
LLM_CONFIG_ID = 24
LMSTUDIO_MODEL = "gemma-3-12b-it"
LMSTUDIO_API_BASE = "http://host.docker.internal:1234/v1"


def _login(base_url: str, username: str, password: str) -> str:
    req = urllib.request.Request(
        base_url + "/auth/jwt/login",
        data=urllib.parse.urlencode({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    for attempt in range(5):
        try:
            return json.loads(urllib.request.urlopen(req).read())["access_token"]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                print("[setup] 429 rate-limited, waiting 20s ...", flush=True)
                time.sleep(20)
                continue
            raise


def _update_llm_config(base_url: str, token: str, config_id: int) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "name": "Gemma 3 12B IT (LM Studio)",
        "description": "gemma-3-12b-it via LM Studio",
        "provider": "OPENAI",
        "custom_provider": "",
        "model_name": LMSTUDIO_MODEL,
        "api_key": "lm-studio",
        "api_base": LMSTUDIO_API_BASE,
        "litellm_params": {},
        "system_instructions": "",
        "use_default_system_instructions": True,
        "citations_enabled": True,
    }
    req = urllib.request.Request(
        base_url + f"/api/v1/new-llm-configs/{config_id}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="PUT",
    )
    for attempt in range(5):
        try:
            resp = json.loads(urllib.request.urlopen(req).read())
            print(f"[setup] LLM config {config_id} → model={resp['model_name']}", flush=True)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                print("[setup] 429 rate-limited, waiting 20s ...", flush=True)
                time.sleep(20)
                continue
            raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run SurfSense benchmark with Gemma-3-12B-IT via LM Studio"
    )
    parser.add_argument("--benchmark-file", default="msft_fy26q1_qa_benchmark_100_sanitized.json")
    parser.add_argument("--max-questions", type=int, default=100)
    parser.add_argument("--start-question", type=int, default=1)
    parser.add_argument("--run-name", default="gemma3_12b_it_surfsense_1024chunk_w1")
    parser.add_argument("--config", default="benchmark_runner_config.json")
    parser.add_argument("--output-dir", default="benchmark_results_MSFT_FY26Q1_qa")
    parser.add_argument("--document-title-contains", default="MSFT_FY26Q1_10Q")
    parser.add_argument("--sanitize-questions", default="true")
    parser.add_argument("--sleep-between", type=float, default=0.0)
    parser.add_argument("--request-timeout", type=float, default=300.0,
                        help="Per-request timeout in seconds (default: 300)")
    parser.add_argument("--disabled-tools", default=None,
                        help="Comma-separated disabled tools (default: web_search,scrape_webpage)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel workers (default: 1)")
    parser.add_argument("--username", default="shi.yu@broadridge.com")
    parser.add_argument("--password", default="Lexar1357!!")
    parser.add_argument("--skip-llm-update", action="store_true",
                        help="Skip updating the SurfSense LLM config (if already set to Gemma-3-12B)")
    ranked_group = parser.add_mutually_exclusive_group()
    ranked_group.add_argument("--enforce-ranked-evidence-first", dest="enforce_ranked_evidence_first",
                              action="store_true")
    ranked_group.add_argument("--no-enforce-ranked-evidence-first", dest="enforce_ranked_evidence_first",
                              action="store_false")
    parser.set_defaults(enforce_ranked_evidence_first=None)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    if not args.skip_llm_update:
        print(f"[setup] Logging in to {SURFSENSE_BASE_URL} ...", flush=True)
        token = _login(SURFSENSE_BASE_URL, args.username, args.password)
        _update_llm_config(SURFSENSE_BASE_URL, token, LLM_CONFIG_ID)

    cmd = [
        sys.executable,
        "scripts/run_surfsense_benchmark.py",
        "--config", args.config,
        "--benchmark-file", args.benchmark_file,
        "--max-questions", str(args.max_questions),
        "--start-question", str(args.start_question),
        "--run-name", args.run_name,
        "--output-dir", args.output_dir,
        "--document-title-contains", args.document_title_contains,
        "--sanitize-questions", str(args.sanitize_questions),
        "--sleep-between", str(args.sleep_between),
        "--request-timeout", str(args.request_timeout),
        "--workers", str(args.workers),
    ]

    if args.disabled_tools is not None:
        cmd += ["--disabled-tools", args.disabled_tools]
    else:
        cmd += ["--disabled-tools", "web_search,scrape_webpage"]

    if args.enforce_ranked_evidence_first is True:
        cmd += ["--enforce-ranked-evidence-first"]
    elif args.enforce_ranked_evidence_first is False:
        cmd += ["--no-enforce-ranked-evidence-first"]

    print(f"[setup] Launching benchmark (workers={args.workers}, run={args.run_name}) ...", flush=True)
    completed = subprocess.run(cmd)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
