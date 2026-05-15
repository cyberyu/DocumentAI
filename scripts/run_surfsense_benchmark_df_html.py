#!/usr/bin/env python3
"""Run SurfSense benchmark for df.html using df_qa.json.

This wrapper delegates to scripts/run_surfsense_benchmark.py with defaults for:
- document_title_contains: df.html
- benchmark_file: df_qa.json

If df_qa.json is missing locally, it can auto-download the latest matching
benchmark dataset associated with the df.html document from the backend DB
(/api/v1/documents/{document_id}/benchmark-data/*).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _read_json_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_present(cfg: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in cfg and cfg[key] not in (None, ""):
            return cfg[key]
    return None


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _login(base_url: str, username: str, password: str) -> str:
    req = urllib.request.Request(
        base_url + "/auth/jwt/login",
        data=urllib.parse.urlencode({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Login succeeded but access_token is missing")
    return token


def _get_json(base_url: str, path: str, token: str) -> Any:
    req = urllib.request.Request(
        base_url + path,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _resolve_search_space_id(base_url: str, token: str, search_space_name: str | None) -> int:
    spaces = _get_json(base_url, "/api/v1/searchspaces", token)
    if not isinstance(spaces, list) or not spaces:
        raise RuntimeError("No accessible search spaces found")

    if search_space_name:
        needle = search_space_name.strip().lower()
        for item in spaces:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip().lower()
            if needle == name:
                value = item.get("id")
                if isinstance(value, int):
                    return value

    first_id = spaces[0].get("id")
    if not isinstance(first_id, int):
        raise RuntimeError("Unable to resolve search space id")
    return first_id


def _find_document_id_by_title(base_url: str, token: str, search_space_id: int, title_contains: str) -> int:
    payload = _get_json(base_url, f"/api/v1/documents?search_space_id={search_space_id}", token)
    docs = payload.get("items", []) if isinstance(payload, dict) else payload
    if not isinstance(docs, list):
        raise RuntimeError("Unexpected documents response while resolving df.html document")

    needle = title_contains.strip().lower()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        title = str(doc.get("title", "")).strip().lower()
        if needle in title:
            doc_id = doc.get("id")
            if isinstance(doc_id, int):
                return doc_id

    raise RuntimeError(f"No document found matching title contains '{title_contains}'")


def _download_latest_benchmark_data(
    *,
    base_url: str,
    token: str,
    document_id: int,
    preferred_filename: str,
    output_path: Path,
) -> Path:
    listing = _get_json(base_url, f"/api/v1/documents/{document_id}/benchmark-data", token)
    items = listing.get("items", []) if isinstance(listing, dict) else []
    if not isinstance(items, list) or not items:
        raise RuntimeError(f"No benchmark data associated with document_id={document_id}")

    preferred = [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("dataset_filename", "")).strip().lower() == preferred_filename.lower()
    ]
    candidates = preferred if preferred else [item for item in items if isinstance(item, dict)]
    candidates = sorted(
        candidates,
        key=lambda item: (
            str(item.get("created_date") or ""),
            int(item.get("benchmarkdata_id") or 0),
        ),
        reverse=True,
    )
    selected = candidates[0]

    benchmarkdata_id = selected.get("benchmarkdata_id")
    if not isinstance(benchmarkdata_id, int):
        raise RuntimeError("Invalid benchmarkdata_id in benchmark-data listing")

    req = urllib.request.Request(
        base_url + f"/api/v1/documents/{document_id}/benchmark-data/{benchmarkdata_id}/download",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = response.read()

    output_path.write_bytes(payload)
    return output_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SurfSense benchmark for df.html + df_qa.json")
    parser.add_argument("--config", default="benchmark_runner_config.json")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--search-space-name", default=None)
    parser.add_argument("--search-space-id", type=int, default=None)
    parser.add_argument("--document-title-contains", default="df.html")
    parser.add_argument("--benchmark-file", default="df_qa.json")
    parser.add_argument("--max-questions", type=int, default=44)
    parser.add_argument("--start-question", type=int, default=1)
    parser.add_argument("--run-name", default="df_html_check44")
    parser.add_argument("--output-dir", default="benchmark_results_df_html_qa")
    parser.add_argument("--sanitize-questions", default="false")
    parser.add_argument("--sleep-between", type=float, default=0.0)
    parser.add_argument("--request-timeout", type=float, default=240.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--disabled-tools", default="web_search,scrape_webpage")
    parser.add_argument(
        "--auto-download-benchmark",
        default="true",
        help="If true and benchmark file is missing, download latest benchmark data from DB",
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
    cfg = _read_json_config(Path(args.config) if args.config else None)

    base_url = args.base_url or _first_present(cfg, ["base_url", "BASE_URL"]) or "http://localhost:8930"
    username = args.username or _first_present(cfg, ["username", "USERNAME"])
    password = args.password or _first_present(cfg, ["password", "PASSWORD"])
    search_space_name = (
        args.search_space_name
        or _first_present(cfg, ["search_space_name", "SEARCH_SPACE_NAME", "searchspace", "SEARCHSPACE"])
    )

    benchmark_path = Path(args.benchmark_file)
    auto_download = _as_bool(args.auto_download_benchmark, True)

    if not benchmark_path.exists() and auto_download:
        if not username or not password:
            print(
                "ERROR: benchmark file missing and auto-download requires username/password",
                file=sys.stderr,
            )
            return 2

        print(f"[setup] Benchmark file not found: {benchmark_path}. Downloading from DB...", flush=True)
        token = _login(base_url, username, password)
        search_space_id = (
            args.search_space_id
            if args.search_space_id is not None
            else _resolve_search_space_id(base_url, token, search_space_name)
        )
        doc_id = _find_document_id_by_title(
            base_url,
            token,
            search_space_id,
            args.document_title_contains,
        )
        _download_latest_benchmark_data(
            base_url=base_url,
            token=token,
            document_id=doc_id,
            preferred_filename=benchmark_path.name,
            output_path=benchmark_path,
        )
        print(f"[setup] Downloaded benchmark dataset to {benchmark_path}", flush=True)

    if not benchmark_path.exists():
        print(f"ERROR: benchmark file not found: {benchmark_path}", file=sys.stderr)
        return 2

    cmd = [
        sys.executable,
        "scripts/run_surfsense_benchmark.py",
        "--config",
        args.config,
        "--base-url",
        base_url,
        "--benchmark-file",
        str(benchmark_path),
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
        "--disabled-tools",
        args.disabled_tools,
    ]

    if args.search_space_id is not None:
        cmd += ["--search-space-id", str(args.search_space_id)]
    elif search_space_name:
        cmd += ["--search-space-name", str(search_space_name)]

    if args.username is not None:
        cmd += ["--username", args.username]
    if args.password is not None:
        cmd += ["--password", args.password]

    if args.enforce_ranked_evidence_first is True:
        cmd += ["--enforce-ranked-evidence-first"]
    elif args.enforce_ranked_evidence_first is False:
        cmd += ["--no-enforce-ranked-evidence-first"]

    print(f"[setup] Running: {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
