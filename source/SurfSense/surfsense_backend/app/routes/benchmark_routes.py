from __future__ import annotations

import json
import asyncio
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import redis as _redis_lib
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import BenchmarkData, Document, Permission, User, get_async_session
from app.users import current_active_user
from app.utils.rbac import check_permission

router = APIRouter()


class BenchmarkJobCreateResponse(BaseModel):
    job_id: str
    status: str


class BenchmarkJobStatusResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    message: str
    progress_percent: int = Field(ge=0, le=100)
    total_candidates: int = 0
    completed_candidates: int = 0
    eta_seconds: int | None = None
    run_prefix: str | None = None
    output_dir: str | None = None
    summary_json_path: str | None = None
    summary_md_path: str | None = None
    recommended_pipeline_id: str | None = None
    ranked_subagent_reports: list[dict[str, Any]] | None = None
    candidates_status: list[dict[str, Any]] | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class BenchmarkAvailableOptionsResponse(BaseModel):
    search_space_id: int
    document_id: int | None = None
    source: str
    etl_services: list[str]
    chunking_strategies: list[str]
    chunk_sizes: list[int]
    embedding_models: list[str]
    pipeline_ids: list[str]
    ranking_variants: list[str]


_BENCHMARK_JOB_TTL = 86400  # 24 hours — jobs survive backend restarts
_BENCHMARK_KEY_PREFIX = "surfsense:benchmark_job:"
_INTERNAL_API_BASE_URL = "http://localhost:8000"
_BENCHMARK_RANKING_VARIANTS = ["hybrid_rrf_plus", "hybrid_weighted"]
_BENCHMARK_MAX_IN_FLIGHT = 12
_BENCHMARK_MEM_GIB_PER_QUESTION_WORKER = 1.5

# Lazy Redis client — one sync connection pool, shared across threads.
_redis_client: _redis_lib.Redis | None = None
_redis_lock = threading.Lock()


def _get_redis() -> _redis_lib.Redis:
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                # Bounded pool: benchmark threads use sync Redis, but we don't want
                # them to exhaust connections used by the async GET/WS handlers.
                pool = _redis_lib.ConnectionPool.from_url(
                    url, decode_responses=True, max_connections=20
                )
                _redis_client = _redis_lib.Redis(connection_pool=pool)
    return _redis_client


def _job_key(job_id: str) -> str:
    return f"{_BENCHMARK_KEY_PREFIX}{job_id}"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _serialize_field(v: Any) -> str:
    """Serialize any value to a JSON string for storage in a Redis Hash field."""
    return json.dumps(v, default=str)


def _deserialize_field(v: str) -> Any:
    try:
        return json.loads(v)
    except (json.JSONDecodeError, ValueError):
        return v


def _candidate_key(job_key: str, pipeline_id: str) -> str:
    return f"{job_key}:c:{pipeline_id}"


def _create_job(job_id: str, initial_job: dict[str, Any]) -> None:
    """Write the initial job state to a Redis Hash. Called once at job creation."""
    r = _get_redis()
    key = _job_key(job_id)
    # Don't store candidates_status as a field — it lives in per-candidate hashes.
    initial_job.pop("candidates_status", None)
    mapping = {k: _serialize_field(v) for k, v in initial_job.items()}
    pipe = r.pipeline()
    pipe.hset(key, mapping=mapping)
    pipe.expire(key, _BENCHMARK_JOB_TTL)
    pipe.execute()


# Sentinel used to distinguish "not passed" from None
_SENTINEL: Any = object()


def _update_job(job_id: str, **updates: Any) -> None:
    """Patch specific scalar fields in the job Hash.
    candidates_status (list[dict]) is handled separately — each candidate
    gets its own Hash key so updates never conflict with each other.
    No read-modify-write anywhere; HSET is atomic per-field.
    """
    r = _get_redis()
    key = _job_key(job_id)

    # candidates_status requires special treatment: initialize per-candidate hashes
    candidates_list = updates.pop("candidates_status", _SENTINEL)

    if updates:
        mapping = {k: _serialize_field(v) for k, v in updates.items()}
        pipe = r.pipeline()
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, _BENCHMARK_JOB_TTL)
        pipe.execute()

    if candidates_list is not _SENTINEL and isinstance(candidates_list, list):
        pids = [c["pipeline_id"] for c in candidates_list]
        pipe = r.pipeline()
        # Store ordered pipeline_id list in the main hash
        pipe.hset(key, "candidate_ids", _serialize_field(pids))
        pipe.expire(key, _BENCHMARK_JOB_TTL)
        # Create one Hash per candidate
        for c in candidates_list:
            ckey = _candidate_key(key, c["pipeline_id"])
            pipe.hset(ckey, mapping={k: _serialize_field(v) for k, v in c.items()})
            pipe.expire(ckey, _BENCHMARK_JOB_TTL)
        pipe.execute()


def _update_candidate_status(job_id: str, pipeline_id: str, **updates: Any) -> None:
    """Update individual fields of a single candidate Hash.
    Each candidate is its own Redis Hash key so concurrent updates from different
    worker threads never conflict — HSET writes disjoint keys simultaneously.
    """
    r = _get_redis()
    ckey = _candidate_key(_job_key(job_id), pipeline_id)
    mapping = {k: _serialize_field(v) for k, v in updates.items()}
    pipe = r.pipeline()
    pipe.hset(ckey, mapping=mapping)
    pipe.expire(ckey, _BENCHMARK_JOB_TTL)
    pipe.execute()


def _get_job(job_id: str) -> dict[str, Any] | None:
    """Read the job Hash plus all per-candidate Hashes and return a unified dict."""
    r = _get_redis()
    key = _job_key(job_id)
    try:
        raw = r.hgetall(key)
    except Exception:
        # Key exists but is a STRING (old format from before the Hash migration).
        # Try to read it as JSON; if that also fails, return None.
        try:
            raw_str = r.get(key)
            if raw_str is None:
                return None
            return json.loads(raw_str)
        except Exception:
            return None

    if not raw:
        return None
    job: dict[str, Any] = {k: _deserialize_field(v) for k, v in raw.items()}

    # Load per-candidate hashes in insertion order
    pids: list[str] = job.pop("candidate_ids", None) or []
    if pids:
        pipe = r.pipeline()
        for pid in pids:
            pipe.hgetall(_candidate_key(key, pid))
        results = pipe.execute()
        candidates = []
        for craw in results:
            if craw:
                candidates.append({k: _deserialize_field(v) for k, v in craw.items()})
        job["candidates_status"] = candidates or None
    else:
        job["candidates_status"] = None
    return job


def _parse_csv_or_json_list(raw: str | None, *, item_type: type = str) -> list[Any]:
    if raw is None:
        return []
    value = raw.strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [item_type(v) for v in parsed]
        if isinstance(parsed, str):
            return [item_type(parsed)]
    except json.JSONDecodeError:
        pass
    return [item_type(part.strip()) for part in value.split(",") if part.strip()]


def _is_reachable_http_base(url: str, timeout_seconds: float = 0.5) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((parsed.hostname, port), timeout=timeout_seconds):
            return True
    except Exception:
        return False


def _resolve_internal_api_base_url() -> str:
    candidates: list[str] = []

    # Highest priority: explicit runtime override.
    for env_key in (
        "BENCHMARK_INTERNAL_API_BASE_URL",
        "INTERNAL_API_BASE_URL",
        "FASTAPI_BACKEND_URL",
        "NEXT_PUBLIC_FASTAPI_BACKEND_URL",
    ):
        value = os.getenv(env_key)
        if value:
            candidates.append(value.rstrip("/"))

    # Known local defaults across dev/prod setups.
    candidates.extend(
        [
            _INTERNAL_API_BASE_URL,
            "http://127.0.0.1:8000",
            "http://localhost:8930",
            "http://127.0.0.1:8930",
        ]
    )

    seen: set[str] = set()
    unique_candidates: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)

    for candidate in unique_candidates:
        if _is_reachable_http_base(candidate):
            return candidate

    return _INTERNAL_API_BASE_URL


