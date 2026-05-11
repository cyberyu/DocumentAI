#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import requests


def _now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _elapsed_seconds(start_monotonic: float) -> float:
    return round(time.monotonic() - start_monotonic, 3)


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _extract_db_targets(dotenv_values: dict[str, str]) -> list[dict[str, Any]]:
    user = dotenv_values.get("DB_USER", "surfsense")
    password = dotenv_values.get("DB_PASSWORD", "surfsense")
    db_name = dotenv_values.get("DB_NAME", "surfsense")
    raw_port = dotenv_values.get("DB_PORT", "5432")
    try:
        port = int(raw_port)
    except ValueError:
        port = 5432

    hosts = [
        dotenv_values.get("DB_HOST", "db"),
        "localhost",
        "127.0.0.1",
    ]
    deduped_hosts: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        if not host or host in seen:
            continue
        deduped_hosts.append(host)
        seen.add(host)

    return [
        {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "dbname": db_name,
        }
        for host in deduped_hosts
    ]


def _extract_opensearch_hosts(dotenv_values: dict[str, str]) -> list[str]:
    raw_hosts = dotenv_values.get("OPENSEARCH_HOSTS", "http://localhost:9200")
    candidates = [h.strip() for h in raw_hosts.split(",") if h.strip()]
    candidates.extend(["http://localhost:9200", "http://127.0.0.1:9200"])

    normalized: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        host = value.rstrip("/")
        if not host or host in seen:
            continue
        normalized.append(host)
        seen.add(host)
    return normalized


