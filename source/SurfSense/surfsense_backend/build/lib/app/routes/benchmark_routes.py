from __future__ import annotations

import json
import asyncio
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import redis as _redis_lib
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Permission, User, get_async_session
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


_BENCHMARK_JOB_TTL = 86400  # 24 hours — jobs survive backend restarts
_BENCHMARK_KEY_PREFIX = "surfsense:benchmark_job:"
_INTERNAL_API_BASE_URL = "http://localhost:8000"

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
    chunking_strategies: list[str],
    embedding_models: list[str],
    chunk_sizes: list[int],
    ranking_variants: list[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for strategy in chunking_strategies:
        for model in embedding_models:
            for chunk_size in chunk_sizes:
                for ranking in ranking_variants:
                    combo = (strategy, model, chunk_size, ranking)
                    if combo in seen:
                        continue
                    seen.add(combo)
                    strategy_slug = _slug(strategy)
                    model_slug = _slug(model.replace("/", "_"))
                    size_slug = f"tok{chunk_size}"
                    ranking_slug = _slug(ranking)
                    candidates.append(
                        {
                            "pipeline_id": f"{strategy_slug}__{model_slug}__{size_slug}__{ranking_slug}",
                            "chunking_strategy": strategy,
                            "embedding_model": model,
                            "chunk_size": chunk_size,
                            "ranking_variant": ranking,
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
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    from scripts.run_surfsense_benchmark import (
        SurfSenseClient,
        evaluate_answer,
        load_benchmark,
        write_outputs,
    )

    token = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise RuntimeError("Missing bearer token for indexed-only benchmark mode")

    client = SurfSenseClient(base_url=_INTERNAL_API_BASE_URL, timeout=max(30.0, request_timeout))
    client.token = token

    docs = client.list_documents(search_space_id)
    qas = load_benchmark(benchmark_file_path)
    if start_question > 1:
        qas = qas[start_question - 1 :]
    if max_questions > 0:
        qas = qas[:max_questions]

    candidates = _build_candidates(chunking_strategies, embedding_models, chunk_sizes, ranking_variants)

    def _resolve_candidate_doc_ids(candidate: dict[str, Any]) -> list[int]:
        def _compact(value: str) -> str:
            return "".join(ch for ch in value.lower() if ch.isalnum())

        source_stem = benchmark_file_path.stem.replace("_qa_benchmark_100_sanitized", "").replace("_qa_benchmark_100", "")
        expected_prefix = (
            f"{source_stem}__{candidate['strategy_slug']}__{candidate['model_slug']}__"
            f"{candidate['size_slug']}__{candidate['ranking_slug']}"
        ).lower()
        matched_ids: list[int] = []
        for doc in docs:
            title = str(doc.get("title", "")).lower()
            doc_id = doc.get("id")
            if expected_prefix in title and isinstance(doc_id, int):
                matched_ids.append(doc_id)
        if not matched_ids:
            fallback_prefix = (
                f"{candidate['strategy_slug']}__{candidate['model_slug']}__"
                f"{candidate['size_slug']}__{candidate['ranking_slug']}"
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
            ranking_compact = _compact(str(candidate.get("ranking_variant", "")))

            ranked_candidates: list[tuple[int, int]] = []
            for doc in docs:
                doc_id = doc.get("id")
                if not isinstance(doc_id, int):
                    continue
                title = str(doc.get("title", "")).lower()
                title_compact = _compact(title)

                if strategy_compact and strategy_compact not in title_compact:
                    continue
                if model_compact and model_compact not in title_compact:
                    continue
                if size_compact and size_compact not in title_compact:
                    continue

                score = 0
                if source_compact and source_compact in title_compact:
                    score += 2
                if ranking_compact and ranking_compact in title_compact:
                    score += 1
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
                "number_match_rate": 0.0,
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
        number_rate = float(summary.get("number_match_rate", 0.0))
        mean_token_f1 = float(summary.get("mean_token_f1", 0.0))
        score = 0.60 * overall + 0.30 * number_rate + 0.10 * mean_token_f1 - 0.01 * failures

        return {
            "candidate": {
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
            "number_match_rate": number_rate,
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
    started_at_ts = time.time()
    _update_job(
        job_id,
        status="running",
        stage="preparing",
        message="Preparing benchmark run",
        progress_percent=3,
        started_at=_now_iso(),
        run_prefix=run_prefix,
        output_dir=str(output_dir),
    )

    try:
        if source_doc_path is not None and source_doc_path.exists():
            from scripts.self_adaptive_master_agent import BenchmarkSubagent, MasterOptimizerAgent

            subagent = BenchmarkSubagent(
                base_url=_INTERNAL_API_BASE_URL,
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
            candidates = _build_candidates(chunking_strategies, embedding_models, chunk_sizes, ranking_variants)
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
    source_doc_path: str | None = Form(None),
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

    parsed_chunking = _parse_csv_or_json_list(chunking_strategies, item_type=str)
    parsed_embeddings = _parse_csv_or_json_list(embedding_models, item_type=str)
    parsed_chunk_sizes = _parse_csv_or_json_list(chunk_sizes, item_type=int)
    parsed_ranking = _parse_csv_or_json_list(ranking_variants, item_type=str)

    if not parsed_chunking or not parsed_embeddings or not parsed_chunk_sizes or not parsed_ranking:
        raise HTTPException(
            status_code=400,
            detail=(
                "chunking_strategies, embedding_models, chunk_sizes, and ranking_variants "
                "must contain at least one value"
            ),
        )

    bench_jobs_root = Path("/tmp/surfsense_benchmark_jobs")
    bench_jobs_root.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex
    benchmark_file_path = bench_jobs_root / f"{job_id}__{benchmark_file.filename or 'benchmark.json'}"

    content = await benchmark_file.read()
    await asyncio.to_thread(benchmark_file_path.write_bytes, content)

    initial_job: dict[str, Any] = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "message": "Queued",
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
            "chunking_strategies": parsed_chunking,
            "embedding_models": parsed_embeddings,
            "chunk_sizes": parsed_chunk_sizes,
            "ranking_variants": parsed_ranking,
            "max_questions": max_questions,
            "start_question": start_question,
            "subagent_workers": subagent_workers,
            "benchmark_workers": benchmark_workers,
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
