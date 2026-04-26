from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NUM_RE = re.compile(r"\(?\$?\d[\d,]*(?:\.\d+)?\)?%?")
SPLIT_RE = re.compile(r"(?<=[.;:])\s+")
MONEY_OR_RATE_RE = re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?|\d(?:[\d,]*\.?\d+)?%")

FIN_KEYWORDS = [
    "revenue",
    "income",
    "operating",
    "gross",
    "net",
    "cash",
    "assets",
    "liabilities",
    "equity",
    "margin",
    "earnings",
    "expense",
    "tax",
    "diluted",
    "basic",
    "segment",
    "cloud",
    "commercial",
    "products",
    "services",
]

NOISE_KEYWORDS = [
    "washington",
    "commission file",
    "form 10-q",
    "telephone",
    "page",
    "section 13",
    "rule 12b",
    "october",
    "registrant",
]

UNIT_WORDS = ["million", "billion", "thousand", "basis points", "percent"]


@dataclass
class QAPair:
    id: str
    group: str
    difficulty: int
    question: str
    answer: str
    evidence: dict[str, Any]
    verification: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group": self.group,
            "difficulty": self.difficulty,
            "question": self.question,
            "answer": self.answer,
            "evidence": self.evidence,
            "verification": self.verification,
        }


class QAGenerateAgent:
    """Generate and verify numeric QA benchmark from a DOCX-derived structured file.

    The agent runs an iterative two-phase loop:
    1) extract/generate candidate QAs
    2) verify each QA against source evidence or deterministic arithmetic
    """

    def __init__(self, structured_path: Path, seed: int = 7) -> None:
        self.structured_path = structured_path
        self.rng = random.Random(seed)
        self.data = json.loads(structured_path.read_text())
        self.paragraphs: list[str] = self.data["paragraphs"]
        self.tables: list[dict[str, Any]] = self.data["tables"]
        self.paragraph_entries: list[dict[str, Any]] = self.data.get("paragraph_entries", [])
        self.table_entries: list[dict[str, Any]] = self.data.get("table_entries", [])

        if not self.paragraph_entries:
            self.paragraph_entries = [
                {
                    "paragraph_index": i,
                    "text": p,
                    "page_number": None,
                    "line_number": None,
                }
                for i, p in enumerate(self.paragraphs)
            ]

        if not self.table_entries:
            self.table_entries = []
            for t in self.tables:
                rows = t["rows"]
                row_entries = []
                for i, row in enumerate(rows):
                    row_text = " | ".join(c.strip() for c in row)
                    row_entries.append(
                        {
                            "row_index": i,
                            "cells": row,
                            "row_text": row_text,
                            "page_number": None,
                            "line_number": None,
                        }
                    )
                self.table_entries.append(
                    {
                        "table_index": t.get("table_index", len(self.table_entries)),
                        "page_number": None,
                        "rows": row_entries,
                    }
                )

    @staticmethod
    def _clean_number(token: str) -> float | None:
        token = QAGenerateAgent._normalize_numeric_token(token)
        neg = token.startswith("(") and token.endswith(")")
        token = token.strip("()$")
        token = token.replace(",", "")
        token = token.replace("%", "")
        if not token:
            return None
        try:
            value = float(token)
            return -value if neg else value
        except ValueError:
            return None

    @staticmethod
    def _normalize_numeric_token(token: str) -> str:
        token = token.strip()
        # Common DOCX-table artifact: opening parenthesis without closing one.
        if token.startswith("(") and not token.endswith(")"):
            token = f"{token})"
        return token

    @staticmethod
    def _best_financial_number(text: str) -> str | None:
        text_low = text.lower()
        if "note " in text_low and not MONEY_OR_RATE_RE.search(text):
            return None

        # Prefer explicit monetary amounts and percentages.
        prioritized = [
            QAGenerateAgent._normalize_numeric_token(m.group(0))
            for m in MONEY_OR_RATE_RE.finditer(text)
        ]
        if prioritized:
            for tok in prioritized:
                if "%" in tok or "$" in tok:
                    return tok
            return prioritized[0]

        # Fallback: select a non-date numeric token in financial context.
        cands = [QAGenerateAgent._normalize_numeric_token(t) for t in NUM_RE.findall(text)]
        for tok in cands:
            t = tok.strip("(),$")
            if not t:
                continue
            if len(t) <= 2:
                continue
            if t in {"2024", "2025", "2026"}:
                continue
            return tok
        return None

    @staticmethod
    def _all_numbers(text: str) -> list[str]:
        return NUM_RE.findall(text)

    @staticmethod
    def _append_sentence_unit(token: str, sentence: str) -> str:
        """Attach nearby unit information from sentence text when available."""
        if "%" in token:
            return token

        unit_match = re.search(
            re.escape(token) + r"\s*(million|billion|thousand|trillion)\b",
            sentence,
            flags=re.IGNORECASE,
        )
        if unit_match:
            unit = unit_match.group(1).lower()
            if token.startswith("$"):
                return f"{token} {unit} USD"
            return f"{token} {unit}"

        if token.startswith("$"):
            return f"{token} USD"
        return token

    @staticmethod
    def _table_unit_context(header: list[str], row: list[str], label: str) -> str:
        joined_header = " ".join(header).lower()
        joined_row = " ".join(row).lower()
        llabel = label.lower()

        if "shares" in joined_row or "outstanding" in joined_header:
            return "shares"

        if "except per share" in joined_header and llabel in {"basic", "diluted"}:
            return "USD/share"

        is_currency = "$" in " ".join(row) or "$" in " ".join(header)

        scale = ""
        if "in millions" in joined_header:
            scale = "million"
        elif "in billions" in joined_header:
            scale = "billion"
        elif "in thousands" in joined_header:
            scale = "thousand"

        if is_currency and scale:
            return f"USD {scale}"
        if is_currency:
            return "USD"
        if scale:
            return scale
        return ""

    @staticmethod
    def _with_unit(token: str, unit_context: str) -> str:
        token = token.strip()
        if not unit_context or "%" in token:
            return token
        if any(ch.isalpha() for ch in token):
            return token
        return f"{token} {unit_context}"

    @staticmethod
    def _has_financial_context(text: str) -> bool:
        low = text.lower()
        if any(n in low for n in NOISE_KEYWORDS):
            return False
        return any(k in low for k in FIN_KEYWORDS)

    @staticmethod
    def _sentence_spans(text: str) -> list[tuple[str, int, int]]:
        spans: list[tuple[str, int, int]] = []
        start = 0
        for m in SPLIT_RE.finditer(text):
            end = m.start()
            seg = text[start:end].strip()
            if seg:
                s = text.find(seg, start, end)
                spans.append((seg, s, s + len(seg)))
            start = m.end()
        tail = text[start:].strip()
        if tail:
            s = text.find(tail, start)
            spans.append((tail, s, s + len(tail)))
        return spans

    @staticmethod
    def _evidence_obj(
        text: str,
        page_number: int | None,
        line_number: int | None,
        start_offset: int,
        end_offset: int,
    ) -> dict[str, Any]:
        return {
            "text": text,
            "page_number": page_number,
            "line_number": line_number,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "offset_convention": {
                "library": "python3-str",
                "unit": "unicode_codepoint",
                "index_base": 0,
                "range": "[start_offset, end_offset)",
            },
        }

    def _numeric_sentences(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in self.paragraph_entries:
            ptext = p["text"]
            for s, s_start, s_end in self._sentence_spans(ptext):
                if len(s) < 35:
                    continue
                if NUM_RE.search(s) and self._has_financial_context(s):
                    # Filter metadata/date-heavy sentences with no financial amounts/rates.
                    if not MONEY_OR_RATE_RE.search(s):
                        if not any(u in s.lower() for u in UNIT_WORDS):
                            continue
                    out.append(
                        {
                            "sentence": s,
                            "sentence_start": s_start,
                            "sentence_end": s_end,
                            "page_number": p.get("page_number"),
                            "line_number": p.get("line_number"),
                        }
                    )
        # dedupe while preserving order
        seen = set()
        deduped: list[dict[str, Any]] = []
        for s in out:
            key = s["sentence"].lower()
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        return deduped

    def _table_rows_with_numbers(self) -> list[dict[str, Any]]:
        rows_out: list[dict[str, Any]] = []
        for ti, t in enumerate(self.table_entries):
            row_entries = t.get("rows", [])
            rows = [r.get("cells", []) for r in row_entries]
            if not rows:
                continue

            # Build table-level unit context from leading rows, not only the selected header.
            preview_rows = rows[: min(len(rows), 8)]
            preview_text = " ".join(" ".join(c.strip() for c in r if c) for r in preview_rows).lower()
            table_scale = ""
            if "in millions" in preview_text:
                table_scale = "million"
            elif "in billions" in preview_text:
                table_scale = "billion"
            elif "in thousands" in preview_text:
                table_scale = "thousand"
            table_has_dollar = "$" in " ".join(" ".join(r) for r in rows)
            table_unit_context = ""
            if table_has_dollar and table_scale:
                table_unit_context = f"USD {table_scale}"
            elif table_has_dollar:
                table_unit_context = "USD"
            elif table_scale:
                table_unit_context = table_scale

            # Find a usable header row with at least 2 non-empty cells.
            header_idx = None
            for idx, row in enumerate(rows[:6]):
                non_empty = [c for c in row if c.strip()]
                if len(non_empty) >= 2:
                    header_idx = idx
                    break
            if header_idx is None:
                continue

            header = [c.strip() for c in rows[header_idx]]

            for ri, row in enumerate(rows[header_idx + 1 :], start=header_idx + 1):
                label = row[0].strip() if row else ""
                if not label:
                    continue
                nums_in_row = sum(1 for cell in row if NUM_RE.search(cell or ""))
                if nums_in_row < 1:
                    continue
                if not self._has_financial_context(label) and nums_in_row < 2:
                    continue
                src_row = row_entries[ri] if ri < len(row_entries) else {}
                rows_out.append(
                    {
                        "table_index": ti,
                        "row_index": ri,
                        "header": header,
                        "row": [c.strip() for c in row],
                        "row_text": src_row.get("row_text", " | ".join(c.strip() for c in row)),
                        "page_number": src_row.get("page_number"),
                        "line_number": src_row.get("line_number"),
                        "label": label,
                        "table_unit_context": table_unit_context,
                    }
                )
        return rows_out

    def generate_group1(self, target: int) -> list[QAPair]:
        candidates = self._numeric_sentences()
        qas: list[QAPair] = []

        for cand in candidates:
            sent = cand["sentence"]
            ans = self._best_financial_number(sent)
            if not ans:
                continue

            # Skip category-like answers that are unlikely to be financial results.
            raw = ans.strip("(),$")
            if raw.isdigit() and len(raw) <= 2:
                continue

            # Use a context fragment as subject, but strip date-heavy prefixes.
            subject = sent
            for linker in [" was ", " were ", " is ", " are ", " increased", " decreased"]:
                pos = sent.lower().find(linker)
                if pos > 18:
                    subject = sent[:pos].strip()
                    break
            subject = re.sub(
                r"^(As of|For the (three|six|nine|twelve) months ended|During the period ended)\s+[^,]+,\s*",
                "",
                subject,
                flags=re.IGNORECASE,
            )
            subject = re.sub(r"^In (the|this) (quarter|period),\s*", "", subject, flags=re.IGNORECASE)

            # If subject is still too generic, anchor on first financial keyword neighborhood.
            if len(subject) < 20 or subject.lower().startswith("as of"):
                low = sent.lower()
                kpos = -1
                for k in FIN_KEYWORDS:
                    p = low.find(k)
                    if p >= 0 and (kpos < 0 or p < kpos):
                        kpos = p
                if kpos >= 0:
                    left = max(0, kpos - 35)
                    right = min(len(sent), kpos + 85)
                    subject = sent[left:right].strip(" ,.;:")
            subject = re.sub(r"\s+", " ", subject)[:140]

            q = (
                "According to the MSFT_FY26Q1_10Q.docx file, "
                f"what is the reported amount or rate in this sentence: \"{sent}\"?"
            )
            answer_with_unit = self._append_sentence_unit(ans, sent)
            ans_start = sent.find(ans)
            if ans_start < 0:
                ans_start = 0
            ans_end = ans_start + len(ans)
            qa = QAPair(
                id=f"G1-{len(qas)+1:03d}",
                group="Group1",
                difficulty=1,
                question=q,
                answer=answer_with_unit,
                evidence=self._evidence_obj(
                    sent,
                    cand.get("page_number"),
                    cand.get("line_number"),
                    ans_start,
                    ans_end,
                ),
                verification={
                    "method": "evidence_contains_answer",
                    "passed": ans in sent
                    and bool(MONEY_OR_RATE_RE.search(ans) or any(u in sent.lower() for u in UNIT_WORDS)),
                },
            )
            if qa.verification["passed"]:
                qas.append(qa)
            if len(qas) >= target:
                break

        return qas

    def generate_group2(self, target: int) -> list[QAPair]:
        rows = self._table_rows_with_numbers()
        qas: list[QAPair] = []

        for r in rows:
            header = r["header"]
            row = r["row"]
            label = r["label"]
            ti = r["table_index"]
            global_unit = r.get("table_unit_context", "")
            row_text = r.get("row_text", " | ".join(row))
            page_number = r.get("page_number")
            line_number = r.get("line_number")

            for ci in range(1, min(len(row), len(header))):
                cell = self._normalize_numeric_token(row[ci].strip())
                if not NUM_RE.search(cell):
                    continue
                col = header[ci].strip() or f"column {ci+1}"
                q = (
                    "According to the MSFT_FY26Q1_10Q.docx file, "
                    f"what is the reported value for '{label}' under '{col}'?"
                )
                unit_context = self._table_unit_context(header, row, label) or global_unit
                cell_with_unit = self._with_unit(cell, unit_context)
                offset = row_text.find(cell)
                if offset < 0:
                    offset = 0
                evidence = self._evidence_obj(
                    row_text,
                    page_number,
                    line_number,
                    offset,
                    offset + len(cell),
                )
                qa = QAPair(
                    id=f"G2-{len(qas)+1:03d}",
                    group="Group2",
                    difficulty=2,
                    question=q,
                    answer=cell_with_unit,
                    evidence=evidence,
                    verification={
                        "method": "table_row_column_lookup",
                        "passed": cell in evidence["text"],
                    },
                )
                if qa.verification["passed"]:
                    qas.append(qa)
                if len(qas) >= target:
                    return qas

        return qas

    def generate_group3(self, target: int) -> list[QAPair]:
        rows = self._table_rows_with_numbers()
        qas: list[QAPair] = []

        # A) In-row comparisons across columns.
        for r in rows:
            header = r["header"]
            row = r["row"]
            label = r["label"]
            ti = r["table_index"]
            global_unit = r.get("table_unit_context", "")
            row_text = r.get("row_text", " | ".join(row))
            page_number = r.get("page_number")
            line_number = r.get("line_number")

            # collect numeric columns only
            num_cols: list[tuple[int, str, float]] = []
            for ci in range(1, min(len(row), len(header))):
                token = self._normalize_numeric_token(row[ci].strip())
                if not NUM_RE.search(token):
                    continue
                value = self._clean_number(token)
                if value is None:
                    continue
                col = header[ci].strip() or f"column {ci+1}"
                num_cols.append((ci, token, value))

            if len(num_cols) < 2:
                continue

            (_, tok1, v1), (_, tok2, v2) = num_cols[0], num_cols[1]
            c1 = header[num_cols[0][0]].strip() or f"column {num_cols[0][0]+1}"
            c2 = header[num_cols[1][0]].strip() or f"column {num_cols[1][0]+1}"

            diff = v1 - v2
            pct = (diff / abs(v2) * 100.0) if v2 != 0 else None
            unit_context = self._table_unit_context(header, row, label) or global_unit
            diff_base = f"{diff:,.2f}"
            diff_ans = self._with_unit(diff_base, unit_context)
            pct_ans = "n/a" if pct is None else f"{pct:.2f}%"

            q1 = (
                "According to the MSFT_FY26Q1_10Q.docx file, "
                f"what is the absolute difference for '{label}' between '{c1}' and '{c2}'?"
            )
            e1 = f"Row: {row_text} | Computation: {v1} - {v2} = {diff_base}"
            e1_start = e1.rfind(diff_base)
            qas.append(
                QAPair(
                    id=f"G3-{len(qas)+1:03d}",
                    group="Group3",
                    difficulty=3,
                    question=q1,
                    answer=diff_ans,
                    evidence=self._evidence_obj(
                        e1,
                        page_number,
                        line_number,
                        max(0, e1_start),
                        max(0, e1_start) + len(diff_base),
                    ),
                    verification={
                        "method": "arithmetic_diff",
                        "passed": True,
                        "inputs": [tok1, tok2],
                    },
                )
            )
            if len(qas) >= target:
                return qas

            q2 = (
                "According to the MSFT_FY26Q1_10Q.docx file, "
                f"what is the percent change for '{label}' from '{c2}' to '{c1}'?"
            )
            e2 = f"Row: {row_text} | Computation: ({v1} - {v2}) / |{v2}| * 100 = {pct_ans}"
            e2_start = e2.rfind(pct_ans)
            qas.append(
                QAPair(
                    id=f"G3-{len(qas)+1:03d}",
                    group="Group3",
                    difficulty=3,
                    question=q2,
                    answer=pct_ans,
                    evidence=self._evidence_obj(
                        e2,
                        page_number,
                        line_number,
                        max(0, e2_start),
                        max(0, e2_start) + len(pct_ans),
                    ),
                    verification={
                        "method": "arithmetic_percent_change",
                        "passed": True,
                        "inputs": [tok1, tok2],
                    },
                )
            )
            if len(qas) >= target:
                return qas

        # B) Cross-row same-column ratios to increase difficulty.
        for i in range(0, max(0, len(rows) - 1)):
            if len(qas) >= target:
                break
            r1 = rows[i]
            r2 = rows[i + 1]
            if r1["table_index"] != r2["table_index"]:
                continue

            h1, row1, label1 = r1["header"], r1["row"], r1["label"]
            _, row2, label2 = r2["header"], r2["row"], r2["label"]
            row1_text = r1.get("row_text", " | ".join(row1))
            row2_text = r2.get("row_text", " | ".join(row2))
            for ci in range(1, min(len(row1), len(row2), len(h1))):
                t1, t2 = row1[ci].strip(), row2[ci].strip()
                t1 = self._normalize_numeric_token(t1)
                t2 = self._normalize_numeric_token(t2)
                if not NUM_RE.search(t1) or not NUM_RE.search(t2):
                    continue
                v1 = self._clean_number(t1)
                v2 = self._clean_number(t2)
                if v1 is None or v2 is None or v2 == 0:
                    continue
                ratio = v1 / v2
                col = h1[ci].strip() or f"column {ci+1}"
                q = (
                    "According to the MSFT_FY26Q1_10Q.docx file, "
                    f"what is the ratio of '{label1}' to '{label2}' for '{col}'?"
                )
                ratio_base = f"{ratio:.4f}"
                e = f"Rows: {row1_text} || {row2_text} | Computation: {v1} / {v2} = {ratio_base}"
                ratio_ans = f"{ratio:.4f}x"
                e_start = e.rfind(ratio_base)
                qas.append(
                    QAPair(
                        id=f"G3-{len(qas)+1:03d}",
                        group="Group3",
                        difficulty=3,
                        question=q,
                        answer=ratio_ans,
                        evidence=self._evidence_obj(
                            e,
                            r1.get("page_number"),
                            r1.get("line_number"),
                            max(0, e_start),
                            max(0, e_start) + len(ratio_base),
                        ),
                        verification={"method": "arithmetic_ratio", "passed": True},
                    )
                )
                break

        return qas[:target]

    def iterative_generate_and_verify(
        self,
        group_targets: dict[str, int],
        max_rounds: int = 4,
    ) -> dict[str, list[QAPair]]:
        """Iteratively generate and verify QAs until targets are reached."""
        groups: dict[str, list[QAPair]] = {"Group1": [], "Group2": [], "Group3": []}

        for _round in range(1, max_rounds + 1):
            if len(groups["Group1"]) < group_targets["Group1"]:
                needed = group_targets["Group1"] - len(groups["Group1"])
                groups["Group1"].extend(self.generate_group1(needed * 2))
            if len(groups["Group2"]) < group_targets["Group2"]:
                needed = group_targets["Group2"] - len(groups["Group2"])
                groups["Group2"].extend(self.generate_group2(needed * 2))
            if len(groups["Group3"]) < group_targets["Group3"]:
                needed = group_targets["Group3"] - len(groups["Group3"])
                groups["Group3"].extend(self.generate_group3(needed * 2))

            # Verify and de-duplicate per group
            for g in ["Group1", "Group2", "Group3"]:
                dedup: list[QAPair] = []
                seen = set()
                for qa in groups[g]:
                    key = (qa.question.lower(), qa.answer)
                    if key in seen:
                        continue
                    seen.add(key)
                    if qa.verification.get("passed"):
                        dedup.append(qa)
                groups[g] = dedup[: group_targets[g]]

            if all(len(groups[g]) >= group_targets[g] for g in group_targets):
                break

        # Re-number IDs after final selection
        for g in ["Group1", "Group2", "Group3"]:
            for i, qa in enumerate(groups[g], start=1):
                qa.id = f"{g.replace('Group', 'G')}-{i:03d}"

        return groups


def write_outputs(groups: dict[str, list[QAPair]], out_json: Path, out_md: Path) -> None:
    all_qas: list[QAPair] = groups["Group1"] + groups["Group2"] + groups["Group3"]

    payload = {
        "summary": {
            "total": len(all_qas),
            "group_counts": {k: len(v) for k, v in groups.items()},
        },
        "qa_pairs": [qa.to_dict() for qa in all_qas],
    }
    out_json.write_text(json.dumps(payload, indent=2))

    lines = [
        "# MSFT FY26Q1 10-Q Benchmark QAs",
        "",
        f"Total pairs: {len(all_qas)}",
        "",
        "## Counts",
        "",
        f"- Group1 (paragraph-direct): {len(groups['Group1'])}",
        f"- Group2 (table row/column lookup): {len(groups['Group2'])}",
        f"- Group3 (multi-step inference): {len(groups['Group3'])}",
        "",
    ]

    for g in ["Group1", "Group2", "Group3"]:
        lines.append(f"## {g}")
        lines.append("")
        for qa in groups[g]:
            lines.append(f"### {qa.id}")
            lines.append(f"Q: {qa.question}")
            lines.append(f"A: {qa.answer}")
            lines.append(f"Evidence: {qa.evidence}")
            lines.append("")

    out_md.write_text("\n".join(lines))


def main() -> None:
    agent = QAGenerateAgent(Path("msft_docx_structured.json"))
    targets = {
        "Group1": 30,
        "Group2": 40,
        "Group3": 30,
    }

    groups = agent.iterative_generate_and_verify(targets)

    missing = {k: targets[k] - len(v) for k, v in groups.items()}
    if any(v > 0 for v in missing.values()):
        raise RuntimeError(f"Could not meet target counts, missing={missing}")

    write_outputs(
        groups,
        Path("msft_fy26q1_qa_benchmark_100.json"),
        Path("msft_fy26q1_qa_benchmark_100.md"),
    )

    print("Generated benchmark:")
    print({k: len(v) for k, v in groups.items()})


if __name__ == "__main__":
    main()
