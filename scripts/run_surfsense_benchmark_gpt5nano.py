#!/usr/bin/env python3
"""Run SurfSense benchmark with GPT-5 Nano (global config id=-3).

Sets the search space's agent_llm_id to -3 (GPT-5 Nano, global config defined
in global_llm_config.yaml) then delegates to scripts/run_surfsense_benchmark.py.

Prerequisites:
  1. The SurfSense backend must be running (http://localhost:8929).
  2. global_llm_config.yaml must have id=-3 pointing to gpt-5-nano with a valid
     OpenAI API key.
  3. Search space 1 (My Search Space) must exist.
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
GPT5_NANO_LLM_CONFIG_ID = -3


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
                print("[setup] 429 rate-limited on login, waiting 30s ...", flush=True)
                time.sleep(30)
                continue
            raise


def _update_llm_preferences(
    base_url: str, token: str, search_space_id: int, llm_config_id: int
) -> None:
    """PUT /api/v1/search-spaces/{id}/llm-preferences to set agent_llm_id."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {"agent_llm_id": llm_config_id}
    req = urllib.request.Request(
        base_url + f"/api/v1/search-spaces/{search_space_id}/llm-preferences",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="PUT",
    )
    for attempt in range(5):
        try:
            resp = json.loads(urllib.request.urlopen(req).read())
            print(
                f"[setup] Search space {search_space_id} → agent_llm_id={resp.get('agent_llm_id')}",
                flush=True,
            )
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                print("[setup] 429 rate-limited on prefs update, waiting 30s ...", flush=True)
                time.sleep(30)
                continue
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Failed to update LLM preferences ({e.code}): {body}"
            ) from e


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run SurfSense benchmark with GPT-5 Nano (global config id=-3)"
    )
    parser.add_argument("--benchmark-file", default="msft_fy26q1_qa_benchmark_100_sanitized.json")
    parser.add_argument("--max-questions", type=int, default=100)
    parser.add_argument("--start-question", type=int, default=1)
    parser.add_argument("--run-name", default="gpt5nano_surfsense_1024chunk_w1")
    parser.add_argument("--config", default="benchmark_runner_config.json")
    parser.add_argument("--output-dir", default="benchmark_results_MSFT_FY26Q1_qa")
    parser.add_argument("--document-title-contains", default="MSFT_FY26Q1_10Q")
    parser.add_argument("--sanitize-questions", default="true")
    parser.add_argument("--sleep-between", type=float, default=0.0)
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=300.0,
        help="Per-request timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--disabled-tools",
        default=None,
        help="Comma-separated disabled tools (default: web_search,scrape_webpage)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers (default: 1)",
    )
    parser.add_argument("--search-space-id", type=int, default=1)
    parser.add_argument("--username", default="shi.yu@broadridge.com")
    parser.add_argument("--password", default="Lexar1357!!")
    parser.add_argument(
        "--skip-llm-update",
        action="store_true",
        help="Skip updating the search space LLM preference (if already set to GPT-5 Nano)",
    )
    ranked_group = parser.add_mutually_exclusive_group()
    ranked_group.add_argument(
        "--enforce-ranked-evidence-first",
        dest="enforce_ranked_evidence_first",
        action="store_true",
    )
    ranked_group.add_argument(
        "--no-enforce-ranked-evidence-first",
        dest="enforce_ranked_evidence_first",
        action="store_false",
    )
    parser.set_defaults(enforce_ranked_evidence_first=None)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    if not args.skip_llm_update:
        print(f"[setup] Logging in to {SURFSENSE_BASE_URL} ...", flush=True)
        token = _login(SURFSENSE_BASE_URL, args.username, args.password)
        _update_llm_preferences(
            SURFSENSE_BASE_URL, token, args.search_space_id, GPT5_NANO_LLM_CONFIG_ID
        )

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

    print(f"[setup] Running: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
