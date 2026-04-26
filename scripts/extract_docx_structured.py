import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def _norm_text(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split())


def _p_text(p: ET.Element) -> str:
    texts = [t.text or "" for t in p.findall(".//w:t", NS)]
    return _norm_text("".join(texts))


def _page_break_count(elem: ET.Element) -> int:
    br_count = len(elem.findall(".//w:br[@w:type='page']", NS))
    rendered_count = len(elem.findall(".//w:lastRenderedPageBreak", NS))
    return br_count + rendered_count


def main() -> None:
    docx_path = Path("MSFT_FY26Q1_10Q.docx")

    with zipfile.ZipFile(docx_path, "r") as zf:
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("Could not parse document body from DOCX")

    page_number = 1
    line_number = 1
    table_index = 0

    paragraph_entries: list[dict] = []
    table_entries: list[dict] = []
    paragraphs: list[str] = []
    tables: list[dict] = []

    for child in list(body):
        tag = child.tag.split("}")[-1]

        if tag == "p":
            text = _p_text(child)
            breaks = _page_break_count(child)
            if text:
                paragraph_entries.append(
                    {
                        "paragraph_index": len(paragraph_entries),
                        "text": text,
                        "page_number": page_number,
                        "line_number": line_number,
                    }
                )
                paragraphs.append(text)
                line_number += 1
            page_number += breaks

        elif tag == "tbl":
            rows_raw: list[list[str]] = []
            row_entries: list[dict] = []

            for tr in child.findall(".//w:tr", NS):
                row_cells: list[str] = []
                for tc in tr.findall("./w:tc", NS):
                    parts: list[str] = []
                    for p in tc.findall(".//w:p", NS):
                        t = _p_text(p)
                        if t:
                            parts.append(t)
                    row_cells.append(_norm_text(" ".join(parts)))

                if any(c for c in row_cells):
                    row_text = _norm_text(" | ".join(row_cells))
                    row_entries.append(
                        {
                            "row_index": len(row_entries),
                            "cells": row_cells,
                            "row_text": row_text,
                            "page_number": page_number,
                            "line_number": line_number,
                        }
                    )
                    rows_raw.append(row_cells)
                    line_number += 1

            if rows_raw:
                table_entries.append(
                    {
                        "table_index": table_index,
                        "page_number": page_number,
                        "rows": row_entries,
                    }
                )
                tables.append({"table_index": table_index, "rows": rows_raw})
                table_index += 1

            page_number += _page_break_count(child)

    out = {
        "docx_path": str(docx_path.resolve()),
        "paragraph_count": len(paragraphs),
        "table_count": len(tables),
        "paragraphs": paragraphs,
        "tables": tables,
        "paragraph_entries": paragraph_entries,
        "table_entries": table_entries,
    }

    out_path = Path("msft_docx_structured.json")
    out_path.write_text(json.dumps(out, indent=2))
    print(
        f"Wrote {out_path} with paragraphs={len(paragraphs)} "
        f"tables={len(tables)} lines={line_number-1}"
    )


if __name__ == "__main__":
    main()
