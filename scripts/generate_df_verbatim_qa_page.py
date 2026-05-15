#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_json(
    base_url: str,
    path: str,
    *,
    token: str | None = None,
    form_body: dict[str, str] | None = None,
) -> Any:
    headers: dict[str, str] = {"Accept": "application/json"}
    body: bytes | None = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form_body is not None:
        body = urllib.parse.urlencode(form_body).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method="POST" if form_body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    return json.loads(payload)


def _login(base_url: str, username: str, password: str) -> str:
    payload = _request_json(
        base_url,
        "/auth/jwt/login",
        form_body={"username": username, "password": password},
    )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Login succeeded but access_token missing")
    return token


def _resolve_df_document(base_url: str, token: str, search_space_id: int, title_contains: str) -> dict[str, Any]:
    docs_payload = _request_json(
        base_url,
        f"/api/v1/documents?search_space_id={search_space_id}&page_size=-1",
        token=token,
    )
    docs = docs_payload.get("items", []) if isinstance(docs_payload, dict) else docs_payload
    if not isinstance(docs, list):
        raise RuntimeError("Unexpected documents payload")

    needle = title_contains.strip().lower()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        title = str(doc.get("title", "")).lower()
        if needle in title:
            return doc
    raise RuntimeError(f"No document matched title contains: {title_contains}")


def _find_span(content: str, evidence_text: str, start_offset: Any, end_offset: Any) -> tuple[int | None, int | None, str]:
    if isinstance(start_offset, int) and isinstance(end_offset, int):
        if 0 <= start_offset <= end_offset <= len(content):
            if content[start_offset:end_offset] == evidence_text:
                return start_offset, end_offset, "offset_exact"

    if evidence_text:
        idx = content.find(evidence_text)
        if idx >= 0:
            return idx, idx + len(evidence_text), "search_exact"
        idx_ci = content.lower().find(evidence_text.lower())
        if idx_ci >= 0:
            return idx_ci, idx_ci + len(evidence_text), "search_case_insensitive"

    return None, None, "not_found"


def _render_source_with_marks(content: str, spans: list[dict[str, Any]]) -> str:
    valid = [s for s in spans if isinstance(s.get("start"), int) and isinstance(s.get("end"), int)]
    valid.sort(key=lambda item: int(item["start"]))

    out: list[str] = []
    cursor = 0
    for item in valid:
        start = int(item["start"])
        end = int(item["end"])
        if start < cursor or end < start or end > len(content):
            continue
        out.append(html.escape(content[cursor:start]))
        snippet = html.escape(content[start:end])
        out.append(
            f"<mark class=\"hit\" id=\"{html.escape(item['anchor'])}\" title=\"{html.escape(item['label'])}\">{snippet}</mark>"
        )
        cursor = end
    out.append(html.escape(content[cursor:]))
    return "".join(out)


