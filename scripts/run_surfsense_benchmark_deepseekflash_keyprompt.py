#!/usr/bin/env python3
"""Run SurfSense benchmark with DeepSeek-v4-flash.

This wrapper:
  1) prompts for a DeepSeek API key at startup (unless --api-key is provided),
    2) ensures a per-search-space NewLLMConfig exists for deepseek-v4-flash,
  3) sets the search space agent_llm_id to that config,
  4) delegates execution to scripts/run_surfsense_benchmark.py.
"""

from __future__ import annotations

import argparse
import getpass
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SURFSENSE_BASE_URL = "http://localhost:8929"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"


def _request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    timeout: float = 60.0,
) -> dict | list:
    headers = {"Accept": "application/json"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
        if not payload:
            return {}
        return json.loads(payload)


def _login(base_url: str, username: str, password: str) -> str:
    req = urllib.request.Request(
        base_url + "/auth/jwt/login",
        data=urllib.parse.urlencode({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))["access_token"]
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 4:
                print("[setup] 429 rate-limited on login, waiting 15s ...", flush=True)
                time.sleep(15)
                continue
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Login failed ({exc.code}): {detail}") from exc


def _list_llm_configs(base_url: str, token: str, search_space_id: int) -> list[dict]:
    query = urllib.parse.urlencode({"search_space_id": search_space_id, "limit": 200, "skip": 0})
    url = f"{base_url}/api/v1/new-llm-configs?{query}"
    payload = _request_json("GET", url, token=token)
    if isinstance(payload, list):
        return payload
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return items if isinstance(items, list) else []


def _upsert_deepseek_flash_config(
    base_url: str,
    token: str,
    search_space_id: int,
    api_key: str,
    *,
    config_name: str,
) -> int:
    configs = _list_llm_configs(base_url, token, search_space_id)

    for cfg in configs:
        model_name = str(cfg.get("model_name") or "").strip().lower()
        provider = str(cfg.get("provider") or "").strip().upper()
        if provider == "DEEPSEEK" and model_name == DEEPSEEK_MODEL:
            cfg_id = int(cfg["id"])
            update_payload = {
                "name": config_name,
                "provider": "DEEPSEEK",
                "model_name": DEEPSEEK_MODEL,
                "api_key": api_key,
                "api_base": DEEPSEEK_API_BASE,
                "use_default_system_instructions": True,
                "citations_enabled": True,
            }
            _request_json(
                "PUT",
                f"{base_url}/api/v1/new-llm-configs/{cfg_id}",
                token=token,
                json_body=update_payload,
            )
            print(f"[setup] Updated DeepSeek Flash config id={cfg_id}", flush=True)
            return cfg_id

    create_payload = {
        "name": config_name,
        "description": "DeepSeek V4 Flash for benchmark runs",
        "provider": "DEEPSEEK",
        "model_name": DEEPSEEK_MODEL,
        "api_key": api_key,
        "api_base": DEEPSEEK_API_BASE,
        "litellm_params": {
            "temperature": 0.0,
        },
        "system_instructions": "",
        "use_default_system_instructions": True,
        "citations_enabled": True,
        "search_space_id": search_space_id,
    }
    created = _request_json(
        "POST",
        f"{base_url}/api/v1/new-llm-configs",
        token=token,
        json_body=create_payload,
    )
    cfg_id = int(created["id"])
    print(f"[setup] Created DeepSeek Flash config id={cfg_id}", flush=True)
    return cfg_id


def _set_agent_llm(base_url: str, token: str, search_space_id: int, llm_config_id: int) -> None:
    payload = {"agent_llm_id": llm_config_id}
    resp = _request_json(
        "PUT",
        f"{base_url}/api/v1/search-spaces/{search_space_id}/llm-preferences",
        token=token,
        json_body=payload,
    )
    print(
        f"[setup] Search space {search_space_id} agent_llm_id -> {resp.get('agent_llm_id')}",
        flush=True,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SurfSense benchmark with DeepSeek-v4-flash")
    parser.add_argument("--benchmark-file", default="msft_fy26q1_qa_benchmark_100_sanitized.json")
    parser.add_argument("--max-questions", type=int, default=100)
    parser.add_argument("--start-question", type=int, default=1)
    parser.add_argument("--run-name", default="deepseekflash_surfsense_full100")
    parser.add_argument("--config", default="benchmark_runner_config.json")
    parser.add_argument("--output-dir", default="benchmark_results_MSFT_FY26Q1_qa")
    parser.add_argument("--document-title-contains", default="MSFT_FY26Q1_10Q")
    parser.add_argument("--sanitize-questions", default="true")
    parser.add_argument("--sleep-between", type=float, default=0.0)
    parser.add_argument("--delay-per-request", type=float, default=None)
    parser.add_argument("--request-timeout", type=float, default=300.0)
    parser.add_argument("--disabled-tools", default="web_search,scrape_webpage")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--search-space-id", type=int, default=1)
    parser.add_argument("--username", default="shi.yu@broadridge.com")
    parser.add_argument("--password", default="Lexar1357!!")
    parser.add_argument(
        "--deepseek-config-name",
        default="DeepSeek V4 Flash (Benchmark)",
        help="Display name for created/updated NewLLMConfig",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="DeepSeek API key. If omitted, prompts securely at script start.",
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

    api_key = (args.api_key or "").strip()
    if not api_key:
        api_key = getpass.getpass("Enter your DeepSeek API key for deepseek-v4-flash: ").strip()
    if not api_key:
        print("ERROR: DeepSeek API key is required.", file=sys.stderr)
        return 2

    print(f"[setup] Logging in to {SURFSENSE_BASE_URL} ...", flush=True)
    token = _login(SURFSENSE_BASE_URL, args.username, args.password)

    llm_config_id = _upsert_deepseek_flash_config(
        SURFSENSE_BASE_URL,
        token,
        args.search_space_id,
        api_key,
        config_name=args.deepseek_config_name,
    )
    _set_agent_llm(SURFSENSE_BASE_URL, token, args.search_space_id, llm_config_id)

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
        "--workers",
        str(args.workers),
    ]

    if args.delay_per_request is not None:
        cmd += ["--delay-per-request", str(args.delay_per_request)]

    if args.disabled_tools is not None:
        cmd += ["--disabled-tools", args.disabled_tools]

    if args.enforce_ranked_evidence_first is True:
        cmd += ["--enforce-ranked-evidence-first"]
    elif args.enforce_ranked_evidence_first is False:
        cmd += ["--no-enforce-ranked-evidence-first"]

    print(f"[setup] Running: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
