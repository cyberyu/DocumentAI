#!/usr/bin/env python3
"""Launch master agent with multiple subagents (one per chunk+embedding candidate).

This wrapper:
1) prompts for DeepSeek API key at startup (unless --api-key is provided),
2) ensures a DeepSeek V4 Flash config exists for the target search space,
3) sets search space agent_llm_id to that config,
4) runs scripts/self_adaptive_master_agent.py with your chunk/embedding matrix.
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
from pathlib import Path

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
        return json.loads(payload) if payload else {}


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
                time.sleep(15)
                continue
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Login failed ({exc.code}): {detail}") from exc


def _ensure_deepseek_flash_config(
    *,
    base_url: str,
    token: str,
    search_space_id: int,
    api_key: str,
    config_name: str,
) -> int:
    query = urllib.parse.urlencode({"search_space_id": search_space_id, "limit": 200, "skip": 0})
    list_url = f"{base_url}/api/v1/new-llm-configs?{query}"
    payload = _request_json("GET", list_url, token=token)
    items = payload if isinstance(payload, list) else payload.get("items", [])

    for cfg in items:
        provider = str(cfg.get("provider") or "").upper().strip()
        model_name = str(cfg.get("model_name") or "").lower().strip()
        if provider == "DEEPSEEK" and model_name == DEEPSEEK_MODEL:
            cfg_id = int(cfg["id"])
            _request_json(
                "PUT",
                f"{base_url}/api/v1/new-llm-configs/{cfg_id}",
                token=token,
                json_body={
                    "name": config_name,
                    "provider": "DEEPSEEK",
                    "model_name": DEEPSEEK_MODEL,
                    "api_key": api_key,
                    "api_base": DEEPSEEK_API_BASE,
                    "use_default_system_instructions": True,
                    "citations_enabled": True,
                },
            )
            print(f"[setup] Updated DeepSeek Flash config id={cfg_id}", flush=True)
            return cfg_id

    created = _request_json(
        "POST",
        f"{base_url}/api/v1/new-llm-configs",
        token=token,
        json_body={
            "name": config_name,
            "description": "DeepSeek V4 Flash for master/subagent benchmark",
            "provider": "DEEPSEEK",
            "model_name": DEEPSEEK_MODEL,
            "api_key": api_key,
            "api_base": DEEPSEEK_API_BASE,
            "litellm_params": {"temperature": 0.0},
            "system_instructions": "",
            "use_default_system_instructions": True,
            "citations_enabled": True,
            "search_space_id": search_space_id,
        },
    )
    cfg_id = int(created["id"])
    print(f"[setup] Created DeepSeek Flash config id={cfg_id}", flush=True)
    return cfg_id


def _set_agent_llm(base_url: str, token: str, search_space_id: int, llm_config_id: int) -> None:
    resp = _request_json(
        "PUT",
        f"{base_url}/api/v1/search-spaces/{search_space_id}/llm-preferences",
        token=token,
        json_body={"agent_llm_id": llm_config_id},
    )
    print(f"[setup] Search space {search_space_id} agent_llm_id -> {resp.get('agent_llm_id')}", flush=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run master+subagents for chunk/embedding extraction")
    parser.add_argument("--base-url", default=SURFSENSE_BASE_URL)
    parser.add_argument("--username", default="shi.yu@broadridge.com")
    parser.add_argument("--password", default="Lexar1357!!")
    parser.add_argument("--search-space-id", type=int, default=1)
    parser.add_argument("--source-doc", default="MSFT_FY26Q1_10Q.docx")
    parser.add_argument("--benchmark-file", default="msft_fy26q1_qa_benchmark_100_sanitized.json")
    parser.add_argument("--max-questions", type=int, default=100)
    parser.add_argument("--start-question", type=int, default=1)
    parser.add_argument("--subagent-workers", type=int, default=3)
    parser.add_argument("--benchmark-workers", type=int, default=1)
    parser.add_argument("--request-timeout", type=float, default=300.0)
    parser.add_argument("--run-prefix", default="deepseekflash_master_subagents")
    parser.add_argument("--output-dir", default="benchmark_results_master_agent")
    parser.add_argument("--cleanup-documents", default="true")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Optional per-request chunk size override for upload chunking",
    )
    parser.add_argument(
        "--chunk-sizes",
        default="256,1024",
        help="Comma-separated chunk sizes (token lengths) for candidate expansion",
    )
    parser.add_argument(
        "--chunking-strategies",
        default="chunk_text,sandwitch_chunk",
        help="Comma-separated chunking strategies; one subagent per strategy×embedding pair",
    )
    parser.add_argument(
        "--embedding-models",
        default="fastembed/all-MiniLM-L6-v2,fastembed/bge-base-en-v1.5,fastembed/bge-large-en-v1.5",
        help="Comma-separated embedding models; one subagent per strategy×embedding pair",
    )
    parser.add_argument(
        "--ranking-variants",
        default="hybrid_rrf_plus,hybrid_weighted",
        help="Comma-separated ranking variants; one subagent per strategy×embedding×size×ranking candidate",
    )
    parser.add_argument("--api-key", default=None, help="DeepSeek API key (otherwise prompted)")
    parser.add_argument("--deepseek-config-name", default="DeepSeek V4 Flash (MasterAgent)")
    return parser


def main() -> int:
    try:
        args = build_arg_parser().parse_args()

        api_key = (args.api_key or "").strip()
        if not api_key:
            api_key = getpass.getpass("Enter your DeepSeek API key for deepseek-v4-flash: ").strip()
        if not api_key:
            print("ERROR: DeepSeek API key is required", file=sys.stderr)
            return 2

        token = _login(args.base_url, args.username, args.password)
        cfg_id = _ensure_deepseek_flash_config(
            base_url=args.base_url,
            token=token,
            search_space_id=args.search_space_id,
            api_key=api_key,
            config_name=args.deepseek_config_name,
        )
        _set_agent_llm(args.base_url, token, args.search_space_id, cfg_id)

        script_dir = Path(__file__).resolve().parent
        repo_root = script_dir.parent

        cmd = [
            sys.executable,
            "scripts/self_adaptive_master_agent.py",
            "--base-url", args.base_url,
            "--username", args.username,
            "--password", args.password,
            "--search-space-id", str(args.search_space_id),
            "--source-doc", args.source_doc,
            "--benchmark-file", args.benchmark_file,
            "--max-questions", str(args.max_questions),
            "--start-question", str(args.start_question),
            "--benchmark-workers", str(args.benchmark_workers),
            "--subagent-workers", str(args.subagent_workers),
            "--request-timeout", str(args.request_timeout),
            "--run-prefix", args.run_prefix,
            "--output-dir", args.output_dir,
            "--cleanup-documents", args.cleanup_documents,
            "--llm-model", DEEPSEEK_MODEL,
            "--chunking-strategies", args.chunking_strategies,
            "--embedding-models", args.embedding_models,
            "--ranking-variants", args.ranking_variants,
        ]
        if args.chunk_size is not None:
            if args.chunk_size <= 0:
                print("ERROR: --chunk-size must be a positive integer", file=sys.stderr)
                return 2
            cmd.extend(["--chunk-size", str(args.chunk_size)])
        else:
            cmd.extend(["--chunk-sizes", args.chunk_sizes])

        print(f"[setup] Running: {' '.join(cmd)}", flush=True)
        completed = subprocess.run(cmd, cwd=str(repo_root))
        return completed.returncode
    except KeyboardInterrupt:
        print("Interrupted by user (Ctrl+C).", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