def _build_html(title: str, source_html: str, rows: list[dict[str, Any]]) -> str:
    qa_items: list[str] = []
    for row in rows:
        q = html.escape(row["question"])
        effective_query = html.escape(row["effective_query"])
        a = html.escape(row["answer"])
        qid = html.escape(row["qid_unique"])
        how = html.escape(row["match_method"])
        if row["anchor"]:
            link = f"<a href=\"#{html.escape(row['anchor'])}\" class=\"jump\">Open highlighted source</a>"
        else:
            link = "<span class=\"missing\">No verbatim match found</span>"

        qa_items.append(
            "<div class=\"qa\">"
            f"<div class=\"meta\">{qid} · {how}</div>"
            f"<div class=\"q\"><b>Q (df_qa.json):</b> {q}</div>"
            f"<div class=\"q\"><b>Effective query:</b> {effective_query}</div>"
            f"<div class=\"a\"><b>A:</b> {a}</div>"
            f"<div class=\"l\">{link}</div>"
            "</div>"
        )

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>{html.escape(title)} - Verbatim QA Links</title>
  <style>
    body {{ font-family: Inter, Arial, sans-serif; margin: 0; background: #0b1220; color: #dbe5ff; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 16px; }}
    h1, h2 {{ margin: 12px 0; }}
    .panel {{ background: #121a2c; border: 1px solid #27324d; border-radius: 10px; padding: 12px; margin-bottom: 16px; }}
    .source {{ white-space: pre-wrap; word-break: break-word; line-height: 1.45; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .hit {{ background: #ffd84d; color: #1b1b1b; padding: 1px 2px; border-radius: 3px; }}
    .qa {{ border: 1px solid #2c395a; border-radius: 8px; padding: 10px; margin-bottom: 10px; background: #10192b; }}
    .meta {{ color: #9fb5ff; font-size: 12px; margin-bottom: 6px; }}
    .q, .a, .l {{ margin-bottom: 6px; }}
    .jump {{ color: #70e1ff; text-decoration: none; }}
    .jump:hover {{ text-decoration: underline; }}
    .missing {{ color: #ff9a9a; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>{html.escape(title)} - Source + Verbatim QA Section</h1>
    <div class=\"panel\">
      <h2>df.html Source</h2>
      <div class=\"source\">{source_html}</div>
    </div>
    <div class=\"panel\">
      <h2>Questions and Answers (one by one)</h2>
      {''.join(qa_items)}
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate df.html page with QA links to highlighted verbatim matches")
    parser.add_argument("--config", default="benchmark_runner_config.json")
    parser.add_argument("--base-url", default="http://localhost:8930")
    parser.add_argument("--search-space-id", type=int, default=1)
    parser.add_argument("--document-title-contains", default="df.html")
    parser.add_argument("--benchmark-file", default="df_qa.json")
    parser.add_argument(
        "--output-file",
        default="benchmark_results_df_html_qa/df_verbatim_qa_section.html",
    )
    args = parser.parse_args()

    cfg = _read_json(Path(args.config))
    username = str(cfg.get("USERNAME") or cfg.get("username") or "").strip()
    password = str(cfg.get("PASSWORD") or cfg.get("password") or "").strip()
    if not username or not password:
        raise RuntimeError("Missing USERNAME/PASSWORD in config")

    token = _login(args.base_url, username, password)
    doc = _resolve_df_document(
        args.base_url,
        token,
        args.search_space_id,
        args.document_title_contains,
    )
    doc_id = int(doc.get("id"))
    doc_detail = _request_json(args.base_url, f"/api/v1/documents/{doc_id}", token=token)
    content = doc_detail.get("content") or ""
    if not isinstance(content, str):
        content = str(content)

    qas = _read_json(Path(args.benchmark_file)).get("qa_pairs", [])
    if not isinstance(qas, list):
        raise RuntimeError("Benchmark file missing qa_pairs list")

    rows: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    for i, qa in enumerate(qas, start=1):
        qid = str(qa.get("id", f"Q{i}"))
        unique = f"{qid}-{i:03d}"
        question = str(qa.get("question", "")).strip()
        answer = str(qa.get("answer", "")).strip()
        fund_name = str(qa.get("fund_name", "")).strip()
        fund_family = str(qa.get("fund_family", "")).strip()
        fund_class = str(qa.get("class", "")).strip()

        scope_parts: list[str] = []
        if fund_name:
            if fund_class:
                scope_parts.append(f"{fund_name} ({fund_class})")
            else:
                scope_parts.append(fund_name)
        elif fund_class:
            scope_parts.append(fund_class)

        if fund_family:
            scope_parts.append(f"of {fund_family}")

        scope = " ".join(scope_parts).strip()
        if scope and question:
            effective_query = f"Locate {scope}. {question} Restrict extraction to this fund and class only."
        elif question:
            effective_query = question
        else:
            effective_query = f"Locate {scope}. Restrict extraction to this fund and class only." if scope else ""

        evidence = qa.get("evidence") if isinstance(qa.get("evidence"), dict) else {}
        evidence_text = str(evidence.get("text", ""))

        start, end, method = _find_span(
            content,
            evidence_text,
            evidence.get("start_offset"),
            evidence.get("end_offset"),
        )
        anchor = None
        if start is not None and end is not None:
            anchor = f"match-{unique}"
            spans.append(
                {
                    "start": start,
                    "end": end,
                    "anchor": anchor,
                    "label": f"{unique} ({method})",
                }
            )

        rows.append(
            {
                "qid_unique": unique,
                "question": question,
                "effective_query": effective_query,
                "answer": answer,
                "match_method": method,
                "anchor": anchor,
            }
        )

    source_html = _render_source_with_marks(content, spans)
    title = str(doc_detail.get("title") or "df.html")
    page = _build_html(title, source_html, rows)

    out = Path(args.output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"generated: {out}")
    print(f"document_id: {doc_id}, questions: {len(rows)}, matched_links: {sum(1 for r in rows if r['anchor'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