def _read_mem_available_gib() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        kib = int(parts[1])
                        return kib / (1024 * 1024)
    except Exception:
        return None
    return None


def _compute_effective_worker_counts(
    requested_subagent_workers: int,
    requested_benchmark_workers: int,
) -> tuple[int, int]:
    cpu_total = max(1, os.cpu_count() or 1)

    # Keep headroom for API/event loop, OpenSearch client, and host processes.
    cpu_reserve = max(2, cpu_total // 4)
    cpu_budget = max(1, cpu_total - cpu_reserve)

    effective_subagent_workers = max(1, min(requested_subagent_workers, cpu_budget))

    max_by_cpu = max(1, cpu_budget // effective_subagent_workers)
    max_by_inflight = max(1, _BENCHMARK_MAX_IN_FLIGHT // effective_subagent_workers)

    mem_available_gib = _read_mem_available_gib()
    if mem_available_gib is None:
        max_by_mem = max_by_cpu
    else:
        max_by_mem_total = max(1, int(mem_available_gib // _BENCHMARK_MEM_GIB_PER_QUESTION_WORKER))
        max_by_mem = max(1, max_by_mem_total // effective_subagent_workers)

    benchmark_cap = max(1, min(max_by_cpu, max_by_mem, max_by_inflight))
    effective_benchmark_workers = max(1, min(requested_benchmark_workers, benchmark_cap))

    return effective_subagent_workers, effective_benchmark_workers


def _extract_options_from_metadata(
    metadata: dict[str, Any] | None,
) -> tuple[set[str], set[str], set[int], set[str], set[str]]:
    etl_services: set[str] = set()
    chunking: set[str] = set()
    chunk_sizes: set[int] = set()
    embedding_models: set[str] = set()
    pipeline_ids: set[str] = set()

    if not isinstance(metadata, dict):
        return etl_services, chunking, chunk_sizes, embedding_models, pipeline_ids

    raw_etl = metadata.get("ETL_SERVICE")
    if isinstance(raw_etl, str) and raw_etl.strip():
        etl_services.add(raw_etl.strip().upper())

    raw_pipeline_ids = metadata.get("pipeline_ids")
    if isinstance(raw_pipeline_ids, list):
        for value in raw_pipeline_ids:
            if isinstance(value, str) and value.strip():
                pipeline_ids.add(value.strip())

    signatures = metadata.get("pipeline_signatures")
    if not isinstance(signatures, list):
        return etl_services, chunking, chunk_sizes, embedding_models, pipeline_ids

    for signature in signatures:
        if not isinstance(signature, dict):
            continue

        etl_service = signature.get("etl_service")
        if isinstance(etl_service, str) and etl_service.strip():
            etl_services.add(etl_service.strip().upper())

        strategy = signature.get("chunking_strategy")
        if isinstance(strategy, str) and strategy.strip():
            chunking.add(strategy.strip())

        strategies = signature.get("chunking_strategies")
        if isinstance(strategies, list):
            for item in strategies:
                if isinstance(item, str) and item.strip():
                    chunking.add(item.strip())

        chunk_size = signature.get("chunk_size")
        if isinstance(chunk_size, int):
            chunk_sizes.add(chunk_size)

        models = signature.get("embedding_models")
        if isinstance(models, list):
            for model in models:
                if isinstance(model, str) and model.strip():
                    embedding_models.add(model.strip())

    return etl_services, chunking, chunk_sizes, embedding_models, pipeline_ids


async def _load_options_from_metadata(
    session: AsyncSession,
    search_space_id: int,
    document_id: int | None,
) -> tuple[list[str], list[str], list[int], list[str], list[str]]:
    query = select(Document.id, Document.document_metadata).where(Document.search_space_id == search_space_id)
    if document_id is not None:
        query = query.where(Document.id == document_id)

    rows = (await session.execute(query)).all()
    etl_services: set[str] = set()
    chunking: set[str] = set()
    chunk_sizes: set[int] = set()
    embedding_models: set[str] = set()
    pipeline_ids: set[str] = set()

    for _, metadata in rows:
        m_etl, m_chunking, m_chunk_sizes, m_embedding, m_pipeline_ids = _extract_options_from_metadata(metadata)
        etl_services.update(m_etl)
        chunking.update(m_chunking)
        chunk_sizes.update(m_chunk_sizes)
        embedding_models.update(m_embedding)
        pipeline_ids.update(m_pipeline_ids)

    return (
        sorted(etl_services),
        sorted(chunking),
        sorted(chunk_sizes),
        sorted(embedding_models),
        sorted(pipeline_ids),
    )


async def _load_options_from_opensearch(
    search_space_id: int,
    document_id: int | None,
) -> tuple[list[str], list[str], list[int], list[str], list[str]]:
    from opensearch_multi_embedding_storage import MultiEmbeddingOpenSearchStorage

    raw_hosts = os.getenv("OPENSEARCH_HOSTS", "http://opensearch:9200")
    hosts = [host.strip() for host in raw_hosts.split(",") if host.strip()]
    storage = MultiEmbeddingOpenSearchStorage(
        hosts=hosts,
        index_prefix=os.getenv("OPENSEARCH_INDEX_PREFIX", "surfsense"),
        use_ssl=os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true",
        verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true",
        username=os.getenv("OPENSEARCH_USERNAME") or None,
        password=os.getenv("OPENSEARCH_PASSWORD") or None,
    )

    index_pattern = f"{storage.index_prefix}_chunks_{search_space_id}*"
    query: dict[str, Any] = {"match_all": {}}
    if document_id is not None:
        query = {"term": {"document_id": str(document_id)}}

    body: dict[str, Any] = {
        "size": 0,
        "query": query,
        "aggs": {
            "etl_services_keyword": {"terms": {"field": "metadata.ETL_SERVICE.keyword", "size": 20}},
            "etl_services_plain": {"terms": {"field": "metadata.ETL_SERVICE", "size": 20}},
            "chunking_strategies": {"terms": {"field": "chunking_strategy", "size": 200}},
            "chunk_sizes": {"terms": {"field": "chunk_size", "size": 200}},
            "embedding_models": {"terms": {"field": "embedding_models", "size": 1000}},
            "pipeline_ids": {"terms": {"field": "pipeline_id", "size": 2000}},
        },
    }

    try:
        response = await storage.client.search(index=index_pattern, body=body, ignore_unavailable=True)
    finally:
        await storage.close()

    aggs = response.get("aggregations") or {}
    etl_services_keyword = [
        b.get("key")
        for b in (aggs.get("etl_services_keyword", {}).get("buckets") or [])
        if isinstance(b.get("key"), str)
    ]
    etl_services_plain = [
        b.get("key")
        for b in (aggs.get("etl_services_plain", {}).get("buckets") or [])
        if isinstance(b.get("key"), str)
    ]
    etl_services = etl_services_keyword + etl_services_plain
    chunking = [b.get("key") for b in (aggs.get("chunking_strategies", {}).get("buckets") or []) if isinstance(b.get("key"), str)]
    chunk_sizes = [b.get("key") for b in (aggs.get("chunk_sizes", {}).get("buckets") or []) if isinstance(b.get("key"), int)]
    embedding_models = [b.get("key") for b in (aggs.get("embedding_models", {}).get("buckets") or []) if isinstance(b.get("key"), str)]
    pipeline_ids = [b.get("key") for b in (aggs.get("pipeline_ids", {}).get("buckets") or []) if isinstance(b.get("key"), str)]
    return (
        sorted({value.strip().upper() for value in etl_services if value.strip()}),
        sorted(set(chunking)),
        sorted(set(chunk_sizes)),
        sorted(set(embedding_models)),
        sorted(set(pipeline_ids)),
    )


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _aggregate_benchmark_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    overall = sum(1 for item in items if item.get("metrics", {}).get("overall_correct"))
    number_match = sum(1 for item in items if item.get("metrics", {}).get("number_match"))
    unit_match = sum(1 for item in items if item.get("metrics", {}).get("unit_match"))
    normalized_exact = sum(1 for item in items if item.get("metrics", {}).get("normalized_exact"))
    mean_token_f1 = (
        sum(float(item.get("metrics", {}).get("token_f1", 0.0)) for item in items) / total if total else 0.0
    )
    return {
        "run": total,
        "overall_correct_count": overall,
        "overall_correct_rate": (overall / total) if total else 0.0,
        "number_match_count": number_match,
        "number_match_rate": (number_match / total) if total else 0.0,
        "unit_match_count": unit_match,
        "unit_match_rate": (unit_match / total) if total else 0.0,
        "normalized_exact_count": normalized_exact,
        "normalized_exact_rate": (normalized_exact / total) if total else 0.0,
        "mean_token_f1": mean_token_f1,
    }


def _build_candidates(
    etl_services: list[str],
    chunking_strategies: list[str],
    embedding_models: list[str],
    chunk_sizes: list[int],
    ranking_variants: list[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int, str]] = set()
    normalized_etls = [etl.strip().upper() for etl in etl_services if etl.strip()]
    if not normalized_etls:
        normalized_etls = ["DOCLING"]
    for etl_service in normalized_etls:
        for strategy in chunking_strategies:
            for model in embedding_models:
                for chunk_size in chunk_sizes:
                    for ranking in ranking_variants:
                        combo = (etl_service, strategy, model, chunk_size, ranking)
                        if combo in seen:
                            continue
                        seen.add(combo)
                        etl_slug = _slug(etl_service)
                        strategy_slug = _slug(strategy)
                        model_slug = _slug(model.replace("/", "_"))
                        size_slug = f"tok{chunk_size}"
                        ranking_slug = _slug(ranking)
                        candidates.append(
                            {
                                "pipeline_id": f"{etl_slug}__{strategy_slug}__{model_slug}__{size_slug}__{ranking_slug}",
                                "etl_service": etl_service,
                                "chunking_strategy": strategy,
                                "embedding_model": model,
                                "chunk_size": chunk_size,
                                "ranking_variant": ranking,
                                "etl_slug": etl_slug,
                                "strategy_slug": strategy_slug,
                                "model_slug": model_slug,
                                "size_slug": size_slug,
                                "ranking_slug": ranking_slug,
                            }
                        )
    return candidates


def _write_indexed_master_summary(output_dir: Path, run_prefix: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_json_path = output_dir / f"{run_prefix}__master_summary.json"
    summary_md_path = output_dir / f"{run_prefix}__master_summary.md"
    summary_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines: list[str] = [
        "# Self-Adaptive Master Agent Summary (Indexed-Only)",
        "",
        f"- Generated: {payload.get('generated_at_utc', '')}",
        f"- Search space: {payload.get('search_space_id', '')}",
        f"- Mode: {payload.get('mode', '')}",
        "",
        "## Ranked Subagents",
        "",
        "| Rank | Pipeline ID | Overall | Number | Mean F1 | Score |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for rank, report in enumerate(payload.get("ranked_subagent_reports", []), start=1):
        lines.append(
            "| {rank} | {pipeline_id} | {overall:.2%} | {number:.2%} | {f1:.4f} | {score:.4f} |".format(
                rank=rank,
                pipeline_id=str(report.get("pipeline_id", "")),
                overall=float(report.get("overall_correct_rate", 0.0) or 0.0),
                number=float(report.get("number_match_rate", 0.0) or 0.0),
                f1=float(report.get("mean_token_f1", 0.0) or 0.0),
                score=float(report.get("score", 0.0) or 0.0),
            )
        )
    summary_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_json_path, summary_md_path


def _run_indexed_only_job(
    *,
    job_id: str,
    auth_header: str | None,
    search_space_id: int,
    benchmark_file_path: Path,
    etl_services: list[str],
    chunking_strategies: list[str],
    embedding_models: list[str],
    chunk_sizes: list[int],
    ranking_variants: list[str],
    max_questions: int,
    start_question: int,
    request_timeout: float,
    sanitize_questions: bool,
    run_prefix: str,
    output_dir: Path,
    subagent_workers: int,
    internal_api_base_url: str,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    try:
        from scripts.run_surfsense_benchmark import (  # type: ignore
            SurfSenseClient,
            evaluate_answer,
            load_benchmark,
            write_outputs,
        )
    except ModuleNotFoundError:
        import re
        import urllib.error
        import urllib.parse
        import urllib.request
        from types import SimpleNamespace

        class SurfSenseClient:  # type: ignore[no-redef]
            def __init__(self, base_url: str, timeout: float = 180.0) -> None:
                self.base_url = base_url.rstrip("/")
                self.timeout = timeout
                self.token: str | None = None

            def _request(
                self,
                method: str,
                path: str,
                *,
                json_body: dict[str, Any] | None = None,
                params: dict[str, Any] | None = None,
                extra_headers: dict[str, str] | None = None,
            ) -> tuple[int, bytes, dict[str, str]]:
                url = f"{self.base_url}{path}"
                if params:
                    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
                    if query:
                        url = f"{url}?{query}"

                headers: dict[str, str] = {"Accept": "application/json"}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"

                payload: bytes | None = None
                if json_body is not None:
                    payload = json.dumps(json_body).encode("utf-8")
                    headers["Content-Type"] = "application/json"
                if extra_headers:
                    headers.update(extra_headers)

                req = urllib.request.Request(url, data=payload, headers=headers, method=method)
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        body = resp.read()
                        return int(resp.status), body, dict(resp.headers.items())
                except urllib.error.HTTPError as exc:
                    body = exc.read()
                    return int(exc.code), body, dict(exc.headers.items())

            def list_documents(self, search_space_id: int) -> list[dict[str, Any]]:
                status, body, _ = self._request(
                    "GET",
                    "/api/v1/documents",
                    params={"search_space_id": search_space_id, "page_size": -1},
                )
                if status != 200:
                    raise RuntimeError(f"Failed to list documents ({status}): {body.decode('utf-8', errors='replace')}")
                payload = json.loads(body.decode("utf-8"))
                return payload.get("items", [])

            def create_thread(self, search_space_id: int, title: str) -> int:
                status, body, _ = self._request(
                    "POST",
                    "/api/v1/threads",
                    json_body={
                        "search_space_id": search_space_id,
                        "title": title,
                        "visibility": "PRIVATE",
                        "archived": False,
                    },
                )
                if status != 200:
                    raise RuntimeError(f"Failed to create thread ({status}): {body.decode('utf-8', errors='replace')}")
                payload = json.loads(body.decode("utf-8"))
                thread_id = payload.get("id")
                if not isinstance(thread_id, int):
                    raise RuntimeError(f"Thread create response missing id: {payload}")
                return thread_id

            def list_messages(self, thread_id: int, limit: int = 40) -> list[dict[str, Any]]:
                status, body, _ = self._request(
                    "GET",
                    f"/api/v1/threads/{thread_id}/messages",
                    params={"skip": 0, "limit": limit},
                )
                if status != 200:
                    raise RuntimeError(f"Failed to list messages ({status}): {body.decode('utf-8', errors='replace')}")
                payload = json.loads(body.decode("utf-8"))
                return payload if isinstance(payload, list) else []

            @staticmethod
            def _extract_text_from_json_event(obj: Any) -> str:
                chunks: list[str] = []

                def walk(x: Any) -> None:
                    if isinstance(x, str):
                        return
                    if isinstance(x, list):
                        for item in x:
                            walk(item)
                        return
                    if not isinstance(x, dict):
                        return

                    for key in ("delta", "text", "content", "output_text"):
                        value = x.get(key)
                        if isinstance(value, str):
                            chunks.append(value)
                        elif isinstance(value, list):
                            for part in value:
                                if isinstance(part, dict) and isinstance(part.get("text"), str):
                                    chunks.append(part["text"])
                                elif isinstance(part, str):
                                    chunks.append(part)

                    choices = x.get("choices")
                    if isinstance(choices, list):
                        for choice in choices:
                            if not isinstance(choice, dict):
                                continue
                            delta = choice.get("delta")
                            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                                chunks.append(delta["content"])
                            text = choice.get("text")
                            if isinstance(text, str):
                                chunks.append(text)
                            message = choice.get("message")
                            if isinstance(message, dict) and isinstance(message.get("content"), str):
                                chunks.append(message["content"])

                walk(obj)
                return "".join(chunks)

            @staticmethod
            def _extract_text_from_message_content(content: Any) -> str:
                if isinstance(content, str):
                    return content.strip()
                if not isinstance(content, list):
                    return ""

                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            parts.append(text)
                            continue

                        inner = item.get("content")
                        if isinstance(inner, str) and inner.strip():
                            parts.append(inner)
                    elif isinstance(item, str) and item.strip():
                        parts.append(item)

                return "".join(parts).strip()

            @staticmethod
            def _decode_vercel_protocol_line(line: str) -> str:
                match = re.match(r"^0:(.*)$", line)
                if not match:
                    return ""
                payload = match.group(1).strip()
                if not payload:
                    return ""
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    return ""
                return parsed if isinstance(parsed, str) else ""

            def ask_new_chat(
                self,
                *,
                thread_id: int,
                search_space_id: int,
                question: str,
                mentioned_document_ids: list[int] | None,
                disabled_tools: list[str] | None,
                message_poll_timeout: float,
                pre_request_delay_seconds: float,
                enforce_ranked_evidence_first: bool | None = None,
                ranking_variant: str | None = None,
            ) -> str:
                if pre_request_delay_seconds > 0:
                    time.sleep(pre_request_delay_seconds)

                payload: dict[str, Any] = {
                    "chat_id": thread_id,
                    "user_query": question,
                    "search_space_id": search_space_id,
                }
                if mentioned_document_ids:
                    payload["mentioned_document_ids"] = mentioned_document_ids
                if disabled_tools:
                    payload["disabled_tools"] = disabled_tools
                if enforce_ranked_evidence_first is not None:
                    payload["enforce_ranked_evidence_first"] = enforce_ranked_evidence_first
                if ranking_variant:
                    payload["ranking_variant"] = ranking_variant

                status, body, headers = self._request(
                    "POST",
                    "/api/v1/new_chat",
                    json_body=payload,
                    extra_headers={"Accept": "text/event-stream"},
                )
                if status != 200:
                    raise RuntimeError(f"/api/v1/new_chat failed ({status}): {body.decode('utf-8', errors='replace')}")

                raw = body.decode("utf-8", errors="replace")
                answer_chunks: list[str] = []
                stream_error_texts: list[str] = []
                content_type = headers.get("Content-Type", "")
                parsed_json_body: Any = None

                if "json" in content_type:
                    try:
                        parsed_json_body = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed_json_body = None

                if "event-stream" in content_type or "data:" in raw or re.search(r"^\d+:", raw, re.MULTILINE):
                    for line in raw.splitlines():
                        part = line.strip()
                        if not part:
                            continue
                        if part.startswith("data:"):
                            part = part[5:].strip()
                        if not part or part == "[DONE]":
                            continue

                        vercel_text = self._decode_vercel_protocol_line(part)
                        if vercel_text:
                            answer_chunks.append(vercel_text)

                        try:
                            obj = json.loads(part)
                        except json.JSONDecodeError:
                            continue

                        text = ""
                        if isinstance(obj, dict) and isinstance(obj.get("type"), str):
                            event_type = obj["type"]
                            if event_type == "error":
                                err = obj.get("errorText") or obj.get("message") or obj.get("error")
                                if isinstance(err, str) and err.strip():
                                    stream_error_texts.append(err.strip())
                            if event_type == "text-delta" and isinstance(obj.get("delta"), str):
                                text = obj["delta"]
                            elif event_type == "text" and isinstance(obj.get("text"), str):
                                text = obj["text"]
                            elif event_type == "message" and isinstance(obj.get("message"), dict):
                                content = obj["message"].get("content")
                                if isinstance(content, str):
                                    text = content
                        elif isinstance(obj, dict):
                            err = obj.get("errorText") or obj.get("message") or obj.get("error")
                            if isinstance(err, str) and err.strip():
                                stream_error_texts.append(err.strip())

                        if not text:
                            text = self._extract_text_from_json_event(obj)
                        if text:
                            answer_chunks.append(text)

                answer = "".join(answer_chunks).strip()
                if answer:
                    return answer

                if parsed_json_body is not None:
                    json_answer = ""
                    if isinstance(parsed_json_body, dict):
                        for key in ("answer", "response", "text", "content", "message"):
                            value = parsed_json_body.get(key)
                            if isinstance(value, str) and value.strip():
                                json_answer = value.strip()
                                break
                            if isinstance(value, dict):
                                candidate = self._extract_text_from_json_event(value)
                                if candidate.strip():
                                    json_answer = candidate.strip()
                                    break
                        if not json_answer:
                            candidate = self._extract_text_from_json_event(parsed_json_body)
                            if candidate.strip():
                                json_answer = candidate.strip()

                    if json_answer:
                        return json_answer

                if stream_error_texts:
                    first_error = stream_error_texts[0]
                    if len(first_error) > 400:
                        first_error = first_error[:397] + "..."
                    raise RuntimeError(f"/api/v1/new_chat stream error: {first_error}")

                deadline = time.time() + max(1.0, message_poll_timeout)
                while time.time() < deadline:
                    messages = self.list_messages(thread_id=thread_id, limit=40)
                    for message in reversed(messages):
                        if message.get("role") != "assistant":
                            continue
                        content = message.get("content")
                        extracted = self._extract_text_from_message_content(content)
                        if extracted:
                            return extracted

                        for key in ("text", "answer", "response"):
                            value = message.get(key)
                            if isinstance(value, str) and value.strip():
                                return value.strip()

                        parts = message.get("parts")
                        extracted_parts = self._extract_text_from_message_content(parts)
                        if extracted_parts:
                            return extracted_parts
                    time.sleep(1.0)

                return ""

        def _normalize_text(value: str) -> str:
            text = (value or "").lower().strip()
            text = text.replace("\u00a0", " ")
            text = re.sub(r"\s+", " ", text)
            text = re.sub(r"[^a-z0-9.%$\- ]+", "", text)
            return text.strip()

        def _extract_numbers(value: str) -> list[float]:
            nums: list[float] = []
            for match in re.finditer(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\$?\d+(?:\.\d+)?", value or ""):
                raw = match.group(0).replace("$", "").replace(",", "")
                try:
                    nums.append(float(raw))
                except ValueError:
                    continue
            return nums

        def _extract_units(value: str) -> set[str]:
            text = (value or "").lower()
            units = set()
            for unit in ["billion", "million", "thousand", "percent", "%", "bps", "basis points", "$", "usd"]:
                if unit in text:
                    units.add(unit)
            return units

        def _f1_token(gold: str, pred: str) -> float:
            g = [t for t in _normalize_text(gold).split(" ") if t]
            p = [t for t in _normalize_text(pred).split(" ") if t]
            if not g and not p:
                return 1.0
            if not g or not p:
                return 0.0
            g_counts: dict[str, int] = {}
            for token in g:
                g_counts[token] = g_counts.get(token, 0) + 1
            overlap = 0
            for token in p:
                if g_counts.get(token, 0) > 0:
                    overlap += 1
                    g_counts[token] -= 1
            precision = overlap / len(p)
            recall = overlap / len(g)
            return (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

        def evaluate_answer(gold: str, pred: str):  # type: ignore[no-redef]
            gnorm = _normalize_text(gold)
            pnorm = _normalize_text(pred)
            strict_exact = gold.strip() == (pred or "").strip()
            normalized_exact = gnorm == pnorm
            contains_gold = bool(gnorm) and gnorm in pnorm
            g_nums = _extract_numbers(gold)
            p_nums = _extract_numbers(pred)
            number_match = bool(g_nums) and bool(p_nums) and any(abs(g - p) <= max(abs(g) * 0.01, 1e-9) for g in g_nums for p in p_nums)
            unit_match = bool(_extract_units(gold) & _extract_units(pred)) if _extract_units(gold) else True
            token_f1 = _f1_token(gold, pred)
            overall_correct = normalized_exact or (number_match and unit_match)
            return SimpleNamespace(
                answer_clean=bool((pred or "").strip()),
                semantic_intent_ok=True,
                strict_exact=strict_exact,
                normalized_exact=normalized_exact,
                contains_gold=contains_gold,
                number_match=number_match,
                unit_match=unit_match,
                numeric_precision=1.0 if number_match else 0.0,
                numeric_recall=1.0 if number_match else 0.0,
                numeric_f1=1.0 if number_match else 0.0,
                primary_value_match=number_match,
                token_f1=token_f1,
                strict_correct=strict_exact,
                lenient_correct=overall_correct,
                overall_correct=overall_correct,
            )

        def load_benchmark(path: Path) -> list[dict[str, Any]]:  # type: ignore[no-redef]
            payload = json.loads(path.read_text(encoding="utf-8"))
            qas = payload.get("qa_pairs")
            if not isinstance(qas, list):
                raise RuntimeError("Benchmark JSON missing 'qa_pairs' list")
            return qas

        def write_outputs(output_dir: Path, run_name: str, payload: dict[str, Any]) -> tuple[Path, Path]:  # type: ignore[no-redef]
            output_dir.mkdir(parents=True, exist_ok=True)
            json_path = output_dir / f"{run_name}.json"
            md_path = output_dir / f"{run_name}.md"
            json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            summary = payload.get("summary", {})
            lines = [
                f"# SurfSense Benchmark Report: {run_name}",
                "",
                f"- Generated at: {payload.get('generated_at_utc', '')}",
                f"- Questions run: {summary.get('questions_run', 0)} / {summary.get('questions_total', 0)}",
                f"- Overall correct: {summary.get('overall_correct_count', 0)} ({float(summary.get('overall_correct_rate', 0.0)):.2%})",
                "",
            ]
            md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return json_path, md_path

    token = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise RuntimeError("Missing bearer token for indexed-only benchmark mode")

    client = SurfSenseClient(base_url=internal_api_base_url, timeout=max(30.0, request_timeout))
    client.token = token

    docs = client.list_documents(search_space_id)
    qas = load_benchmark(benchmark_file_path)
    if start_question > 1:
        qas = qas[start_question - 1 :]
    if max_questions > 0:
        qas = qas[:max_questions]

    candidates = _build_candidates(etl_services, chunking_strategies, embedding_models, chunk_sizes, ranking_variants)

    def _resolve_candidate_doc_ids(candidate: dict[str, Any]) -> list[int]:
        def _compact(value: str) -> str:
            return "".join(ch for ch in value.lower() if ch.isalnum())

        def _doc_matches_signature(doc: dict[str, Any]) -> bool:
            metadata = doc.get("document_metadata") if isinstance(doc.get("document_metadata"), dict) else {}
            if not isinstance(metadata, dict):
                return False

            signatures = metadata.get("pipeline_signatures")
            if not isinstance(signatures, list):
                return False

            target_etl = str(candidate.get("etl_service", "")).strip().upper()
            target_strategy = str(candidate.get("chunking_strategy", "")).strip()
            target_model = str(candidate.get("embedding_model", "")).strip()
            target_chunk_size = candidate.get("chunk_size")

            for signature in signatures:
                if not isinstance(signature, dict):
                    continue

                etl_service = str(signature.get("etl_service", "")).strip().upper()
                if target_etl and etl_service and target_etl != etl_service:
                    continue

                strategy = str(signature.get("chunking_strategy", "")).strip()
                if target_strategy and strategy and target_strategy != strategy:
                    continue

                chunk_size = signature.get("chunk_size")
                if isinstance(target_chunk_size, int) and isinstance(chunk_size, int) and target_chunk_size != chunk_size:
                    continue

                models = signature.get("embedding_models")
                if isinstance(models, list):
                    normalized_models = {str(value).strip() for value in models if isinstance(value, str)}
                    if target_model and target_model not in normalized_models:
                        continue

                return True

            return False

        source_stem = benchmark_file_path.stem.replace("_qa_benchmark_100_sanitized", "").replace("_qa_benchmark_100", "")
        expected_prefix = (
            f"{source_stem}__{candidate['etl_slug']}__{candidate['strategy_slug']}__{candidate['model_slug']}__"
            f"{candidate['size_slug']}"
        ).lower()
        matched_ids: list[int] = []

        for doc in docs:
            doc_id = doc.get("id")
            if not isinstance(doc_id, int):
                continue
            if _doc_matches_signature(doc):
                matched_ids.append(doc_id)

        for doc in docs:
            title = str(doc.get("title", "")).lower()
            doc_id = doc.get("id")
            if expected_prefix in title and isinstance(doc_id, int):
                matched_ids.append(doc_id)
        if not matched_ids:
            fallback_prefix = (
                f"{candidate['etl_slug']}__{candidate['strategy_slug']}__{candidate['model_slug']}__"
                f"{candidate['size_slug']}"
            ).lower()
            for doc in docs:
                title = str(doc.get("title", "")).lower()
                doc_id = doc.get("id")
                if fallback_prefix in title and isinstance(doc_id, int):
                    matched_ids.append(doc_id)
        if not matched_ids:
            source_compact = _compact(source_stem)
            strategy_compact = _compact(str(candidate.get("chunking_strategy", "")))
            model_compact = _compact(str(candidate.get("embedding_model", "")))
            size_compact = _compact(str(candidate.get("size_slug", "")))
            etl_compact = _compact(str(candidate.get("etl_service", "")))

            ranked_candidates: list[tuple[int, int]] = []
            for doc in docs:
                doc_id = doc.get("id")
                if not isinstance(doc_id, int):
                    continue
                title = str(doc.get("title", "")).lower()
                title_compact = _compact(title)
                metadata = doc.get("document_metadata") if isinstance(doc.get("document_metadata"), dict) else {}
                doc_etl = _compact(str(metadata.get("ETL_SERVICE", ""))) if isinstance(metadata, dict) else ""

                if etl_compact and etl_compact not in title_compact and etl_compact != doc_etl:
                    continue

                if strategy_compact and strategy_compact not in title_compact:
                    continue
                if model_compact and model_compact not in title_compact:
                    continue
                if size_compact and size_compact not in title_compact:
                    continue

                score = 0
                if source_compact and source_compact in title_compact:
                    score += 2
                ranked_candidates.append((score, doc_id))

            if ranked_candidates:
                ranked_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
                matched_ids.append(ranked_candidates[0][1])
        if not matched_ids:
            return []
        return [max(matched_ids)]

    def _run_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        pipeline_id = str(candidate["pipeline_id"])
        ranking_variant = str(candidate["ranking_variant"])
        doc_ids = _resolve_candidate_doc_ids(candidate)
        if not doc_ids:
            return {
                "candidate": {
                    "etl_service": candidate["etl_service"],
                    "chunking_strategy": candidate["chunking_strategy"],
                    "embedding_model": candidate["embedding_model"],
                    "chunk_size": candidate["chunk_size"],
                    "ranking_variant": candidate["ranking_variant"],
                },
                "pipeline_id": pipeline_id,
                "success": False,
                "run_name": f"{run_prefix}__{pipeline_id}__indexed",
                "document_id": "indexed",
                "pipeline_upload_id": None,
                "document_title_filter": pipeline_id,
                "benchmark_json": None,
                "benchmark_md": None,
                "overall_correct_rate": 0.0,
                "normalized_exact_rate": 0.0,
                "number_match_rate": 0.0,
                "unit_match_rate": 0.0,
                "mean_token_f1": 0.0,
                "request_failures": 1,
                "elapsed_seconds": 0.0,
                "score": -1.0,
                "error": "No indexed document matched candidate title pattern",
            }

        started = time.time()
        run_name = f"{run_prefix}__{pipeline_id}__indexed"
        results: list[dict[str, Any]] = []
        failures = 0
        for idx, qa in enumerate(qas, start=1):
            qid = str(qa.get("id", f"Q{idx:03d}"))
            question = str(qa.get("question", "")).strip()
            gold = str(qa.get("answer", "")).strip()
            asked_question = question
            thread_id = client.create_thread(search_space_id=search_space_id, title=f"benchmark-{run_name}-{qid}")
            try:
                prediction = client.ask_new_chat(
                    thread_id=thread_id,
                    search_space_id=search_space_id,
                    question=asked_question,
                    mentioned_document_ids=doc_ids,
                    disabled_tools=["web_search", "scrape_webpage"],
                    message_poll_timeout=30.0,
                    pre_request_delay_seconds=0.0,
                    enforce_ranked_evidence_first=True,
                    ranking_variant=ranking_variant,
                )
            except Exception:
                prediction = ""
                failures += 1

            metrics = evaluate_answer(gold=gold, pred=prediction)
            results.append(
                {
                    "id": qid,
                    "group": str(qa.get("group", "unknown")),
                    "question": question,
                    "asked_question": asked_question,
                    "gold_answer": gold,
                    "predicted_answer": prediction,
                    "metrics": {
                        "answer_clean": metrics.answer_clean,
                        "semantic_intent_ok": metrics.semantic_intent_ok,
                        "strict_exact": metrics.strict_exact,
                        "normalized_exact": metrics.normalized_exact,
                        "contains_gold": metrics.contains_gold,
                        "number_match": metrics.number_match,
                        "unit_match": metrics.unit_match,
                        "numeric_precision": metrics.numeric_precision,
                        "numeric_recall": metrics.numeric_recall,
                        "numeric_f1": metrics.numeric_f1,
                        "primary_value_match": metrics.primary_value_match,
                        "token_f1": metrics.token_f1,
                        "strict_correct": metrics.strict_correct,
                        "lenient_correct": metrics.lenient_correct,
                        "overall_correct": metrics.overall_correct,
                    },
                }
            )

        summary = _aggregate_benchmark_items(results)
        summary["questions_total"] = len(qas)
        summary["questions_run"] = len(results)
        summary["request_failures"] = failures
        summary["context_overflow_failures"] = 0

        by_group: dict[str, dict[str, Any]] = {}
        groups = sorted({str(item.get("group", "unknown")) for item in results})
        for group in groups:
            grouped_items = [item for item in results if str(item.get("group", "unknown")) == group]
            by_group[group] = _aggregate_benchmark_items(grouped_items)

        bench_payload = {
            "generated_at_utc": _now_iso(),
            "config": {
                "base_url": _INTERNAL_API_BASE_URL,
                "resolved_base_url": internal_api_base_url,
                "search_space_id": search_space_id,
                "benchmark_file": str(benchmark_file_path),
                "mentioned_document_ids": doc_ids,
                "sanitize_questions": sanitize_questions,
                "ranking_variant": ranking_variant,
            },
            "summary": summary,
            "by_group": by_group,
            "thread_ids_used": [],
            "results": results,
        }
        out_json, out_md = write_outputs(output_dir, run_name, bench_payload)

        overall = float(summary.get("overall_correct_rate", 0.0))
        normalized_rate = float(summary.get("normalized_exact_rate", 0.0))
        number_rate = float(summary.get("number_match_rate", 0.0))
        unit_rate = float(summary.get("unit_match_rate", 0.0))
        mean_token_f1 = float(summary.get("mean_token_f1", 0.0))
        score = 0.60 * overall + 0.30 * number_rate + 0.10 * mean_token_f1 - 0.01 * failures

        return {
            "candidate": {
                "etl_service": candidate["etl_service"],
                "chunking_strategy": candidate["chunking_strategy"],
                "embedding_model": candidate["embedding_model"],
                "chunk_size": candidate["chunk_size"],
                "ranking_variant": candidate["ranking_variant"],
            },
            "pipeline_id": pipeline_id,
            "success": True,
            "run_name": run_name,
            "document_id": "indexed",
            "pipeline_upload_id": doc_ids[0],
            "document_title_filter": pipeline_id,
            "benchmark_json": str(out_json),
            "benchmark_md": str(out_md),
            "overall_correct_rate": overall,
            "normalized_exact_rate": normalized_rate,
            "number_match_rate": number_rate,
            "unit_match_rate": unit_rate,
            "mean_token_f1": mean_token_f1,
            "request_failures": failures,
            "elapsed_seconds": time.time() - started,
            "score": score,
            "error": None,
        }

    def _run_candidate_tracked(candidate: dict[str, Any]) -> dict[str, Any]:
        _update_candidate_status(job_id, candidate["pipeline_id"], status="running", started_at=_now_iso())
        result = _run_candidate(candidate)
        _update_candidate_status(
            job_id, candidate["pipeline_id"],
            status="completed" if result.get("success") else "failed",
            score=result.get("score"),
            overall_correct_rate=result.get("overall_correct_rate"),
            elapsed_seconds=result.get("elapsed_seconds"),
            error=result.get("error"),
            completed_at=_now_iso(),
        )
        return result

    reports: list[dict[str, Any]] = []
    workers = max(1, subagent_workers)
    completed = 0
    total = len(candidates)
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_run_candidate_tracked, candidate) for candidate in candidates]
            for future in as_completed(futures):
                report = future.result()
                reports.append(report)
                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, total, str(report.get("pipeline_id", "")))
    else:
        for candidate in candidates:
            report = _run_candidate_tracked(candidate)
            reports.append(report)
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, total, str(report.get("pipeline_id", "")))

    ranked_reports = sorted(reports, key=lambda report: float(report.get("score", -1.0)), reverse=True)
    successful = [report for report in ranked_reports if report.get("success")]
    recommended = successful[0] if successful else None

    payload = {
        "generated_at_utc": _now_iso(),
        "mode": "indexed_only",
        "search_space_id": search_space_id,
        "benchmark_file": str(benchmark_file_path),
        "recommended_pipeline": recommended,
        "ranked_subagent_reports": ranked_reports,
    }
    summary_json_path, summary_md_path = _write_indexed_master_summary(output_dir, run_prefix, payload)
    payload["summary_json_path"] = str(summary_json_path)
    payload["summary_md_path"] = str(summary_md_path)
    return payload


def _run_benchmark_job(
    *,
    job_id: str,
    auth_header: str | None,
    search_space_id: int,
    benchmark_file_path: Path,
    source_doc_path: Path | None,
    etl_services: list[str],
    chunking_strategies: list[str],
    embedding_models: list[str],
    chunk_sizes: list[int],
    ranking_variants: list[str],
    max_questions: int,
    start_question: int,
    subagent_workers: int,
    benchmark_workers: int,
    request_timeout: float,
    sanitize_questions: bool,
    cleanup_documents: bool,
    run_prefix: str,
    output_dir: Path,
) -> None:
    internal_api_base_url = _resolve_internal_api_base_url()
    started_at_ts = time.time()
    _update_job(
        job_id,
        status="running",
        stage="preparing",
        message=f"Preparing benchmark run (base_url={internal_api_base_url})",
        progress_percent=3,
        started_at=_now_iso(),
        run_prefix=run_prefix,
        output_dir=str(output_dir),
    )

    try:
        if source_doc_path is not None and source_doc_path.exists():
            from scripts.self_adaptive_master_agent import BenchmarkSubagent, MasterOptimizerAgent

            subagent = BenchmarkSubagent(
                base_url=internal_api_base_url,
                username="",
                password="",
                search_space_id=search_space_id,
                source_doc=source_doc_path,
                benchmark_file=benchmark_file_path,
                output_dir=output_dir,
                benchmark_workers=max(1, benchmark_workers),
                benchmark_max_questions=max(1, max_questions),
                benchmark_start_question=max(1, start_question),
                request_timeout=max(30.0, request_timeout),
                sanitize_questions=sanitize_questions,
                llm_model="benchmark-ui",
                cleanup_documents=cleanup_documents,
                auth_header=auth_header,
                chunk_size=None,
            )

            master = MasterOptimizerAgent(
                subagent=subagent,
                chunking_strategies=chunking_strategies,
                embedding_models=embedding_models,
                chunk_sizes=chunk_sizes,
                ranking_variants=ranking_variants,
                subagent_workers=max(1, subagent_workers),
                run_prefix=run_prefix,
                output_dir=output_dir,
                llm_model="benchmark-ui",
            )

            candidates = master._candidates()
            total = len(candidates)
            _update_job(
                job_id,
                stage="running",
                message=f"Running candidates (0/{total})",
                total_candidates=total,
                completed_candidates=0,
                progress_percent=5,
                candidates_status=[
                    {"pipeline_id": str(c.pipeline_id if hasattr(c, 'pipeline_id') else c), "status": "queued", "score": None, "overall_correct_rate": None, "elapsed_seconds": None, "error": None, "started_at": None, "completed_at": None}
                    for c in candidates
                ],
            )

            completed = 0
            original_print_report = master._print_report

            def _patched_print_report(report):
                nonlocal completed
                completed += 1
                elapsed = max(time.time() - started_at_ts, 1e-6)
                remaining = max(total - completed, 0)
                eta = int(remaining / (completed / elapsed)) if completed > 0 else None
                progress = 100 if completed >= total else 5 + int((completed / max(total, 1)) * 90)
                pid = str(report.pipeline_id) if hasattr(report, 'pipeline_id') else str(report)
                _update_candidate_status(
                    job_id, pid,
                    status="completed",
                    score=float(report.score) if hasattr(report, 'score') else None,
                    overall_correct_rate=float(report.overall_correct_rate) if hasattr(report, 'overall_correct_rate') else None,
                    elapsed_seconds=float(report.elapsed_seconds) if hasattr(report, 'elapsed_seconds') else None,
                    completed_at=_now_iso(),
                )
                _update_job(
                    job_id,
                    stage="running",
                    message=f"Completed candidate {completed}/{total}: {pid}",
                    completed_candidates=completed,
                    total_candidates=total,
                    eta_seconds=max(eta, 0) if eta is not None else None,
                    progress_percent=min(progress, 100),
                )
                return original_print_report(report)

            master._print_report = _patched_print_report  # type: ignore[method-assign]
            payload = master.run()
        else:
            candidates = _build_candidates(etl_services, chunking_strategies, embedding_models, chunk_sizes, ranking_variants)
            total = len(candidates)
            _update_job(
                job_id,
                stage="running",
                message=f"Running indexed candidates (0/{total})",
                total_candidates=total,
                completed_candidates=0,
                progress_percent=5,
                candidates_status=[
                    {"pipeline_id": c["pipeline_id"], "status": "queued", "score": None, "overall_correct_rate": None, "elapsed_seconds": None, "error": None, "started_at": None, "completed_at": None}
                    for c in candidates
                ],
            )

            def _on_indexed_candidate_completed(done: int, total_count: int, pipeline_id: str) -> None:
                elapsed = max(time.time() - started_at_ts, 1e-6)
                remaining = max(total_count - done, 0)
                eta = int(remaining / (done / elapsed)) if done > 0 else None
                progress = 100 if done >= total_count else 5 + int((done / max(total_count, 1)) * 90)
                _update_job(
                    job_id,
                    stage="running",
                    message=f"Completed indexed candidate {done}/{total_count}: {pipeline_id}",
                    completed_candidates=done,
                    total_candidates=total_count,
                    eta_seconds=max(eta, 0) if eta is not None else None,
                    progress_percent=min(progress, 100),
                )

            payload = _run_indexed_only_job(
                job_id=job_id,
                auth_header=auth_header,
                search_space_id=search_space_id,
                benchmark_file_path=benchmark_file_path,
                etl_services=etl_services,
                chunking_strategies=chunking_strategies,
                embedding_models=embedding_models,
                chunk_sizes=chunk_sizes,
                ranking_variants=ranking_variants,
                max_questions=max_questions,
                start_question=start_question,
                request_timeout=request_timeout,
                sanitize_questions=sanitize_questions,
                run_prefix=run_prefix,
                output_dir=output_dir,
                subagent_workers=subagent_workers,
                internal_api_base_url=internal_api_base_url,
                progress_callback=_on_indexed_candidate_completed,
            )
            _update_job(
                job_id,
                stage="running",
                message=f"Completed indexed candidates ({total}/{total})",
                completed_candidates=total,
                total_candidates=total,
                progress_percent=100,
            )

        summary_json_path = Path(
            payload.get("summary_json_path") or output_dir / f"{run_prefix}__master_summary.json"
        )
        summary_md_path = Path(
            payload.get("summary_md_path") or output_dir / f"{run_prefix}__master_summary.md"
        )
        recommended = payload.get("recommended_pipeline") if isinstance(payload, dict) else None
        recommended_pipeline_id = None
        if isinstance(recommended, dict):
            recommended_pipeline_id = recommended.get("pipeline_id")

        # Eagerly store ranked_subagent_reports so GET endpoint doesn't need to lazy-load from disk.
        ranked_subagent_reports = payload.get("ranked_subagent_reports") if isinstance(payload, dict) else None
        # Fallback: try loading from the summary JSON file if not already present.
        if not ranked_subagent_reports:
            try:
                if summary_json_path.exists():
                    summary_data = json.loads(summary_json_path.read_text(encoding="utf-8"))
                    ranked_subagent_reports = summary_data.get("ranked_subagent_reports") or []
            except Exception:
                ranked_subagent_reports = []

        _update_job(
            job_id,
            status="completed",
            stage="completed",
            message="Benchmark finished",
            progress_percent=100,
            eta_seconds=0,
            summary_json_path=str(summary_json_path),
            summary_md_path=str(summary_md_path),
            recommended_pipeline_id=recommended_pipeline_id,
            ranked_subagent_reports=ranked_subagent_reports or [],
            completed_at=_now_iso(),
        )
    except Exception as exc:
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            message="Benchmark failed",
            error=str(exc),
            completed_at=_now_iso(),
        )


@router.post("/benchmark/jobs", response_model=BenchmarkJobCreateResponse)
async def create_benchmark_job(
    request: Request,
    benchmark_file: UploadFile = File(...),
    search_space_id: int = Form(...),
    benchmark_document_id: int | None = Form(None),
    source_doc_path: str | None = Form(None),
    etl_services: str = Form("DOCLING"),
    chunking_strategies: str = Form("chunk_text,sandwitch_chunk"),
    embedding_models: str = Form(
        "fastembed/all-MiniLM-L6-v2,fastembed/bge-base-en-v1.5,fastembed/bge-large-en-v1.5"
    ),
    chunk_sizes: str = Form("256,1024"),
    ranking_variants: str = Form("hybrid_rrf_plus,hybrid_weighted"),
    max_questions: int = Form(5),
    start_question: int = Form(1),
    subagent_workers: int = Form(4),
    benchmark_workers: int = Form(1),
    request_timeout: float = Form(240.0),
    sanitize_questions: bool = Form(True),
    cleanup_documents: bool = Form(True),
    run_prefix: str = Form("benchmark_ui_run"),
    output_dir: str = Form("benchmark_results_master_agent"),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    await check_permission(
        session,
        user,
        search_space_id,
        Permission.DOCUMENTS_CREATE.value,
        "You don't have permission to run benchmark jobs in this search space",
    )

    parsed_etl_services = [
        value.strip().upper()
        for value in _parse_csv_or_json_list(etl_services, item_type=str)
        if isinstance(value, str) and value.strip()
    ]
    parsed_chunking = _parse_csv_or_json_list(chunking_strategies, item_type=str)
    parsed_embeddings = _parse_csv_or_json_list(embedding_models, item_type=str)
    parsed_chunk_sizes = _parse_csv_or_json_list(chunk_sizes, item_type=int)
    parsed_ranking = _parse_csv_or_json_list(ranking_variants, item_type=str)

    if not parsed_etl_services or not parsed_chunking or not parsed_embeddings or not parsed_chunk_sizes or not parsed_ranking:
        raise HTTPException(
            status_code=400,
            detail=(
                "etl_services, chunking_strategies, embedding_models, chunk_sizes, and ranking_variants "
                "must contain at least one value"
            ),
        )

    effective_subagent_workers, effective_benchmark_workers = _compute_effective_worker_counts(
        requested_subagent_workers=max(1, subagent_workers),
        requested_benchmark_workers=max(1, benchmark_workers),
    )

    bench_jobs_root = Path("/tmp/surfsense_benchmark_jobs")
    bench_jobs_root.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex
    benchmark_file_path = bench_jobs_root / f"{job_id}__{benchmark_file.filename or 'benchmark.json'}"

    content = await benchmark_file.read()
    await asyncio.to_thread(benchmark_file_path.write_bytes, content)

    if benchmark_document_id is not None:
        result = await session.execute(select(Document).filter(Document.id == benchmark_document_id))
        document = result.scalars().first()

        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Document with id {benchmark_document_id} not found",
            )

        if document.search_space_id != search_space_id:
            raise HTTPException(
                status_code=400,
                detail="benchmark_document_id does not belong to the provided search_space_id",
            )

        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_UPDATE.value,
            "You don't have permission to associate benchmark datasets with this document",
        )

        try:
            dataset_content = content.decode("utf-8")
        except UnicodeDecodeError as decode_error:
            raise HTTPException(
                status_code=400,
                detail="benchmark_file must be UTF-8 text (JSON)",
            ) from decode_error

        max_task_num_result = await session.execute(
            select(func.max(BenchmarkData.task_num)).where(
                BenchmarkData.doc_id == benchmark_document_id,
                BenchmarkData.task_type == "benchmark_job",
            )
        )
        next_task_num = int(max_task_num_result.scalar() or 0) + 1

        benchmark_row = BenchmarkData(
            doc_id=benchmark_document_id,
            task_type="benchmark_job",
            task_num=next_task_num,
            created_date=datetime.now(UTC),
            dataset_filename=benchmark_file.filename or f"benchmark-job-{job_id}.json",
            dataset_content=dataset_content,
            dataset_mime_type=benchmark_file.content_type,
            dataset_size_bytes=len(content),
        )
        session.add(benchmark_row)
        await session.flush()
        await session.commit()

    initial_job: dict[str, Any] = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "message": (
            f"Queued (subagent_workers={effective_subagent_workers}, "
            f"benchmark_workers={effective_benchmark_workers})"
        ),
        "progress_percent": 0,
        "total_candidates": 0,
        "completed_candidates": 0,
        "eta_seconds": None,
        "run_prefix": run_prefix,
        "output_dir": output_dir,
        "summary_json_path": None,
        "summary_md_path": None,
        "recommended_pipeline_id": None,
        "candidates_status": None,
        "error": None,
        "started_at": None,
        "completed_at": None,
    }
    _initial_job_json = json.dumps(initial_job)  # kept for reference / logging only
    await asyncio.to_thread(_create_job, job_id, dict(initial_job))

    auth_header = request.headers.get("authorization")

    worker = threading.Thread(
        target=_run_benchmark_job,
        kwargs={
            "job_id": job_id,
            "auth_header": auth_header,
            "search_space_id": search_space_id,
            "benchmark_file_path": benchmark_file_path,
            "source_doc_path": Path(source_doc_path) if source_doc_path else None,
            "etl_services": parsed_etl_services,
            "chunking_strategies": parsed_chunking,
            "embedding_models": parsed_embeddings,
            "chunk_sizes": parsed_chunk_sizes,
            "ranking_variants": parsed_ranking,
            "max_questions": max_questions,
            "start_question": start_question,
            "subagent_workers": effective_subagent_workers,
            "benchmark_workers": effective_benchmark_workers,
            "request_timeout": request_timeout,
            "sanitize_questions": sanitize_questions,
            "cleanup_documents": cleanup_documents,
            "run_prefix": run_prefix,
            "output_dir": Path(output_dir),
        },
        daemon=True,
    )
    worker.start()

    return BenchmarkJobCreateResponse(job_id=job_id, status="queued")


@router.get("/benchmark/options", response_model=BenchmarkAvailableOptionsResponse)
async def get_benchmark_available_options(
    search_space_id: int,
    document_id: int | None = None,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    await check_permission(
        session,
        user,
        search_space_id,
        Permission.DOCUMENTS_READ.value,
        "You don't have permission to view benchmark options in this search space",
    )

    source = "opensearch"
    try:
        etl_services, chunking, chunk_sizes, embedding_models, pipeline_ids = await _load_options_from_opensearch(
            search_space_id=search_space_id,
            document_id=document_id,
        )
    except Exception:
        etl_services, chunking, chunk_sizes, embedding_models, pipeline_ids = [], [], [], [], []

    needs_metadata_backfill = (
        not etl_services
        or not chunking
        or not chunk_sizes
        or not embedding_models
        or not pipeline_ids
    )

    if needs_metadata_backfill:
        fallback_etl, fallback_chunking, fallback_chunk_sizes, fallback_embeddings, fallback_pipeline_ids = await _load_options_from_metadata(
            session=session,
            search_space_id=search_space_id,
            document_id=document_id,
        )

        if not etl_services and fallback_etl:
            etl_services = fallback_etl
        if not chunking and fallback_chunking:
            chunking = fallback_chunking
        if not chunk_sizes and fallback_chunk_sizes:
            chunk_sizes = fallback_chunk_sizes
        if not embedding_models and fallback_embeddings:
            embedding_models = fallback_embeddings
        if not pipeline_ids and fallback_pipeline_ids:
            pipeline_ids = fallback_pipeline_ids

        if source == "opensearch" and (fallback_etl or fallback_chunking or fallback_chunk_sizes or fallback_embeddings):
            source = "opensearch+metadata"

    if not etl_services and not chunking and not chunk_sizes and not embedding_models:
        source = "metadata_fallback"

    return BenchmarkAvailableOptionsResponse(
        search_space_id=search_space_id,
        document_id=document_id,
        source=source,
        etl_services=etl_services,
        chunking_strategies=chunking,
        chunk_sizes=chunk_sizes,
        embedding_models=embedding_models,
        pipeline_ids=pipeline_ids,
        ranking_variants=list(_BENCHMARK_RANKING_VARIANTS),
    )


@router.get("/benchmark/jobs/{job_id}", response_model=BenchmarkJobStatusResponse)
async def get_benchmark_job(job_id: str):
    # Run Redis I/O in a thread so we never block the asyncio event loop.
    # Blocking the event loop here is what causes uvicorn to stop accepting
    # new TCP connections, making the polling GET appear "unreachable".
    job = await asyncio.to_thread(_get_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Benchmark job not found")

    summary_json_path = job.get("summary_json_path")
    if (
        summary_json_path
        and job.get("status") == "completed"
        and job.get("ranked_subagent_reports") is None
    ):
        try:
            summary_path = Path(summary_json_path)
            if summary_path.exists():
                payload = json.loads(await asyncio.to_thread(lambda: summary_path.read_text(encoding="utf-8")))
                ranked = payload.get("ranked_subagent_reports")
                if isinstance(ranked, list):
                    job["ranked_subagent_reports"] = ranked
        except Exception:
            pass

    return BenchmarkJobStatusResponse(**job)


@router.websocket("/benchmark/jobs/{job_id}/ws")
async def stream_benchmark_job(job_id: str, websocket: WebSocket):
    await websocket.accept()
    last_snapshot = None

    try:
        while True:
            job = await asyncio.to_thread(_get_job, job_id)
            if job is None:
                await websocket.send_json(
                    {
                        "job_id": job_id,
                        "status": "failed",
                        "stage": "failed",
                        "message": "Benchmark job not found",
                        "progress_percent": 0,
                        "total_candidates": 0,
                        "completed_candidates": 0,
                        "error": "Benchmark job not found",
                    }
                )
                break

            snapshot = json.dumps(job, sort_keys=True, default=str)
            if snapshot != last_snapshot:
                await websocket.send_json(job)
                last_snapshot = snapshot

            if job.get("status") in {"completed", "failed"}:
                break

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
