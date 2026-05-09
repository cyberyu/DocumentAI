#!/usr/bin/env python3
"""Self-adaptive master agent for SurfSense RAG pipeline optimization.

This script evaluates multiple (chunking_strategy, embedding_model) pipeline settings
using benchmark Q/A with ground truth, then ranks settings and recommends the best one.

Design:
- Master agent builds a candidate universe.
- One subagent per candidate uploads and indexes a document variant with fixed settings.
- Each subagent runs scripts/run_surfsense_benchmark.py for objective scoring.
- Master aggregates subagent reports and outputs ranked recommendations.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


def _now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _first_present(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


@dataclass
class PipelineCandidate:
    pipeline_id: str
    chunking_strategy: str
    embedding_model: str
    chunk_size: int | None = None
    ranking_variant: str | None = None


@dataclass
class SubagentReport:
    candidate: PipelineCandidate
    pipeline_id: str
    success: bool
    run_name: str
    document_id: str
    pipeline_upload_id: int | None
    document_title_filter: str
    benchmark_json: str | None
    benchmark_md: str | None
    overall_correct_rate: float
    number_match_rate: float
    mean_token_f1: float
    request_failures: int
    elapsed_seconds: float
    score: float
    error: str | None = None


@dataclass
class HarnessAssignment:
    pipeline_id: str
    run_name: str
    chunking_strategy: str
    embedding_model: str
    ranking_variant: str | None
    document_id: str
    pipeline_upload_id: int
    forced_mentioned_document_ids: list[int]
    chunk_size: int | None = None


class SurfSenseApiClient:
    def __init__(self, base_url: str, timeout: float = 180.0, auth_header: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if auth_header:
            self.session.headers.update({"Authorization": auth_header})

    def login(self, username: str, password: str) -> None:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = self.session.post(
                    f"{self.base_url}/auth/jwt/login",
                    data={"username": username, "password": password},
                    timeout=self.timeout,
                )
                if response.status_code == 429 and attempt < 4:
                    time.sleep(10)
                    continue
                response.raise_for_status()
                payload = response.json()
                token = payload.get("access_token")
                if not token:
                    raise RuntimeError("Login response missing access_token")
                self.session.headers.update({"Authorization": f"Bearer {token}"})
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 4:
                    time.sleep(5)
                    continue
                break
        raise RuntimeError(f"Login failed after retries: {last_error}")

    @staticmethod
    def _inject_unique_docx_marker(docx_path: Path, marker: str) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="master_agent_docx_patch_") as td:
                patched_path = Path(td) / "patched.docx"

                with zipfile.ZipFile(docx_path, "r") as src_zip:
                    xml = src_zip.read("word/document.xml").decode("utf-8", errors="ignore")
                    marker_text = f"MASTER_AGENT_VARIANT_{marker}"
                    marker_text = marker_text[:200]
                    snippet = (
                        "<w:p><w:r><w:t xml:space=\"preserve\">"
                        f"{marker_text}"
                        "</w:t></w:r></w:p>"
                    )
                    if "</w:body>" in xml:
                        xml = xml.replace("</w:body>", f"{snippet}</w:body>", 1)

                    with zipfile.ZipFile(patched_path, "w", compression=zipfile.ZIP_DEFLATED) as dst_zip:
                        for info in src_zip.infolist():
                            if info.filename == "word/document.xml":
                                dst_zip.writestr(info, xml.encode("utf-8"))
                            else:
                                dst_zip.writestr(info, src_zip.read(info.filename))

                shutil.copy2(patched_path, docx_path)
        except Exception:
            return

    def upload_document_variant(
        self,
        *,
        source_doc: Path,
        upload_filename: str,
        pipeline_id: str,
        search_space_id: int,
        chunking_strategy: str,
        embedding_model: str,
        chunk_size: int | None = None,
    ) -> int:
        with tempfile.TemporaryDirectory(prefix="master_agent_upload_") as td:
            temp_doc = Path(td) / upload_filename
            shutil.copy2(source_doc, temp_doc)

            if temp_doc.suffix.lower() == ".docx":
                unique_marker = f"{_slug(pipeline_id)}_{uuid.uuid4().hex[:12]}"
                self._inject_unique_docx_marker(temp_doc, unique_marker)

            with temp_doc.open("rb") as f:
                files = [("files", (upload_filename, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))]
                data = {
                    "search_space_id": str(search_space_id),
                    "processing_mode": "basic",
                    "chunking_strategy": chunking_strategy,
                    "embedding_models": json.dumps([embedding_model]),
                }
                if chunk_size is not None:
                    data["chunk_size"] = str(chunk_size)
                response = self.session.post(
                    f"{self.base_url}/api/v1/documents/fileupload",
                    files=files,
                    data=data,
                    timeout=self.timeout,
                )

        response.raise_for_status()
        payload = response.json()
        document_ids = payload.get("document_ids") or []
        if not document_ids:
            raise RuntimeError(f"Upload returned no document_ids: {payload}")
        return int(document_ids[0])

    def wait_until_indexed(
        self,
        *,
        search_space_id: int,
        document_id: int,
        timeout_seconds: int = 1200,
        poll_interval_seconds: float = 2.0,
    ) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = self.session.get(
                f"{self.base_url}/api/v1/documents/status",
                params={
                    "search_space_id": search_space_id,
                    "document_ids": str(document_id),
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items") or []
            if items:
                state = ((items[0].get("status") or {}).get("state") or "").lower()
                if state in {"ready", "failed"}:
                    return state
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for document {document_id} to be ready")

    def delete_document(self, document_id: int) -> None:
        response = self.session.delete(
            f"{self.base_url}/api/v1/documents/{document_id}",
            timeout=self.timeout,
        )
        if response.status_code in {200, 202, 204, 404}:
            return
        response.raise_for_status()


class BenchmarkSubagent:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        search_space_id: int,
        source_doc: Path,
        benchmark_file: Path,
        output_dir: Path,
        benchmark_workers: int,
        benchmark_max_questions: int,
        benchmark_start_question: int,
        request_timeout: float,
        sanitize_questions: bool,
        llm_model: str,
        cleanup_documents: bool,
        auth_header: str | None,
        chunk_size: int | None,
    ) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password
        self.search_space_id = search_space_id
        self.source_doc = source_doc
        self.benchmark_file = benchmark_file
        self.output_dir = output_dir
        self.benchmark_workers = benchmark_workers
        self.benchmark_max_questions = benchmark_max_questions
        self.benchmark_start_question = benchmark_start_question
        self.request_timeout = request_timeout
        self.sanitize_questions = sanitize_questions
        self.llm_model = llm_model
        self.cleanup_documents = cleanup_documents
        self.auth_header = auth_header
        self.chunk_size = chunk_size
        self.document_id = self._compute_stable_document_id(source_doc)

    @staticmethod
    def _compute_stable_document_id(source_doc: Path) -> str:
        digest = hashlib.sha256(source_doc.read_bytes()).hexdigest()
        return f"docsha256_{digest[:16]}"

    def run(self, candidate: PipelineCandidate, run_prefix: str) -> SubagentReport:
        started = time.time()
        client = SurfSenseApiClient(
            self.base_url,
            timeout=max(180.0, self.request_timeout),
            auth_header=self.auth_header,
        )
        if not self.auth_header:
            client.login(self.username, self.password)

        embed_slug = _slug(candidate.embedding_model.replace("/", "_"))
        strategy_slug = _slug(candidate.chunking_strategy)
        candidate_chunk_size = candidate.chunk_size if candidate.chunk_size is not None else self.chunk_size
        size_slug = f"tok{candidate_chunk_size}" if candidate_chunk_size is not None else "tokdefault"
        ranking_slug = _slug(candidate.ranking_variant or "hybrid_rrf")
        suffix = uuid.uuid4().hex[:8]
        title_filter = f"{self.source_doc.stem}__{strategy_slug}__{embed_slug}__{size_slug}__{ranking_slug}__{suffix}"
        upload_name = f"{title_filter}{self.source_doc.suffix}"
        run_name = f"{run_prefix}__{strategy_slug}__{embed_slug}__{size_slug}__{ranking_slug}__{suffix}"

        pipeline_upload_id: int | None = None
        benchmark_json_path: Path | None = None
        benchmark_md_path: Path | None = None

        try:
            pipeline_upload_id = client.upload_document_variant(
                source_doc=self.source_doc,
                upload_filename=upload_name,
                pipeline_id=candidate.pipeline_id,
                search_space_id=self.search_space_id,
                chunking_strategy=candidate.chunking_strategy,
                embedding_model=candidate.embedding_model,
                chunk_size=candidate_chunk_size,
            )
            state = client.wait_until_indexed(
                search_space_id=self.search_space_id,
                document_id=pipeline_upload_id,
            )
            if state != "ready":
                raise RuntimeError(
                    f"Document indexing failed for pipeline_upload_id={pipeline_upload_id}, "
                    f"pipeline_id={candidate.pipeline_id}, state={state}"
                )

            cmd = [
                sys.executable,
                "scripts/run_surfsense_benchmark.py",
                "--base-url",
                self.base_url,
                "--username",
                self.username,
                "--password",
                self.password,
                "--search-space-id",
                str(self.search_space_id),
                "--benchmark-file",
                str(self.benchmark_file),
                "--max-questions",
                str(self.benchmark_max_questions),
                "--start-question",
                str(self.benchmark_start_question),
                "--run-name",
                run_name,
                "--output-dir",
                str(self.output_dir),
                "--mentioned-document-ids",
                str(pipeline_upload_id),
                "--sanitize-questions",
                str(self.sanitize_questions).lower(),
                "--request-timeout",
                str(self.request_timeout),
                "--workers",
                str(self.benchmark_workers),
                "--disabled-tools",
                "web_search,scrape_webpage",
                "--enforce-ranked-evidence-first",
            ]
            if candidate.ranking_variant:
                cmd.extend(["--ranking-variant", candidate.ranking_variant])
            completed = subprocess.run(cmd, cwd=str(Path(__file__).resolve().parents[1]), check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"Benchmark runner failed with code {completed.returncode}")

            benchmark_json_path = self.output_dir / f"{run_name}.json"
            benchmark_md_path = self.output_dir / f"{run_name}.md"
            if not benchmark_json_path.exists():
                raise RuntimeError(f"Benchmark output missing: {benchmark_json_path}")

            payload = json.loads(benchmark_json_path.read_text(encoding="utf-8"))
            summary = payload.get("summary") or {}
            overall = float(summary.get("overall_correct_rate", 0.0))
            number_rate = float(summary.get("number_match_rate", 0.0))
            mean_token_f1 = float(summary.get("mean_token_f1", 0.0))
            failures = int(summary.get("request_failures", 0) or 0)

            # Weighted objective (optimize QA correctness first)
            score = (
                0.60 * overall
                + 0.30 * number_rate
                + 0.10 * mean_token_f1
                - 0.01 * failures
            )

            return SubagentReport(
                candidate=candidate,
                pipeline_id=candidate.pipeline_id,
                success=True,
                run_name=run_name,
                document_id=self.document_id,
                pipeline_upload_id=pipeline_upload_id,
                document_title_filter=title_filter,
                benchmark_json=str(benchmark_json_path),
                benchmark_md=str(benchmark_md_path) if benchmark_md_path.exists() else None,
                overall_correct_rate=overall,
                number_match_rate=number_rate,
                mean_token_f1=mean_token_f1,
                request_failures=failures,
                elapsed_seconds=time.time() - started,
                score=score,
            )

        except Exception as exc:  # noqa: BLE001
            return SubagentReport(
                candidate=candidate,
                pipeline_id=candidate.pipeline_id,
                success=False,
                run_name=run_name,
                document_id=self.document_id,
                pipeline_upload_id=pipeline_upload_id,
                document_title_filter=title_filter,
                benchmark_json=str(benchmark_json_path) if benchmark_json_path else None,
                benchmark_md=str(benchmark_md_path) if benchmark_md_path else None,
                overall_correct_rate=0.0,
                number_match_rate=0.0,
                mean_token_f1=0.0,
                request_failures=1,
                elapsed_seconds=time.time() - started,
                score=-1.0,
                error=str(exc),
            )

        finally:
            if self.cleanup_documents and pipeline_upload_id is not None:
                try:
                    client.delete_document(pipeline_upload_id)
                except Exception:
                    pass


class MasterOptimizerAgent:
    def __init__(
        self,
        *,
        subagent: BenchmarkSubagent,
        chunking_strategies: list[str],
        embedding_models: list[str],
        chunk_sizes: list[int | None],
        ranking_variants: list[str],
        subagent_workers: int,
        run_prefix: str,
        output_dir: Path,
        llm_model: str,
    ) -> None:
        self.subagent = subagent
        self.chunking_strategies = chunking_strategies
        self.embedding_models = embedding_models
        self.chunk_sizes = chunk_sizes
        self.ranking_variants = ranking_variants
        self.subagent_workers = max(1, subagent_workers)
        self.run_prefix = run_prefix
        self.output_dir = output_dir
        self.llm_model = llm_model

    def _candidates(self) -> list[PipelineCandidate]:
        candidates: list[PipelineCandidate] = []
        seen: set[tuple[str, str, int | None, str]] = set()
        for strategy in self.chunking_strategies:
            for model in self.embedding_models:
                for chunk_size in self.chunk_sizes:
                    for ranking_variant in self.ranking_variants:
                        combo = (strategy, model, chunk_size, ranking_variant)
                        if combo in seen:
                            continue
                        seen.add(combo)
                        embed_slug = _slug(model.replace("/", "_"))
                        strategy_slug = _slug(strategy)
                        size_slug = f"tok{chunk_size}" if chunk_size is not None else "tokdefault"
                        ranking_slug = _slug(ranking_variant)
                        candidates.append(
                            PipelineCandidate(
                                pipeline_id=f"{strategy_slug}__{embed_slug}__{size_slug}__{ranking_slug}",
                                chunking_strategy=strategy,
                                embedding_model=model,
                                chunk_size=chunk_size,
                                ranking_variant=ranking_variant,
                            )
                        )
        return candidates

    def run(self) -> dict[str, Any]:
        candidates = self._candidates()
        reports: list[SubagentReport] = []
        assignments: list[HarnessAssignment] = []
        seen_pipeline_ids: set[str] = set()

        print(f"[{_now_utc()}] Master agent started")
        print(f"  LLM: {self.llm_model}")
        print(f"  Candidate pipelines: {len(candidates)}")
        print(f"  Subagent workers: {self.subagent_workers}")
        print(f"  Chunk sizes: {self.chunk_sizes}")
        print(f"  Ranking variants: {self.ranking_variants}")

        if self.subagent_workers > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.subagent_workers) as executor:
                future_map = {
                    executor.submit(self.subagent.run, candidate, self.run_prefix): candidate
                    for candidate in candidates
                }
                for future in concurrent.futures.as_completed(future_map):
                    report = future.result()
                    reports.append(report)
                    if report.pipeline_id in seen_pipeline_ids:
                        report.success = False
                        report.error = f"Harness violation: duplicate pipeline_id {report.pipeline_id}"
                        report.score = -1.0
                    else:
                        seen_pipeline_ids.add(report.pipeline_id)
                    if report.success and report.pipeline_upload_id is not None:
                        assignments.append(
                            HarnessAssignment(
                                pipeline_id=report.pipeline_id,
                                run_name=report.run_name,
                                chunking_strategy=report.candidate.chunking_strategy,
                                embedding_model=report.candidate.embedding_model,
                                ranking_variant=report.candidate.ranking_variant,
                                document_id=report.document_id,
                                pipeline_upload_id=report.pipeline_upload_id,
                                forced_mentioned_document_ids=[report.pipeline_upload_id],
                                chunk_size=report.candidate.chunk_size,
                            )
                        )
                    self._print_report(report)
        else:
            for candidate in candidates:
                report = self.subagent.run(candidate, self.run_prefix)
                reports.append(report)
                if report.pipeline_id in seen_pipeline_ids:
                    report.success = False
                    report.error = f"Harness violation: duplicate pipeline_id {report.pipeline_id}"
                    report.score = -1.0
                else:
                    seen_pipeline_ids.add(report.pipeline_id)
                if report.success and report.pipeline_upload_id is not None:
                    assignments.append(
                        HarnessAssignment(
                            pipeline_id=report.pipeline_id,
                            run_name=report.run_name,
                            chunking_strategy=report.candidate.chunking_strategy,
                            embedding_model=report.candidate.embedding_model,
                            ranking_variant=report.candidate.ranking_variant,
                            document_id=report.document_id,
                            pipeline_upload_id=report.pipeline_upload_id,
                            forced_mentioned_document_ids=[report.pipeline_upload_id],
                            chunk_size=report.candidate.chunk_size,
                        )
                    )
                self._print_report(report)

        ranked = sorted(reports, key=lambda r: r.score, reverse=True)
        successful = [r for r in ranked if r.success]
        recommended = successful[0] if successful else None

        payload = {
            "generated_at_utc": _now_utc(),
            "llm_model": self.llm_model,
            "master_run_prefix": self.run_prefix,
            "subagent_workers": self.subagent_workers,
            "search_space_id": self.subagent.search_space_id,
            "source_document": str(self.subagent.source_doc),
            "document_id": self.subagent.document_id,
            "benchmark_file": str(self.subagent.benchmark_file),
            "objective": {
                "formula": "0.60*overall_correct_rate + 0.30*number_match_rate + 0.10*mean_token_f1 - 0.01*request_failures",
                "primary": "overall_correct_rate",
                "secondary": "number_match_rate",
                "tertiary": "mean_token_f1",
            },
            "harness": {
                "isolation_mode": "forced_mentioned_document_ids",
                "non_overlap_guarantee": "unique pipeline_id -> unique backend_document_id",
                "document_identity": {
                    "document_id": self.subagent.document_id,
                    "semantics": "stable identity for the source document across all pipelines",
                },
                "pipeline_upload_id_semantics": "per-pipeline backend upload row id",
                "chunk_sizes": self.chunk_sizes,
                "ranking_variants": self.ranking_variants,
                "assignments": [asdict(a) for a in assignments],
            },
            "recommended_pipeline": asdict(recommended) if recommended else None,
            "ranked_subagent_reports": [asdict(r) for r in ranked],
        }

        self.output_dir.mkdir(parents=True, exist_ok=True)
        summary_json = self.output_dir / f"{self.run_prefix}__master_summary.json"
        summary_md = self.output_dir / f"{self.run_prefix}__master_summary.md"

        summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        summary_md.write_text(self._build_markdown(payload), encoding="utf-8")

        print(f"[{_now_utc()}] Master agent completed")
        if recommended:
            print(
                "  Recommended: "
                f"strategy={recommended.candidate.chunking_strategy}, "
                f"embedding={recommended.candidate.embedding_model}, "
                f"ranking={recommended.candidate.ranking_variant}, "
                f"overall={recommended.overall_correct_rate:.2%}, "
                f"number={recommended.number_match_rate:.2%}, "
                f"f1={recommended.mean_token_f1:.4f}"
            )
        print(f"  Summary JSON: {summary_json}")
        print(f"  Summary MD: {summary_md}")

        return payload

    @staticmethod
    def _print_report(report: SubagentReport) -> None:
        candidate = report.candidate
        if report.success:
            print(
                f"[{_now_utc()}] subagent success "
                f"pipeline_id={report.pipeline_id} "
                f"strategy={candidate.chunking_strategy} "
                f"embedding={candidate.embedding_model} "
                f"ranking={candidate.ranking_variant} "
                f"overall={report.overall_correct_rate:.2%} "
                f"number={report.number_match_rate:.2%} "
                f"f1={report.mean_token_f1:.4f} "
                f"score={report.score:.4f} "
                f"elapsed={report.elapsed_seconds:.1f}s"
            )
        else:
            print(
                f"[{_now_utc()}] subagent failed "
                f"pipeline_id={report.pipeline_id} "
                f"strategy={candidate.chunking_strategy} "
                f"embedding={candidate.embedding_model} "
                f"ranking={candidate.ranking_variant} "
                f"error={report.error}"
            )

    @staticmethod
    def _build_markdown(payload: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append("# Self-Adaptive Master Agent Summary")
        lines.append("")
        lines.append(f"- Generated: {payload['generated_at_utc']}")
        lines.append(f"- LLM: {payload['llm_model']}")
        lines.append(f"- Source document: {payload['source_document']}")
        lines.append(f"- Document ID (stable): {payload.get('document_id', '')}")
        lines.append(f"- Benchmark: {payload['benchmark_file']}")
        lines.append(f"- Chunk sizes: {payload['harness'].get('chunk_sizes')}")
        lines.append(f"- Ranking variants: {payload['harness'].get('ranking_variants')}")
        lines.append("")

        rec = payload.get("recommended_pipeline")
        if rec:
            lines.append("## Recommendation")
            lines.append("")
            lines.append(
                "- Best pipeline: "
                f"{rec['candidate']['chunking_strategy']} + {rec['candidate']['embedding_model']} + {rec['candidate'].get('ranking_variant')}"
            )
            lines.append(f"- Overall correct: {rec['overall_correct_rate']:.2%}")
            lines.append(f"- Number match: {rec['number_match_rate']:.2%}")
            lines.append(f"- Mean token F1: {rec['mean_token_f1']:.4f}")
            lines.append(f"- Composite score: {rec['score']:.4f}")
            lines.append("")

        lines.append("## Ranked Subagents")
        lines.append("")
        lines.append("| Rank | Pipeline ID | Strategy | Embedding | Ranking | TokenLen | Success | Overall | Number | Mean F1 | Score |")
        lines.append("|---|---|---|---|---|---:|---|---:|---:|---:|---:|")

        for rank, item in enumerate(payload["ranked_subagent_reports"], start=1):
            cand = item["candidate"]
            lines.append(
                "| {rank} | {pipeline_id} | {strategy} | {embedding} | {ranking} | {token_len} | {success} | {overall:.2%} | {number:.2%} | {f1:.4f} | {score:.4f} |".format(
                    rank=rank,
                    pipeline_id=item.get("pipeline_id") or "",
                    strategy=cand["chunking_strategy"],
                    embedding=cand["embedding_model"],
                    ranking=cand.get("ranking_variant") or "hybrid_rrf",
                    token_len=str(cand.get("chunk_size")) if cand.get("chunk_size") is not None else "default",
                    success="Y" if item["success"] else "N",
                    overall=float(item["overall_correct_rate"]),
                    number=float(item["number_match_rate"]),
                    f1=float(item["mean_token_f1"]),
                    score=float(item["score"]),
                )
            )

        return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Self-adaptive master agent for RAG pipeline optimization")
    parser.add_argument("--config", default="benchmark_runner_config.json", help="Optional JSON config file")
    parser.add_argument("--base-url", default=None, help="SurfSense base URL")
    parser.add_argument("--username", default=None, help="SurfSense username")
    parser.add_argument("--password", default=None, help="SurfSense password")
    parser.add_argument("--search-space-id", type=int, default=None, help="Search space ID")
    parser.add_argument("--source-doc", default="MSFT_FY26Q1_10Q.docx", help="Path to uploaded docx source file")
    parser.add_argument(
        "--benchmark-file",
        default="msft_fy26q1_qa_benchmark_100_sanitized.json",
        help="Benchmark JSON with qa_pairs",
    )
    parser.add_argument("--max-questions", type=int, default=100, help="Max benchmark questions")
    parser.add_argument("--start-question", type=int, default=1, help="Start question index (1-based)")
    parser.add_argument("--benchmark-workers", type=int, default=20, help="Workers for benchmark question parallelism")
    parser.add_argument("--subagent-workers", type=int, default=2, help="Parallel subagent count")
    parser.add_argument("--request-timeout", type=float, default=180.0, help="HTTP timeout seconds")
    parser.add_argument("--sanitize-questions", default="true", help="Pass-through sanitize setting")
    parser.add_argument("--cleanup-documents", default="true", help="Delete temporary uploaded variants")
    parser.add_argument("--llm-model", default="deepseek-v4-flash", help="LLM label for report metadata")
    parser.add_argument("--run-prefix", default="deepseek_v4_flash_master", help="Run name prefix")
    parser.add_argument("--output-dir", default="benchmark_results_master_agent", help="Output directory")
    parser.add_argument(
        "--chunking-strategies",
            default="chunk_text,sandwitch_chunk",
        help="Comma-separated chunking strategies",
    )
    parser.add_argument(
        "--embedding-models",
        default="openai/text-embedding-3-small,openai/text-embedding-3-large",
        help="Comma-separated embedding model keys",
    )
    parser.add_argument(
        "--ranking-variants",
        default="hybrid_rrf_plus,hybrid_weighted",
        help="Comma-separated ranking variants for retrieval benchmarking",
    )
    parser.add_argument(
        "--chunk-sizes",
        default="256,1024",
        help="Comma-separated chunk sizes (token lengths), e.g. 256,1024",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Optional single chunk size override for document chunking (takes precedence over --chunk-sizes)",
    )
    return parser


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


def main() -> int:
    try:
        args = build_arg_parser().parse_args()

        cfg = _read_json(Path(args.config)) if args.config else {}

        base_url = args.base_url or _first_present(cfg, ["base_url", "BASE_URL"]) or "http://localhost:8929"
        username = args.username or _first_present(cfg, ["username", "USERNAME"]) or os.getenv("SURFSENSE_USERNAME")
        password = args.password or _first_present(cfg, ["password", "PASSWORD"]) or os.getenv("SURFSENSE_PASSWORD")
        search_space_id_raw = args.search_space_id
        if search_space_id_raw is None:
            search_space_id_raw = _first_present(cfg, ["search_space_id", "SEARCH_SPACE_ID"])
        if search_space_id_raw is None:
            print("ERROR: --search-space-id is required (or SEARCH_SPACE_ID in config)", file=sys.stderr)
            return 2

        try:
            search_space_id = int(search_space_id_raw)
        except (TypeError, ValueError):
            print("ERROR: search_space_id must be an integer", file=sys.stderr)
            return 2

        if not username or not password:
            print("ERROR: username/password are required", file=sys.stderr)
            return 2

        source_doc = Path(args.source_doc)
        if not source_doc.exists():
            print(f"ERROR: source doc not found: {source_doc}", file=sys.stderr)
            return 2

        benchmark_file = Path(args.benchmark_file)
        if not benchmark_file.exists():
            print(f"ERROR: benchmark file not found: {benchmark_file}", file=sys.stderr)
            return 2

        chunking_strategies = [s.strip() for s in args.chunking_strategies.split(",") if s.strip()]
        embedding_models = [m.strip() for m in args.embedding_models.split(",") if m.strip()]
        ranking_variants = [v.strip() for v in args.ranking_variants.split(",") if v.strip()]
        if not chunking_strategies:
            print("ERROR: no chunking strategies provided", file=sys.stderr)
            return 2
        if not embedding_models:
            print("ERROR: no embedding models provided", file=sys.stderr)
            return 2
        if not ranking_variants:
            print("ERROR: no ranking variants provided", file=sys.stderr)
            return 2

        if args.chunk_size is not None:
            if args.chunk_size <= 0:
                print("ERROR: --chunk-size must be a positive integer", file=sys.stderr)
                return 2
            chunk_sizes: list[int | None] = [args.chunk_size]
        else:
            raw_chunk_sizes = [s.strip() for s in (args.chunk_sizes or "").split(",") if s.strip()]
            if not raw_chunk_sizes:
                chunk_sizes = [None]
            else:
                chunk_sizes = []
                for raw_size in raw_chunk_sizes:
                    try:
                        parsed_size = int(raw_size)
                    except ValueError:
                        print(f"ERROR: invalid chunk size in --chunk-sizes: {raw_size}", file=sys.stderr)
                        return 2
                    if parsed_size <= 0:
                        print("ERROR: --chunk-sizes values must be positive integers", file=sys.stderr)
                        return 2
                    chunk_sizes.append(parsed_size)

        auth_header: str | None = None
        try:
            bootstrap_client = SurfSenseApiClient(base_url=base_url, timeout=max(30.0, args.request_timeout))
            bootstrap_client.login(username, password)
            auth_header = bootstrap_client.session.headers.get("Authorization")
        except Exception:
            auth_header = None

        subagent = BenchmarkSubagent(
            base_url=base_url,
            username=username,
            password=password,
            search_space_id=search_space_id,
            source_doc=source_doc,
            benchmark_file=benchmark_file,
            output_dir=Path(args.output_dir),
            benchmark_workers=max(1, args.benchmark_workers),
            benchmark_max_questions=max(1, args.max_questions),
            benchmark_start_question=max(1, args.start_question),
            request_timeout=max(30.0, args.request_timeout),
            sanitize_questions=_as_bool(args.sanitize_questions, True),
            llm_model=args.llm_model,
            cleanup_documents=_as_bool(args.cleanup_documents, True),
            auth_header=auth_header,
            chunk_size=args.chunk_size,
        )

        master = MasterOptimizerAgent(
            subagent=subagent,
            chunking_strategies=chunking_strategies,
            embedding_models=embedding_models,
            chunk_sizes=chunk_sizes,
            ranking_variants=ranking_variants,
            subagent_workers=max(1, args.subagent_workers),
            run_prefix=args.run_prefix,
            output_dir=Path(args.output_dir),
            llm_model=args.llm_model,
        )

        master.run()
        return 0
    except KeyboardInterrupt:
        print("Interrupted by user (Ctrl+C). Shutting down cleanly...", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
