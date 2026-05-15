#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _decode_text(path: Path, encoding: str) -> str:
    if encoding == "auto":
        raw = path.read_bytes()
        for candidate in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "cp1252"):
            try:
                return raw.decode(candidate)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
    return path.read_text(encoding=encoding)


def _normalize_eol(text: str, mode: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if mode == "lf":
        return normalized
    if mode == "crlf":
        return normalized.replace("\n", "\r\n")
    return text


def _split_lines_keepends(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    return lines if lines else [""]


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _linecol_to_offset(
    text: str,
    line: int,
    col: int,
    *,
    column_unit: str,
) -> int:
    if line < 1 or col < 1:
        raise ValueError("line and col must be 1-based and >= 1")

    lines = _split_lines_keepends(text)
    if line > len(lines):
        raise ValueError(f"line {line} out of range (max {len(lines)})")

    prefix = "".join(lines[: line - 1])
    target_line = lines[line - 1]

    if column_unit == "codepoint":
        idx_in_line = min(col - 1, len(target_line))
    else:
        remaining_units = col - 1
        idx_in_line = 0
        while idx_in_line < len(target_line) and remaining_units > 0:
            ch = target_line[idx_in_line]
            ch_units = _utf16_units(ch)
            if remaining_units - ch_units < 0:
                break
            remaining_units -= ch_units
            idx_in_line += 1

    return len(prefix) + idx_in_line


def _offset_to_linecol(
    text: str,
    offset: int,
    *,
    column_unit: str,
) -> tuple[int, int]:
    if offset < 0 or offset > len(text):
        raise ValueError(f"offset {offset} out of range [0, {len(text)}]")

    lines = _split_lines_keepends(text)
    cursor = 0
    for i, line in enumerate(lines, start=1):
        nxt = cursor + len(line)
        if offset <= nxt:
            in_line = line[: max(0, offset - cursor)]
            if column_unit == "codepoint":
                col = len(in_line) + 1
            else:
                col = _utf16_units(in_line) + 1
            return i, col
        cursor = nxt

    return len(lines), 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert between Notepad-style line/column and benchmark offsets "
            "(python3-str unicode codepoint, 0-based [start, end))."
        )
    )
    parser.add_argument("--text-file", required=True, help="Path to source text file")
    parser.add_argument(
        "--encoding",
        default="auto",
        help="File encoding (default: auto). Examples: utf-8, utf-16-le",
    )
    parser.add_argument(
        "--eol-mode",
        choices=["preserve", "lf", "crlf"],
        default="preserve",
        help="How to interpret line breaks before conversion",
    )
    parser.add_argument(
        "--column-unit",
        choices=["utf16", "codepoint"],
        default="utf16",
        help="Notepad-like column counting unit (default: utf16)",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--to-offset", action="store_true", help="Convert line/col to offsets")
    group.add_argument("--to-linecol", action="store_true", help="Convert offsets to line/col")

    parser.add_argument("--start-line", type=int)
    parser.add_argument("--start-col", type=int)
    parser.add_argument("--end-line", type=int)
    parser.add_argument("--end-col", type=int)
    parser.add_argument("--start-offset", type=int)
    parser.add_argument("--end-offset", type=int)
    parser.add_argument("--json", action="store_true", help="Emit JSON output")

    args = parser.parse_args()

    text = _decode_text(Path(args.text_file), args.encoding)
    view_text = _normalize_eol(text, args.eol_mode)

    if args.to_offset:
        if None in (args.start_line, args.start_col, args.end_line, args.end_col):
            raise SystemExit("--to-offset requires --start-line --start-col --end-line --end-col")
        start_offset = _linecol_to_offset(
            view_text,
            args.start_line,
            args.start_col,
            column_unit=args.column_unit,
        )
        end_offset = _linecol_to_offset(
            view_text,
            args.end_line,
            args.end_col,
            column_unit=args.column_unit,
        )
        if end_offset < start_offset:
            raise SystemExit("end offset is smaller than start offset")

        extracted = view_text[start_offset:end_offset]
        payload = {
            "start_offset": start_offset,
            "end_offset": end_offset,
            "offset_convention": {
                "library": "python3-str",
                "unit": "unicode_codepoint",
                "index_base": 0,
                "range": "[start_offset, end_offset)",
            },
            "extracted_text": extracted,
            "linecol_input": {
                "start_line": args.start_line,
                "start_col": args.start_col,
                "end_line": args.end_line,
                "end_col": args.end_col,
                "column_unit": args.column_unit,
                "eol_mode": args.eol_mode,
            },
        }
    else:
        if None in (args.start_offset, args.end_offset):
            raise SystemExit("--to-linecol requires --start-offset --end-offset")
        if args.end_offset < args.start_offset:
            raise SystemExit("end offset is smaller than start offset")

        s_line, s_col = _offset_to_linecol(
            view_text,
            args.start_offset,
            column_unit=args.column_unit,
        )
        e_line, e_col = _offset_to_linecol(
            view_text,
            args.end_offset,
            column_unit=args.column_unit,
        )
        extracted = view_text[args.start_offset : args.end_offset]
        payload = {
            "start_line": s_line,
            "start_col": s_col,
            "end_line": e_line,
            "end_col": e_col,
            "column_unit": args.column_unit,
            "eol_mode": args.eol_mode,
            "offset_input": {
                "start_offset": args.start_offset,
                "end_offset": args.end_offset,
            },
            "extracted_text": extracted,
        }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
