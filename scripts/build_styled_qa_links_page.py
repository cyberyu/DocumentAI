#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from pathlib import Path

BASE_HTML = Path("benchmark_results_df_html_qa/df_verbatim_qa_section.html")
RUN_JSON = Path("benchmark_results_df_html_qa/df_source_verbatim_5q_subproc.json")
OUT_HTML = Path("benchmark_results_df_html_qa/df_source_verbatim_3q_linked_answers.html")


def main() -> int:
    base = BASE_HTML.read_text(encoding="utf-8")
    run = json.loads(RUN_JSON.read_text(encoding="utf-8"))
    results = run.get("results", [])[:3]

    blocks: list[str] = []
    for i, row in enumerate(results, start=1):
        qid = str(row.get("id", f"Q{i}"))
        question = str(row.get("question", "")).strip()
        pred = str(row.get("predicted_answer", "")).strip()
        gold = str(row.get("gold_answer", "")).strip()
        anchor = f"match-{qid}-{i:03d}"
        link = f'<a href="#{anchor}" class="jump">Open highlighted source</a>'

        blocks.append(
            "<div class=\"qa\">"
            f"<div class=\"meta\">{html.escape(qid)} · source-verbatim-match</div>"
            f"<div class=\"q\"><b>Q:</b> {html.escape(question)}</div>"
            f"<div class=\"a\"><b>Predicted:</b> {html.escape(pred or '(empty)')}</div>"
            f"<div class=\"a\"><b>Gold:</b> {html.escape(gold)}</div>"
            f"<div class=\"l\">{link}</div>"
            "</div>"
        )

    panel = (
        "\n    <div class=\"panel\">\n"
        "      <h2>3-Question Q&A Linked List (same style)</h2>\n"
        "      <div class=\"meta\">Generated from first 3 rows of df_source_verbatim_5q_subproc.json</div>\n"
        f"      {''.join(blocks)}\n"
        "    </div>\n"
    )

    marker = "  </div>\n</body>"
    pos = base.rfind(marker)
    if pos == -1:
        raise RuntimeError("Could not find insertion marker in base HTML")

    merged = base[:pos] + panel + base[pos:]
    OUT_HTML.write_text(merged, encoding="utf-8")
    print(f"generated: {OUT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
