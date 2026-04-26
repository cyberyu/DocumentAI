#!/usr/bin/env python3
"""Verify benchmark evidence metadata and build number-match comparison matrix.

Outputs:
1) Evidence verification report for all benchmark questions.
2) Per-question number_match matrix across benchmark result runs.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return WS_RE.sub(" ", text).strip().lower()


def extract_numbers(text: str) -> list[str]:
    vals: list[str] = []
    for m in NUMBER_RE.findall(text):
        vals.append(m.replace(",", ""))
    return vals


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def source_entries_from_structured(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    out: list[dict[str, Any]] = []

    # Prefer entries with page/line metadata when available.
    p_entries = payload.get("paragraph_entries", [])
    if isinstance(p_entries, list):
        for e in p_entries:
            if not isinstance(e, dict):
                continue
            t = e.get("text")
            if not isinstance(t, str) or not t.strip():
                continue
            out.append(
                {
                    "text": t,
                    "page_number": e.get("page_number") if isinstance(e.get("page_number"), int) else None,
                    "line_number": e.get("line_number") if isinstance(e.get("line_number"), int) else None,
                    "kind": "paragraph",
                }
            )

    t_entries = payload.get("table_entries", [])
    if isinstance(t_entries, list):
        for te in t_entries:
            if not isinstance(te, dict):
                continue
            rows = te.get("rows", [])
            if not isinstance(rows, list):
                continue
            for r in rows:
                if not isinstance(r, dict):
                    continue
                row_text = r.get("row_text")
                if not isinstance(row_text, str) or not row_text.strip():
                    continue
                out.append(
                    {
                        "text": row_text,
                        "page_number": r.get("page_number") if isinstance(r.get("page_number"), int) else None,
                        "line_number": r.get("line_number") if isinstance(r.get("line_number"), int) else None,
                        "kind": "table_row",
                    }
                )

    # Fallback for older structured format.
    if not out:
        paras = payload.get("paragraphs", [])
        if isinstance(paras, list):
            for p in paras:
                if isinstance(p, str) and p.strip():
                    out.append({"text": p, "page_number": None, "line_number": None, "kind": "paragraph"})

    return out


def line_texts_from_markdown(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


@dataclass
class EvidenceCheck:
    qid: str
    group: str
    line_number: int | None
    page_number: int | None
    offsets_valid: bool
    extracted_span: str
    extracted_span_norm: str
    answer_support: str
    answer_support_in_extracted_span: str
    source_paragraph_found: bool
    source_paragraph_indices_1based: list[int]
    source_match_mode: str
    source_kind_matches: list[str]
    page_line_match_in_structured: bool | None
    line_match_in_md: bool | None
    line_excerpt: str
    issues: list[str]


def evaluate_answer_support(answer: str, evidence_text: str) -> str:
    ans_n = normalize_text(answer)
    ev_n = normalize_text(evidence_text)
    if ans_n and ans_n in ev_n:
        return "exact"

    ans_nums = extract_numbers(answer)
    ev_nums = set(extract_numbers(evidence_text))
    if ans_nums and all(n in ev_nums for n in ans_nums):
        return "numeric"

    return "none"


def evaluate_dataset(
    benchmark_file: Path,
    source_structured_file: Path,
    source_markdown_file: Path,
) -> tuple[dict[str, Any], list[EvidenceCheck], list[str]]:
    benchmark = load_json(benchmark_file)
    qas = benchmark.get("qa_pairs", [])
    if not isinstance(qas, list):
        raise RuntimeError(f"Benchmark file missing qa_pairs list: {benchmark_file}")

    source_entries = source_entries_from_structured(source_structured_file)
    source_texts = [str(e.get("text", "")) for e in source_entries]
    source_texts_norm = [normalize_text(t) for t in source_texts]
    source_doc_norm = normalize_text(" ".join(source_texts))

    md_lines = line_texts_from_markdown(source_markdown_file)
    max_line_in_qas = max(
        (
            qa.get("evidence", {}).get("line_number")
            for qa in qas
            if isinstance(qa, dict)
            and isinstance(qa.get("evidence"), dict)
            and isinstance(qa.get("evidence", {}).get("line_number"), int)
        ),
        default=0,
    )
    can_check_lines = bool(md_lines) and len(md_lines) >= max_line_in_qas

    checks: list[EvidenceCheck] = []

    for qa in qas:
        qid = str(qa.get("id", ""))
        group = str(qa.get("group", ""))
        answer = str(qa.get("answer", ""))
        evidence = qa.get("evidence") if isinstance(qa.get("evidence"), dict) else {}

        text = str(evidence.get("text", ""))
        line_number = evidence.get("line_number") if isinstance(evidence.get("line_number"), int) else None
        page_number = evidence.get("page_number") if isinstance(evidence.get("page_number"), int) else None
        start_offset = evidence.get("start_offset") if isinstance(evidence.get("start_offset"), int) else None
        end_offset = evidence.get("end_offset") if isinstance(evidence.get("end_offset"), int) else None

        issues: list[str] = []
        offsets_valid = (
            start_offset is not None
            and end_offset is not None
            and start_offset >= 0
            and end_offset >= start_offset
            and end_offset <= len(text)
        )
        if not offsets_valid:
            issues.append("invalid_offsets")

        extracted = text[start_offset:end_offset] if offsets_valid else ""
        extracted_n = normalize_text(extracted)

        answer_support = evaluate_answer_support(answer, text)
        answer_support_span = evaluate_answer_support(answer, extracted)

        if answer_support == "none":
            issues.append("answer_not_supported_by_evidence_text")
        if answer_support_span == "none":
            issues.append("answer_not_supported_by_offset_span")

        text_n = normalize_text(text)
        para_indices = [i + 1 for i, p in enumerate(source_texts) if p == text]
        source_match_mode = "none"
        if para_indices:
            source_match_mode = "paragraph_exact"
        if not para_indices and text_n:
            para_indices = [i + 1 for i, pn in enumerate(source_texts_norm) if pn == text_n]
            if para_indices:
                source_match_mode = "paragraph_normalized_exact"
        if not para_indices and text_n:
            para_indices = [
                i + 1
                for i, pn in enumerate(source_texts_norm)
                if (text_n in pn and len(text_n) > 30) or (pn in text_n and len(pn) > 30)
            ]
            if para_indices:
                source_match_mode = "paragraph_normalized_contains"

        source_found = bool(para_indices)
        if not source_found and text_n and text_n in source_doc_norm:
            source_found = True
            source_match_mode = "document_normalized_contains"
        if not source_found:
            issues.append("evidence_text_not_found_in_msft_docx_structured")

        source_kinds = sorted(
            {
                str(source_entries[i - 1].get("kind"))
                for i in para_indices
                if 1 <= i <= len(source_entries)
            }
        )

        page_line_match_in_structured: bool | None = None
        if source_found and page_number is not None and line_number is not None and para_indices:
            page_line_match_in_structured = any(
                source_entries[i - 1].get("page_number") == page_number
                and source_entries[i - 1].get("line_number") == line_number
                for i in para_indices
                if 1 <= i <= len(source_entries)
            )
            if page_line_match_in_structured is False:
                issues.append("page_or_line_number_mismatch_in_structured")

        line_match: bool | None = None
        line_excerpt = ""
        if line_number is not None and can_check_lines and page_line_match_in_structured is None:
            if 1 <= line_number <= len(md_lines):
                line_excerpt = md_lines[line_number - 1].strip()
                line_n = normalize_text(line_excerpt)
                if text_n and line_n and text_n in line_n:
                    line_match = True
                else:
                    line_match = False
                    issues.append("line_number_does_not_match_evidence_text_in_md")
            else:
                line_match = False
                issues.append("line_number_out_of_range_in_md")

        if page_number is None:
            issues.append("missing_page_number")

        checks.append(
            EvidenceCheck(
                qid=qid,
                group=group,
                line_number=line_number,
                page_number=page_number,
                offsets_valid=offsets_valid,
                extracted_span=extracted,
                extracted_span_norm=extracted_n,
                answer_support=answer_support,
                answer_support_in_extracted_span=answer_support_span,
                source_paragraph_found=source_found,
                source_paragraph_indices_1based=para_indices,
                source_match_mode=source_match_mode,
                source_kind_matches=source_kinds,
                page_line_match_in_structured=page_line_match_in_structured,
                line_match_in_md=line_match,
                line_excerpt=line_excerpt,
                issues=issues,
            )
        )

    issues_all = sorted({issue for c in checks for issue in c.issues})

    summary = {
        "total_questions": len(checks),
        "offsets_valid_count": sum(1 for c in checks if c.offsets_valid),
        "answer_supported_by_evidence_exact_or_numeric_count": sum(
            1 for c in checks if c.answer_support in {"exact", "numeric"}
        ),
        "answer_supported_by_offset_span_exact_or_numeric_count": sum(
            1 for c in checks if c.answer_support_in_extracted_span in {"exact", "numeric"}
        ),
        "source_paragraph_found_count": sum(1 for c in checks if c.source_paragraph_found),
        "page_line_match_in_structured_count": sum(
            1 for c in checks if c.page_line_match_in_structured is True
        ),
        "page_line_checked_in_structured_count": sum(
            1 for c in checks if c.page_line_match_in_structured is not None
        ),
        "line_match_in_md_count": sum(1 for c in checks if c.line_match_in_md is True),
        "line_checked_count": sum(1 for c in checks if c.line_match_in_md is not None),
        "questions_with_any_issue_count": sum(1 for c in checks if c.issues),
        "issue_types": issues_all,
        "limitations": [
            "Page and line are validated against structured source entries (paragraph_entries/table_entries) when available.",
            (
                "line_number is validated against MSFT_FY26Q1_10Q_content.md only when that file has enough lines "
                "to cover benchmark line_number values."
            ),
        ],
    }

    return summary, checks, issues_all


def is_results_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    results = payload.get("results")
    return isinstance(results, list) and len(results) > 0


def collect_result_files(root: Path) -> list[Path]:
    candidates = sorted(root.glob("benchmark_results_MSFT_FY26Q1_qa/*.json"))
    candidates.extend(sorted(root.glob("experiment_backups/**/*.json")))
    unique = sorted(set(candidates))
    # Prefer experiment_backups first because they are curated snapshots.
    unique.sort(key=lambda p: (0 if "experiment_backups" in str(p) else 1, str(p)))
    return unique


def run_label_for(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    if rel.parts and rel.parts[0] == "experiment_backups" and len(rel.parts) >= 3:
        return f"{rel.parts[1]}/{path.stem}"
    return str(rel.with_suffix(""))


def load_number_match_map(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    payload = load_json(path)
    results = payload.get("results", [])
    m: dict[str, str] = {}
    for r in results:
        if not isinstance(r, dict):
            continue
        qid = r.get("id")
        metrics = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
        if not isinstance(qid, str):
            continue
        nm = metrics.get("number_match")
        if isinstance(nm, bool):
            m[qid] = "Y" if nm else "N"
    return m, payload


def build_matrix(
    root: Path,
    benchmark_qids: list[str],
    only_complete_100: bool,
) -> tuple[list[str], dict[str, dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    files = collect_result_files(root)

    columns: list[str] = []
    matrix: dict[str, dict[str, str]] = {qid: {} for qid in benchmark_qids}
    included_runs: list[dict[str, Any]] = []
    skipped_runs: list[dict[str, Any]] = []
    seen_signatures: dict[tuple[str, ...], str] = {}

    for fp in files:
        try:
            payload = load_json(fp)
        except Exception as exc:  # noqa: BLE001
            skipped_runs.append({"file": str(fp.relative_to(root)), "reason": f"json_load_error: {exc}"})
            continue

        if not is_results_payload(payload):
            skipped_runs.append({"file": str(fp.relative_to(root)), "reason": "not_benchmark_results_payload"})
            continue

        number_map, full_payload = load_number_match_map(fp)
        covered = sum(1 for q in benchmark_qids if q in number_map)
        if only_complete_100 and covered < len(benchmark_qids):
            skipped_runs.append(
                {
                    "file": str(fp.relative_to(root)),
                    "reason": f"partial_run_{covered}_of_{len(benchmark_qids)}",
                }
            )
            continue

        label = run_label_for(fp, root)

        signature = tuple(number_map.get(qid, "-") for qid in benchmark_qids)
        if signature in seen_signatures:
            skipped_runs.append(
                {
                    "file": str(fp.relative_to(root)),
                    "reason": f"duplicate_number_match_vector_of:{seen_signatures[signature]}",
                }
            )
            continue
        seen_signatures[signature] = label

        columns.append(label)
        for qid in benchmark_qids:
            matrix[qid][label] = number_map.get(qid, "-")

        summary = full_payload.get("summary") if isinstance(full_payload.get("summary"), dict) else {}
        included_runs.append(
            {
                "label": label,
                "file": str(fp.relative_to(root)),
                "questions_with_number_match_metric": covered,
                "number_match_rate": summary.get("number_match_rate"),
                "overall_correct_rate": summary.get("overall_correct_rate"),
            }
        )

    return columns, matrix, included_runs, skipped_runs


def write_evidence_reports(
    out_dir: Path,
    summary: dict[str, Any],
    checks: list[EvidenceCheck],
) -> None:
    out_json = out_dir / "benchmark_evidence_verification_100.json"
    out_md = out_dir / "benchmark_evidence_verification_100.md"

    out_json.write_text(
        json.dumps(
            {
                "summary": summary,
                "checks": [
                    {
                        "id": c.qid,
                        "group": c.group,
                        "line_number": c.line_number,
                        "page_number": c.page_number,
                        "offsets_valid": c.offsets_valid,
                        "extracted_span": c.extracted_span,
                        "answer_support": c.answer_support,
                        "answer_support_in_extracted_span": c.answer_support_in_extracted_span,
                        "source_paragraph_found": c.source_paragraph_found,
                        "source_paragraph_indices_1based": c.source_paragraph_indices_1based,
                        "source_match_mode": c.source_match_mode,
                        "source_kind_matches": c.source_kind_matches,
                        "page_line_match_in_structured": c.page_line_match_in_structured,
                        "line_match_in_md": c.line_match_in_md,
                        "line_excerpt": c.line_excerpt,
                        "issues": c.issues,
                    }
                    for c in checks
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Benchmark Evidence Verification (100Q)",
        "",
        "## Summary",
        "",
        f"- Total questions: {summary['total_questions']}",
        f"- Offsets valid: {summary['offsets_valid_count']}",
        (
            "- Answer supported by evidence text (exact or numeric): "
            f"{summary['answer_supported_by_evidence_exact_or_numeric_count']}"
        ),
        (
            "- Answer supported by offset span (exact or numeric): "
            f"{summary['answer_supported_by_offset_span_exact_or_numeric_count']}"
        ),
        f"- Evidence text found in structured source: {summary['source_paragraph_found_count']}",
        (
            "- page/line match in structured source: "
            f"{summary['page_line_match_in_structured_count']} / {summary['page_line_checked_in_structured_count']}"
        ),
        (
            "- line_number matches MD line text: "
            f"{summary['line_match_in_md_count']} / {summary['line_checked_count']}"
        ),
        f"- Questions with any issue: {summary['questions_with_any_issue_count']}",
        f"- Issue types: {', '.join(summary['issue_types']) if summary['issue_types'] else 'none'}",
        "",
        "## Limitations",
        "",
    ]
    for lim in summary["limitations"]:
        lines.append(f"- {lim}")

    lines.extend(
        [
            "",
            "## Per-question Status",
            "",
            "| ID | Group | offsets_valid | ans_in_evidence | ans_in_span | source_found | page_line_match | line_match | issues |",
            "|---|---|---:|---|---|---:|---:|---:|---|",
        ]
    )
    for c in checks:
        issues = ", ".join(c.issues) if c.issues else "ok"
        lines.append(
            "| {id} | {group} | {off} | {ans_ev} | {ans_sp} | {src} | {line} | {issues} |".format(
                id=c.qid,
                group=c.group,
                off="Y" if c.offsets_valid else "N",
                ans_ev=c.answer_support,
                ans_sp=c.answer_support_in_extracted_span,
                src="Y" if c.source_paragraph_found else "N",
                pl="Y" if c.page_line_match_in_structured is True else ("N" if c.page_line_match_in_structured is False else "-"),
                line="Y" if c.line_match_in_md is True else ("N" if c.line_match_in_md is False else "-"),
                issues=issues,
            )
        )

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_matrix_reports(
    out_dir: Path,
    qids: list[str],
    columns: list[str],
    matrix: dict[str, dict[str, str]],
    included_runs: list[dict[str, Any]],
    skipped_runs: list[dict[str, Any]],
) -> None:
    matrix_csv = out_dir / "number_match_matrix_by_question.csv"
    matrix_md = out_dir / "number_match_matrix_by_question.md"
    run_summary_json = out_dir / "number_match_matrix_run_summary.json"
    per_question_csv = out_dir / "number_match_per_question_totals.csv"

    with matrix_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", *columns])
        for qid in qids:
            writer.writerow([qid, *[matrix[qid].get(col, "-") for col in columns]])

    with per_question_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "correct_count", "incorrect_count", "missing_count", "correct_rate_over_present"])
        for qid in qids:
            vals = [matrix[qid].get(col, "-") for col in columns]
            y = sum(1 for v in vals if v == "Y")
            n = sum(1 for v in vals if v == "N")
            m = sum(1 for v in vals if v == "-")
            denom = y + n
            rate = (y / denom) if denom else None
            writer.writerow([qid, y, n, m, "" if rate is None else f"{rate:.4f}"])

    lines = [
        "# Number Match Matrix by Question",
        "",
        "Legend: `Y` = number_match true, `N` = number_match false, `-` = missing question in run.",
        "",
        "## Included Runs",
        "",
        "| Label | number_match_rate | overall_correct_rate | file |",
        "|---|---:|---:|---|",
    ]
    for r in included_runs:
        nmr = r.get("number_match_rate")
        ocr = r.get("overall_correct_rate")
        nmr_s = "" if nmr is None else f"{float(nmr):.2%}"
        ocr_s = "" if ocr is None else f"{float(ocr):.2%}"
        lines.append(f"| {r['label']} | {nmr_s} | {ocr_s} | {r['file']} |")

    lines.extend(
        [
            "",
            "## Matrix",
            "",
            "| ID | " + " | ".join(columns) + " |",
            "|---|" + "|".join(["---"] * len(columns)) + "|",
        ]
    )

    for qid in qids:
        row = [matrix[qid].get(col, "-") for col in columns]
        lines.append("| " + qid + " | " + " | ".join(row) + " |")

    matrix_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    run_summary_json.write_text(
        json.dumps(
            {
                "included_runs": included_runs,
                "skipped_runs": skipped_runs,
                "included_count": len(included_runs),
                "skipped_count": len(skipped_runs),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Investigate benchmark evidence consistency and run matrix")
    p.add_argument(
        "--benchmark-file",
        default="msft_fy26q1_qa_benchmark_100_sanitized.json",
        help="Benchmark JSON with qa_pairs and evidence metadata",
    )
    p.add_argument(
        "--source-structured-file",
        default="msft_docx_structured.json",
        help="Structured source JSON used to verify evidence text presence",
    )
    p.add_argument(
        "--source-markdown-file",
        default="MSFT_FY26Q1_10Q_content.md",
        help="Markdown line source used to check line_number mapping when available",
    )
    p.add_argument(
        "--out-dir",
        default="benchmark_results_MSFT_FY26Q1_qa/investigation_outputs",
        help="Directory for generated reports",
    )
    p.add_argument(
        "--allow-partial-runs",
        action="store_true",
        help="Include runs with fewer than 100 questions in the number-match matrix",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()

    benchmark_file = (root / args.benchmark_file).resolve()
    source_structured_file = (root / args.source_structured_file).resolve()
    source_markdown_file = (root / args.source_markdown_file).resolve()
    out_dir = (root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    benchmark_payload = load_json(benchmark_file)
    qa_pairs = benchmark_payload.get("qa_pairs", [])
    benchmark_qids = [str(x.get("id", "")) for x in qa_pairs if isinstance(x, dict) and x.get("id")]

    ev_summary, checks, _ = evaluate_dataset(
        benchmark_file=benchmark_file,
        source_structured_file=source_structured_file,
        source_markdown_file=source_markdown_file,
    )
    write_evidence_reports(out_dir=out_dir, summary=ev_summary, checks=checks)

    columns, matrix, included_runs, skipped_runs = build_matrix(
        root=root,
        benchmark_qids=benchmark_qids,
        only_complete_100=not args.allow_partial_runs,
    )
    write_matrix_reports(
        out_dir=out_dir,
        qids=benchmark_qids,
        columns=columns,
        matrix=matrix,
        included_runs=included_runs,
        skipped_runs=skipped_runs,
    )

    print("Investigation complete")
    print(f"  out_dir: {out_dir}")
    print(f"  total_questions: {ev_summary['total_questions']}")
    print(f"  offsets_valid: {ev_summary['offsets_valid_count']}")
    print(
        "  answer_supported_by_offset_span: "
        f"{ev_summary['answer_supported_by_offset_span_exact_or_numeric_count']}"
    )
    print(f"  matrix_runs_included: {len(columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