@dataclass
class ApiClient:
    base_url: str
    timeout: float = 120.0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.session = requests.Session()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_404: bool = False,
        timeout: float | None = None,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        response = self.session.request(
            method=method,
            url=url,
            params=params,
            data=data,
            files=files,
            headers=headers,
            timeout=timeout if timeout is not None else self.timeout,
        )
        if response.status_code == 404 and allow_404:
            return response
        response.raise_for_status()
        return response

    def login(self, username: str, password: str) -> None:
        response = self.request(
            "POST",
            "/auth/jwt/login",
            data={"username": username, "password": password},
        )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Login succeeded but access_token is missing")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def get_search_space_id(self, search_space_name: str) -> int:
        response = self.request(
            "GET",
            "/api/v1/searchspaces",
            params={"limit": 200, "skip": 0},
        )
        payload = response.json()
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise RuntimeError("Unexpected search space list response")
        for item in items:
            if item.get("name") == search_space_name:
                return int(item["id"])
        raise RuntimeError(f"Search space not found: {search_space_name}")

    def list_documents(self, search_space_id: int) -> list[dict[str, Any]]:
        response = self.request(
            "GET",
            "/api/v1/documents",
            params={"search_space_id": search_space_id, "page_size": -1},
        )
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return payload["items"]
        if isinstance(payload, list):
            return payload
        raise RuntimeError("Unexpected documents list response")

    def delete_document(self, document_id: int) -> dict[str, Any]:
        response = self.request(
            "DELETE",
            f"/api/v1/documents/{document_id}",
            allow_404=True,
        )
        if response.status_code == 404:
            return {"message": "Document already deleted", "status_code": 404}
        return response.json()

    def upload_variants(
        self,
        search_space_id: int,
        document_path: Path,
        etl_services: list[str],
        chunking_strategies: list[str],
        chunk_sizes: list[int],
        embedding_models: list[str],
    ) -> dict[str, Any]:
        with document_path.open("rb") as f:
            files = {
                "files": (
                    document_path.name,
                    f,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            }
            data = {
                "search_space_id": str(search_space_id),
                "generate_variants": "true",
                "etl_services": json.dumps(etl_services),
                "chunking_strategies": json.dumps(chunking_strategies),
                "chunk_sizes": json.dumps(chunk_sizes),
                "embedding_models": json.dumps(embedding_models),
            }
            response = self.request("POST", "/api/v1/documents/fileupload", data=data, files=files)
            return response.json()

    def create_benchmark_job(
        self,
        benchmark_file: Path,
        search_space_id: int,
        etl_services: list[str],
        chunking_strategies: list[str],
        embedding_models: list[str],
        chunk_sizes: list[int],
        ranking_variants: list[str],
        max_questions: int,
        run_prefix: str,
    ) -> str:
        with benchmark_file.open("rb") as f:
            files = {"benchmark_file": (benchmark_file.name, f, "application/json")}
            data = {
                "search_space_id": str(search_space_id),
                "etl_services": json.dumps(etl_services),
                "chunking_strategies": json.dumps(chunking_strategies),
                "embedding_models": json.dumps(embedding_models),
                "chunk_sizes": json.dumps(chunk_sizes),
                "ranking_variants": json.dumps(ranking_variants),
                "max_questions": str(max_questions),
                "start_question": "1",
                "subagent_workers": "4",
                "benchmark_workers": "1",
                "request_timeout": "240",
                "sanitize_questions": "true",
                "cleanup_documents": "false",
                "run_prefix": run_prefix,
                "output_dir": "benchmark_results_master_agent",
            }
            response = self.request("POST", "/api/v1/benchmark/jobs", data=data, files=files, timeout=300)
            payload = response.json()
            job_id = payload.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise RuntimeError(f"Unexpected benchmark create response: {payload}")
            return job_id

    def get_benchmark_job(self, job_id: str) -> dict[str, Any]:
        response = self.request("GET", f"/api/v1/benchmark/jobs/{job_id}")
        return response.json()


def _wait_for_document_states(
    api: ApiClient,
    search_space_id: int,
    document_ids: list[int],
    timeout_seconds: int,
    poll_interval: float,
    debug: bool = False,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    target_ids = set(document_ids)
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        docs = api.list_documents(search_space_id)
        by_id = {int(doc["id"]): doc for doc in docs if int(doc.get("id", -1)) in target_ids}
        states: dict[int, str | None] = {}
        for doc_id in target_ids:
            doc = by_id.get(doc_id)
            status = doc.get("status") if isinstance(doc, dict) else None
            state = status.get("state") if isinstance(status, dict) else None
            states[doc_id] = state
        if debug and (attempt == 1 or attempt % 5 == 0):
            print(f"[{_now_utc()}] [debug] processing_wait attempt={attempt} states={states}")
        if states and all(value in {"ready", "failed"} for value in states.values()):
            return {
                "completed": True,
                "states": {str(k): v for k, v in states.items()},
                "documents": by_id,
            }
        time.sleep(poll_interval)
    return {
        "completed": False,
        "states": {},
        "documents": {},
    }


def _wait_for_deletion(
    api: ApiClient,
    search_space_id: int,
    source_key: str,
    timeout_seconds: int,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        docs = api.list_documents(search_space_id)
        still_present = [
            doc
            for doc in docs
            if isinstance(doc.get("title"), str)
            and (doc["title"] == source_key or doc["title"].startswith(f"{source_key}__"))
        ]
        if not still_present:
            return {"completed": True, "remaining": []}
        time.sleep(poll_interval)
    docs = api.list_documents(search_space_id)
    still_present = [
        doc
        for doc in docs
        if isinstance(doc.get("title"), str)
        and (doc["title"] == source_key or doc["title"].startswith(f"{source_key}__"))
    ]
    return {"completed": False, "remaining": still_present}


def _wait_for_full_deletion_confirmation(
    *,
    api: ApiClient,
    search_space_id: int,
    source_key: str,
    document_ids: list[int],
    pipeline_ids: list[str],
    db_targets: list[dict[str, Any]],
    opensearch_hosts: list[str],
    timeout_seconds: int,
    poll_interval: float,
    debug: bool = False,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    attempts = 0
    last_snapshot: dict[str, Any] = {
        "api": {"completed": False, "remaining": []},
        "db": {"ok": False, "error": "not-checked"},
        "opensearch": {"ok": False, "error": "not-checked"},
    }

    while time.time() < deadline:
        attempts += 1
        api_check = _wait_for_deletion(
            api=api,
            search_space_id=search_space_id,
            source_key=source_key,
            timeout_seconds=1,
            poll_interval=0,
        )
        db_check = _query_db_counts(db_targets, document_ids)
        os_check = _query_opensearch_counts(
            opensearch_hosts=opensearch_hosts,
            search_space_id=search_space_id,
            document_ids=document_ids,
            pipeline_ids=pipeline_ids,
            timeout=15,
        )

        api_confirmed = bool(api_check.get("completed"))
        db_confirmed = bool(db_check.get("ok")) and db_check.get("documents") == 0 and db_check.get("chunks") == 0
        os_confirmed = bool(os_check.get("ok")) and os_check.get("document_count") == 0

        last_snapshot = {
            "api": api_check,
            "db": db_check,
            "opensearch": os_check,
            "api_confirmed": api_confirmed,
            "db_confirmed": db_confirmed,
            "opensearch_confirmed": os_confirmed,
        }

        if debug and (attempts == 1 or attempts % 5 == 0):
            print(
                f"[{_now_utc()}] [debug] delete_confirm attempt={attempts} "
                f"api_done={api_confirmed} db=({db_check.get('documents')},{db_check.get('chunks')}) "
                f"os_doc={os_check.get('document_count')}"
            )

        if api_confirmed and db_confirmed and os_confirmed:
            return {
                "confirmed": True,
                "attempts": attempts,
                "api": api_check,
                "db": db_check,
                "opensearch": os_check,
                "last_snapshot": last_snapshot,
            }

        time.sleep(poll_interval)

    return {
        "confirmed": False,
        "attempts": attempts,
        "api": last_snapshot.get("api", {}),
        "db": last_snapshot.get("db", {}),
        "opensearch": last_snapshot.get("opensearch", {}),
        "last_snapshot": last_snapshot,
        "error": "Timed out waiting for full deletion confirmation",
    }


def _source_key_from_filename(filename: str) -> str:
    return filename.rsplit(".", 1)[0]


def _query_db_counts(db_targets: list[dict[str, Any]], document_ids: list[int]) -> dict[str, Any]:
    if not document_ids:
        return {"ok": False, "error": "no document ids", "host": None}
    placeholder = ",".join(["%s"] * len(document_ids))
    sql_docs = f"SELECT COUNT(*) FROM documents WHERE id IN ({placeholder})"
    sql_chunks = f"SELECT COUNT(*) FROM chunks WHERE document_id IN ({placeholder})"

    for target in db_targets:
        try:
            with psycopg.connect(
                host=target["host"],
                port=target["port"],
                dbname=target["dbname"],
                user=target["user"],
                password=target["password"],
                connect_timeout=4,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql_docs, document_ids)
                    doc_count = int(cur.fetchone()[0])
                    cur.execute(sql_chunks, document_ids)
                    chunk_count = int(cur.fetchone()[0])
            return {
                "ok": True,
                "host": f"{target['host']}:{target['port']}",
                "documents": doc_count,
                "chunks": chunk_count,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

    return {
        "ok": False,
        "host": None,
        "error": last_error if "last_error" in locals() else "unknown db error",
    }


def _query_opensearch_counts(
    opensearch_hosts: list[str],
    search_space_id: int,
    document_ids: list[int],
    pipeline_ids: list[str],
    timeout: float,
) -> dict[str, Any]:
    doc_should = [{"term": {"document_id": str(doc_id)}} for doc_id in document_ids]
    pipeline_should = [{"term": {"pipeline_id": pipeline_id}} for pipeline_id in pipeline_ids]
    if not doc_should and not pipeline_should:
        return {"ok": False, "error": "no doc or pipeline ids", "host": None}

    doc_query = {"query": {"bool": {"should": doc_should, "minimum_should_match": 1}}}
    pipeline_query = {
        "query": {"bool": {"should": pipeline_should, "minimum_should_match": 1}}
    }
    index_path = f"/surfsense_chunks_{search_space_id}*/_count"
    for host in opensearch_hosts:
        try:
            doc_count = 0
            if doc_should:
                doc_url = f"{host}{index_path}"
                doc_response = requests.post(doc_url, json=doc_query, timeout=timeout)
                if doc_response.status_code >= 400:
                    last_error = f"{doc_response.status_code}: {doc_response.text[:200]}"
                    continue
                doc_count = int(doc_response.json().get("count", 0))

            pipeline_count = None
            if pipeline_should:
                pipeline_url = f"{host}{index_path}"
                pipeline_response = requests.post(pipeline_url, json=pipeline_query, timeout=timeout)
                if pipeline_response.status_code < 400:
                    pipeline_count = int(pipeline_response.json().get("count", 0))

            return {
                "ok": True,
                "host": host,
                "document_count": doc_count,
                "pipeline_count": pipeline_count,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
    return {
        "ok": False,
        "host": None,
        "error": last_error if "last_error" in locals() else "unknown opensearch error",
    }


def _wait_for_benchmark_completion(
    api: ApiClient,
    job_id: str,
    timeout_seconds: int,
    poll_interval: float,
    debug: bool = False,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_payload: dict[str, Any] | None = None
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        payload = api.get_benchmark_job(job_id)
        last_payload = payload
        status = payload.get("status")
        if debug and (attempt == 1 or attempt % 3 == 0):
            print(
                f"[{_now_utc()}] [debug] benchmark_wait attempt={attempt} "
                f"status={status} stage={payload.get('stage')} progress={payload.get('progress_percent')}"
            )
        if status in {"completed", "failed"}:
            return payload
        time.sleep(poll_interval)
    if last_payload is None:
        return {"status": "failed", "error": "No benchmark status payload returned"}
    last_payload["status"] = "failed"
    last_payload["error"] = "Timed out waiting for benchmark completion"
    return last_payload


def _cleanup_existing_docs(api: ApiClient, search_space_id: int, source_key: str) -> dict[str, Any]:
    docs = api.list_documents(search_space_id)
    candidates = [
        doc
        for doc in docs
        if isinstance(doc.get("title"), str)
        and (doc["title"] == source_key or doc["title"].startswith(f"{source_key}__"))
    ]
    if not candidates:
        return {"queued": 0, "ids": []}

    queued = 0
    queued_ids: list[int] = []
    for doc in candidates:
        doc_id = int(doc["id"])
        try:
            api.delete_document(doc_id)
            queued += 1
            queued_ids.append(doc_id)
        except Exception:
            continue

    return {"queued": queued, "ids": queued_ids}


def run_cycle(
    *,
    cycle_num: int,
    api: ApiClient,
    search_space_id: int,
    document_path: Path,
    benchmark_file: Path,
    db_targets: list[dict[str, Any]],
    opensearch_hosts: list[str],
    etl_services: list[str],
    chunking_strategies: list[str],
    chunk_sizes: list[int],
    embedding_models: list[str],
    ranking_variants: list[str],
    max_questions: int,
    process_timeout: int,
    delete_timeout: int,
    benchmark_timeout: int,
    poll_interval: float,
    debug: bool = False,
) -> dict[str, Any]:
    started = _now_utc()
    cycle_started_mono = time.monotonic()
    source_key = _source_key_from_filename(document_path.name)
    debug_events: list[dict[str, Any]] = []

    def record_event(stage: str, **payload: Any) -> None:
        debug_events.append(
            {
                "ts": _now_utc(),
                "elapsed_s": _elapsed_seconds(cycle_started_mono),
                "stage": stage,
                **payload,
            }
        )

    record_event(
        "cycle_start",
        cycle=cycle_num,
        source_key=source_key,
        search_space_id=search_space_id,
    )
    if debug:
        print(f"[{_now_utc()}] [debug] cycle_start cycle={cycle_num} source_key={source_key}")

    cleanup = _cleanup_existing_docs(api, search_space_id, source_key)
    record_event("pre_cleanup", queued=cleanup.get("queued", 0), ids=cleanup.get("ids", []))
    if debug:
        print(f"[{_now_utc()}] [debug] pre_cleanup queued={cleanup.get('queued', 0)} ids={cleanup.get('ids', [])}")
    if cleanup["queued"]:
        pre_wait = _wait_for_deletion(api, search_space_id, source_key, delete_timeout, poll_interval)
        record_event(
            "pre_cleanup_wait",
            completed=pre_wait.get("completed"),
            remaining=len(pre_wait.get("remaining", [])),
        )

    upload_payload = api.upload_variants(
        search_space_id=search_space_id,
        document_path=document_path,
        etl_services=etl_services,
        chunking_strategies=chunking_strategies,
        chunk_sizes=chunk_sizes,
        embedding_models=embedding_models,
    )
    if debug:
        print(
            f"[{_now_utc()}] [debug] upload_done pending={upload_payload.get('pending_files')} "
            f"total={upload_payload.get('total_files')} skipped={upload_payload.get('skipped_duplicates')}"
        )
    record_event(
        "upload_done",
        pending_files=upload_payload.get("pending_files"),
        total_files=upload_payload.get("total_files"),
        skipped_duplicates=upload_payload.get("skipped_duplicates"),
    )

    document_ids = sorted({int(x) for x in upload_payload.get("document_ids", [])})
    pipeline_jobs = upload_payload.get("pipeline_jobs", [])
    pipeline_ids = [
        job.get("pipeline_id")
        for job in pipeline_jobs
        if isinstance(job, dict) and isinstance(job.get("pipeline_id"), str)
    ]
    pipeline_ids = sorted(set(pipeline_ids))
    record_event(
        "upload_entities",
        document_ids=document_ids,
        pipeline_count=len(pipeline_ids),
    )

    processing = _wait_for_document_states(
        api=api,
        search_space_id=search_space_id,
        document_ids=document_ids,
        timeout_seconds=process_timeout,
        poll_interval=poll_interval,
        debug=debug,
    )
    record_event(
        "processing_wait_done",
        completed=processing.get("completed"),
        states=processing.get("states", {}),
    )

    db_after_upload = _query_db_counts(db_targets, document_ids)
    os_after_upload = _query_opensearch_counts(
        opensearch_hosts=opensearch_hosts,
        search_space_id=search_space_id,
        document_ids=document_ids,
        pipeline_ids=pipeline_ids,
        timeout=15,
    )
    record_event(
        "post_upload_counts",
        db=db_after_upload,
        opensearch=os_after_upload,
    )

    run_prefix = f"local_cycle_{cycle_num}_{int(time.time())}_{random.randint(100, 999)}"
    job_id = api.create_benchmark_job(
        benchmark_file=benchmark_file,
        search_space_id=search_space_id,
        etl_services=etl_services,
        chunking_strategies=chunking_strategies,
        embedding_models=embedding_models,
        chunk_sizes=chunk_sizes,
        ranking_variants=ranking_variants,
        max_questions=max_questions,
        run_prefix=run_prefix,
    )
    benchmark_payload = _wait_for_benchmark_completion(
        api=api,
        job_id=job_id,
        timeout_seconds=benchmark_timeout,
        poll_interval=poll_interval,
        debug=debug,
    )
    record_event(
        "benchmark_done",
        job_id=job_id,
        status=benchmark_payload.get("status"),
        error=benchmark_payload.get("error"),
    )

    delete_result: dict[str, Any]
    if document_ids:
        delete_result = api.delete_document(document_ids[0])
    else:
        delete_result = {"message": "No document IDs from upload response", "queued_deletions": 0}
    record_event("delete_queued", delete_result=delete_result)

    deletion_confirmation = _wait_for_full_deletion_confirmation(
        api=api,
        search_space_id=search_space_id,
        source_key=source_key,
        document_ids=document_ids,
        pipeline_ids=pipeline_ids,
        db_targets=db_targets,
        opensearch_hosts=opensearch_hosts,
        timeout_seconds=delete_timeout,
        poll_interval=poll_interval,
        debug=debug,
    )

    deletion_wait = deletion_confirmation.get("api", {})
    db_after_delete = deletion_confirmation.get("db", {})
    os_after_delete = deletion_confirmation.get("opensearch", {})
    record_event(
        "delete_confirmation_done",
        confirmed=deletion_confirmation.get("confirmed"),
        attempts=deletion_confirmation.get("attempts"),
        api=deletion_wait,
        db=db_after_delete,
        opensearch=os_after_delete,
    )

    benchmark_status = benchmark_payload.get("status")
    benchmark_error = benchmark_payload.get("error")
    ranked_reports = benchmark_payload.get("ranked_subagent_reports")
    candidate_count = len(ranked_reports) if isinstance(ranked_reports, list) else 0
    recommended_pipeline = benchmark_payload.get("recommended_pipeline_id")

    completed = _now_utc()
    failure_reasons: list[str] = []
    if not document_ids:
        failure_reasons.append("no_document_ids_returned")
    if processing.get("completed") is not True:
        failure_reasons.append("processing_not_completed")
    if benchmark_status != "completed":
        failure_reasons.append("benchmark_not_completed")
    if deletion_confirmation.get("confirmed") is not True:
        failure_reasons.append("delete_confirmation_timeout")
    if db_after_delete.get("ok") and not (
        db_after_delete.get("documents") == 0 and db_after_delete.get("chunks", 0) == 0
    ):
        failure_reasons.append("postgres_residual_rows")
    if os_after_delete.get("ok") and os_after_delete.get("document_count") != 0:
        failure_reasons.append("opensearch_residual_chunks")

    success = (
        bool(document_ids)
        and processing.get("completed") is True
        and benchmark_status == "completed"
        and deletion_confirmation.get("confirmed") is True
        and (
            (not db_after_delete.get("ok"))
            or (
                db_after_delete.get("documents") == 0 and db_after_delete.get("chunks", 0) == 0
            )
        )
        and ((not os_after_delete.get("ok")) or os_after_delete.get("document_count") == 0)
    )
    record_event(
        "cycle_complete",
        success=success,
        failure_reasons=failure_reasons,
        total_elapsed_s=_elapsed_seconds(cycle_started_mono),
    )

    return {
        "cycle": cycle_num,
        "started_at": started,
        "completed_at": completed,
        "elapsed_seconds": _elapsed_seconds(cycle_started_mono),
        "success": success,
        "failure_reasons": failure_reasons,
        "upload": {
            "response": upload_payload,
            "document_ids": document_ids,
            "pipeline_ids": pipeline_ids,
        },
        "processing": processing,
        "db_after_upload": db_after_upload,
        "opensearch_after_upload": os_after_upload,
        "benchmark": {
            "job_id": job_id,
            "status": benchmark_status,
            "error": benchmark_error,
            "candidate_count": candidate_count,
            "recommended_pipeline_id": recommended_pipeline,
        },
        "delete": {
            "api": delete_result,
            "wait": deletion_wait,
            "confirmation": deletion_confirmation,
        },
        "db_after_delete": db_after_delete,
        "opensearch_after_delete": os_after_delete,
        "debug_events": debug_events,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local 10-cycle upload/benchmark/delete verification")
    parser.add_argument("--config", default="benchmark_runner_config.json")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--searchspace", default=None)
    parser.add_argument("--document", default="MSFT_FY26Q1_10Q.docx")
    parser.add_argument("--benchmark-file", default="msft_fy26q1_qa_benchmark_100_sanitized.json")
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--max-questions", type=int, default=2)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--process-timeout", type=int, default=420)
    parser.add_argument("--benchmark-timeout", type=int, default=1200)
    parser.add_argument("--delete-timeout", type=int, default=300)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--output", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    config = _load_json_file(Path(args.config))
    dotenv_values = _load_dotenv(Path(args.dotenv))

    base_url = args.base_url or config.get("BASE_URL") or "http://localhost:8930"
    username = args.username or config.get("USERNAME")
    password = args.password or config.get("PASSWORD")
    searchspace_name = args.searchspace or config.get("SEARCHSPACE")
    if not username or not password or not searchspace_name:
        print("ERROR: Missing username/password/searchspace. Provide via args or benchmark_runner_config.json")
        return 2

    document_path = Path(args.document)
    benchmark_file = Path(args.benchmark_file)
    if not document_path.exists():
        print(f"ERROR: document file not found: {document_path}")
        return 2
    if not benchmark_file.exists():
        print(f"ERROR: benchmark file not found: {benchmark_file}")
        return 2

    etl_services = ["DOCLING"]
    chunking_strategies = ["chunk_text", "sandwitch_chunk"]
    chunk_sizes = [256, 1024]
    embedding_models = ["fastembed/all-MiniLM-L6-v2"]
    ranking_variants = ["hybrid_rrf_plus", "hybrid_weighted"]

    db_targets = _extract_db_targets(dotenv_values)
    opensearch_hosts = _extract_opensearch_hosts(dotenv_values)

    api = ApiClient(base_url=base_url, timeout=180)
    print(f"[{_now_utc()}] Logging in to {base_url} as {username}")
    api.login(username, password)
    search_space_id = api.get_search_space_id(searchspace_name)
    print(f"[{_now_utc()}] Resolved search space '{searchspace_name}' -> id={search_space_id}")

    run_started = _now_utc()
    all_cycles: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for cycle in range(1, args.cycles + 1):
        print(f"\n[{_now_utc()}] ===== Cycle {cycle}/{args.cycles} =====")
        try:
            cycle_start = time.monotonic()
            result = run_cycle(
                cycle_num=cycle,
                api=api,
                search_space_id=search_space_id,
                document_path=document_path,
                benchmark_file=benchmark_file,
                db_targets=db_targets,
                opensearch_hosts=opensearch_hosts,
                etl_services=etl_services,
                chunking_strategies=chunking_strategies,
                chunk_sizes=chunk_sizes,
                embedding_models=embedding_models,
                ranking_variants=ranking_variants,
                max_questions=args.max_questions,
                process_timeout=args.process_timeout,
                delete_timeout=args.delete_timeout,
                benchmark_timeout=args.benchmark_timeout,
                poll_interval=args.poll_interval,
                debug=args.debug,
            )
            all_cycles.append(result)
            status = "PASS" if result.get("success") else "FAIL"
            doc_ids = result.get("upload", {}).get("document_ids", [])
            pipelines = result.get("upload", {}).get("pipeline_ids", [])
            bench_status = result.get("benchmark", {}).get("status")
            fail_reasons = result.get("failure_reasons", [])
            os_after_delete = result.get("opensearch_after_delete", {})
            os_count_after_delete = os_after_delete.get("document_count")
            os_pipeline_after_delete = os_after_delete.get("pipeline_count")
            db_after_delete = result.get("db_after_delete", {})
            delete_confirm = result.get("delete", {}).get("confirmation", {})
            db_summary = (
                f"docs={db_after_delete.get('documents')} chunks={db_after_delete.get('chunks')}"
                if db_after_delete.get("ok")
                else f"unavailable({db_after_delete.get('error')})"
            )
            print(
                f"[{_now_utc()}] Cycle {cycle} {status} | doc_ids={doc_ids} | pipelines={len(pipelines)} "
                f"| benchmark={bench_status} | DB after delete {db_summary} "
                f"| OS doc after delete={os_count_after_delete} | OS pipeline after delete={os_pipeline_after_delete} "
                f"| delete_confirmed={delete_confirm.get('confirmed')} attempts={delete_confirm.get('attempts')} "
                f"| elapsed_s={round(time.monotonic() - cycle_start, 3)}"
            )
            if fail_reasons:
                print(f"[{_now_utc()}] Cycle {cycle} failure_reasons={','.join(fail_reasons)}")
            if args.debug:
                debug_events = result.get("debug_events", [])
                print(f"[{_now_utc()}] Cycle {cycle} debug_events={len(debug_events)}")
                for event in debug_events[-6:]:
                    print(
                        f"  - t+{event.get('elapsed_s')}s stage={event.get('stage')} details="
                        f"{json.dumps({k: v for k, v in event.items() if k not in {'ts', 'elapsed_s', 'stage'}}, default=str)[:500]}"
                    )
            if not result.get("success"):
                failures.append(result)
        except Exception as exc:
            failure = {
                "cycle": cycle,
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "started_at": _now_utc(),
                "completed_at": _now_utc(),
            }
            all_cycles.append(failure)
            failures.append(failure)
            print(f"[{_now_utc()}] Cycle {cycle} FAIL with exception: {failure['error']}")

    run_completed = _now_utc()
    report = {
        "run_started_at": run_started,
        "run_completed_at": run_completed,
        "base_url": base_url,
        "search_space": {"name": searchspace_name, "id": search_space_id},
        "document": str(document_path),
        "benchmark_file": str(benchmark_file),
        "cycles": args.cycles,
        "max_questions": args.max_questions,
        "pipeline_spec": {
            "etl_services": etl_services,
            "chunking_strategies": chunking_strategies,
            "chunk_sizes": chunk_sizes,
            "embedding_models": embedding_models,
            "ranking_variants": ranking_variants,
        },
        "summary": {
            "passed": args.cycles - len(failures),
            "failed": len(failures),
        },
        "cycles_detail": all_cycles,
    }

    output_path = Path(args.output) if args.output else Path(f"local_10cycle_report_{int(time.time())}.json")
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n===== Final Summary =====")
    print(f"Run started:   {run_started}")
    print(f"Run completed: {run_completed}")
    print(f"Passed: {report['summary']['passed']} / {args.cycles}")
    print(f"Failed: {report['summary']['failed']} / {args.cycles}")
    print(f"Report: {output_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
