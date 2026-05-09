import argparse
import json
import os
import time
from pathlib import Path
from typing import Optional

import requests


def _load_config(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_models(value: Optional[str]) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, str):
            parsed = [parsed]
        if isinstance(parsed, list):
            return [m.strip() for m in parsed if isinstance(m, str) and m.strip()]
    except json.JSONDecodeError:
        pass
    return [m.strip() for m in stripped.split(",") if m.strip()]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload and verify indexed embeddings for a markdown doc.")
    parser.add_argument("--config", default="benchmark_runner_config.json")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--base-file", default="MSFT_FY26Q1_10Q_content.md")
    parser.add_argument("--search-space-id", default="2")
    parser.add_argument(
        "--embedding-models",
        default=None,
        help='JSON array or comma-separated list, e.g. ["fastembed/all-MiniLM-L6-v2"]',
    )
    parser.add_argument("--chunking-strategy", default="sandwitch_chunk")
    parser.add_argument("--polls", type=int, default=240)
    parser.add_argument("--poll-interval", type=float, default=3)
    return parser.parse_args()


def main() -> None:
    args = _args()
    cfg = _load_config(args.config)

    base = args.base_url or os.getenv("BASE_URL") or cfg.get("BASE_URL") or "http://localhost:8929"
    username = args.username or os.getenv("BENCHMARK_USERNAME") or cfg.get("USERNAME")
    password = args.password or os.getenv("BENCHMARK_PASSWORD") or cfg.get("PASSWORD")

    model_input = args.embedding_models or os.getenv("EMBEDDING_MODELS") or ""
    embeddings = _parse_models(model_input)
    if not embeddings:
        embeddings = [
            "fastembed/all-MiniLM-L6-v2",
            "fastembed/bge-base-en-v1.5",
            "fastembed/bge-large-en-v1.5",
        ]

    if not username or not password:
        raise RuntimeError("Missing credentials. Provide --username/--password or set them in benchmark_runner_config.json")

    session = requests.Session()
    login = session.post(
        f"{base}/auth/jwt/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    source_path = Path(args.base_file)
    upload_name = f"{source_path.stem}_{int(time.time())}{source_path.suffix or '.md'}"
    upload_path = Path(upload_name)
    unique_suffix = f"\n\nRun marker: {int(time.time())}\n"
    upload_path.write_text(source_path.read_text(encoding="utf-8") + unique_suffix, encoding="utf-8")

    with upload_path.open("rb") as file_handle:
        upload = session.post(
            f"{base}/api/v1/documents/fileupload",
            headers=headers,
            files={"files": (upload_name, file_handle, "text/markdown")},
            data={
                "search_space_id": str(args.search_space_id),
                "embedding_models": json.dumps(embeddings),
                "chunking_strategy": args.chunking_strategy,
                "should_summarize": "false",
                "use_vision_llm": "false",
                "processing_mode": "basic",
            },
            timeout=120,
        )
    upload.raise_for_status()
    body = upload.json()

    doc_id = None
    if isinstance(body.get("document_ids"), list) and body.get("document_ids"):
        doc_id = str(body["document_ids"][0])
    elif body.get("document_id") is not None:
        doc_id = str(body.get("document_id"))

    if not doc_id:
        raise RuntimeError(f"Upload response did not include a document id: {body}")

    status = "unknown"
    index = f"surfsense_chunks_{args.search_space_id}"
    count_num = 0
    count_str = 0

    for i in range(args.polls):
        doc = session.get(f"{base}/api/v1/documents/{doc_id}", headers=headers, timeout=30)
        if doc.status_code == 200:
            payload = doc.json()
            if isinstance(payload.get("status"), dict):
                status = (payload.get("status") or {}).get("state") or "unknown"
            else:
                status = payload.get("status") or "unknown"
        print(f"poll {i + 1}: {status}")

        q_num = {"size": 0, "query": {"term": {"document_id": int(doc_id)}}}
        q_str = {"size": 0, "query": {"term": {"document_id": doc_id}}}
        count_by_num = requests.get(f"http://localhost:9200/{index}/_search", json=q_num, timeout=30)
        count_by_num.raise_for_status()
        count_num = count_by_num.json()["hits"]["total"]["value"]
        count_by_str = requests.get(f"http://localhost:9200/{index}/_search", json=q_str, timeout=30)
        count_by_str.raise_for_status()
        count_str = count_by_str.json()["hits"]["total"]["value"]

        if status in {"ready", "failed"} or count_num > 0 or count_str > 0:
            break
        time.sleep(args.poll_interval)

    sample = requests.get(
        f"http://localhost:9200/{index}/_search",
        json={"size": 1, "query": {"term": {"document_id": int(doc_id)}}},
        timeout=30,
    )
    sample.raise_for_status()
    hits = sample.json().get("hits", {}).get("hits", [])
    fields = []
    if hits:
        source = hits[0].get("_source", {})
        fields = sorted([k for k in source if k.startswith("embedding_") or k.startswith("embeddings_")])

    print("SUMMARY_JSON_START")
    print(
        json.dumps(
            {
                "doc_id": doc_id,
                "final_status": status,
                "chunking_strategy": args.chunking_strategy,
                "embedding_models": embeddings,
                "opensearch_chunks_num_term": count_num,
                "opensearch_chunks_str_term": count_str,
                "embedding_fields_on_sample": fields,
                "upload_response": body,
            },
            indent=2,
        )
    )
    print("SUMMARY_JSON_END")


if __name__ == "__main__":
    main()
