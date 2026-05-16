#!/usr/bin/env python3
"""
Test script: verbatim evidence extraction with context (2-3 sentences).

Demonstrates how to take a predicted answer (e.g. "0.80") and the 
top-ranked chunk's content, find the exact verbatim match, and return
the match + surrounding context for better evidence traceability.

Usage:
    python3 test_verbatim_evidence.py
"""

import json
import re
from pathlib import Path


# ── Utility functions (mirroring source_verbatim.py logic) ──────────────────

_SIGNED_NUM_RE = re.compile(
    r"\(?[-+]?[$\u20ac\u00a3\u00a5]?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?"
    r"|[-+]?[$\u20ac\u00a3\u00a5]?\d+(?:\.\d+)?"
)


def _clean_text(value: str) -> str:
    text = (value or "").strip()
    text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_final_value_candidate(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    bool_matches = list(re.finditer(r"\b(?:yes|no|true|false|n/?a)\b", cleaned, flags=re.IGNORECASE))
    if bool_matches:
        return bool_matches[-1].group(0)
    value_matches = list(re.finditer(
        r"[$\u20ac\u00a3\u00a5]?[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?"
        r"(?:\s*(?:billion|million|thousand|percent|%|bps|basis points|usd|dollars?))?"
        r"|[$\u20ac\u00a3\u00a5]?[-+]?\d+(?:\.\d+)?"
        r"(?:\s*(?:billion|million|thousand|percent|%|bps|basis points|usd|dollars?))?",
        cleaned, flags=re.IGNORECASE,
    ))
    if value_matches:
        return value_matches[-1].group(0).strip(" .,:;")
    chunks = [chunk.strip() for chunk in re.split(r"[\n\r]+", cleaned) if chunk.strip()]
    if chunks:
        tail = chunks[-1].strip(" .,:;")
        if len(tail) <= 120:
            return tail
    return cleaned


def _find_text_span(haystack: str, needle: str):
    source = haystack or ""
    target = (needle or "").strip()
    if not source or not target:
        return None
    start = source.find(target)
    if start >= 0:
        return start, start + len(target), "exact"
    start_lower = source.lower().find(target.lower())
    if start_lower >= 0:
        return start_lower, start_lower + len(target), "case_insensitive"
    # Try stripping leading zero for decimal values (e.g. "0.80" vs ".80")
    if target.startswith("0") and len(target) > 1 and target[1] == ".":
        stripped = target[1:]
        start = source.find(stripped)
        if start >= 0:
            return start, start + len(stripped), "stripped_leading_zero"
    # Try adding leading zero (e.g. ".80" in source, "0.80" predicted)
    if target.startswith("."):
        with_zero = "0" + target
        start = source.find(with_zero)
        if start >= 0:
            return start, start + len(with_zero), "added_leading_zero"
    return None


def _extract_numeric_entities(value: str) -> list[dict]:
    entities = []
    text = _clean_text(value)
    for match in _SIGNED_NUM_RE.finditer(text):
        raw = match.group(0)
        negative = raw.startswith("(") and raw.endswith(")")
        num_text = re.sub(r"[$\u20ac\u00a3\u00a5,]", "", raw.strip("()"))
        try:
            base = float(num_text)
        except ValueError:
            continue
        if negative:
            base = -base
        lo = max(0, match.start() - 20)
        hi = min(len(text), match.end() + 20)
        window = text[lo:hi]
        if any(k in window.lower() for k in ["%", "percent", "percentage"]):
            utype = "percent"
        elif "$" in window or "usd" in window or "dollar" in window:
            utype = "currency"
        else:
            utype = "count"
        scale = 1.0
        if "billion" in window.lower() or re.search(r"(?<=\d)b\b", window):
            scale = 1_000_000_000.0
        elif "million" in window.lower() or re.search(r"(?<=\d)m\b", window):
            scale = 1_000_000.0
        elif "thousand" in window.lower() or re.search(r"(?<=\d)k\b", window):
            scale = 1_000.0
        entities.append({
            "raw": raw, "start": match.start(), "end": match.end(),
            "type": utype, "normalized": base * scale,
        })
    return entities


def _entity_match(gold: dict, pred: dict, tolerance=0.01) -> bool:
    if gold["type"] != pred["type"]:
        return False
    allowed = max(1e-9, abs(gold["normalized"]) * tolerance)
    return abs(gold["normalized"] - pred["normalized"]) <= allowed


def _find_entity_aligned_span(haystack: str, candidate: str):
    target_entities = _extract_numeric_entities(candidate)
    if not target_entities:
        return None
    target = target_entities[0]
    for entity in _extract_numeric_entities(haystack):
        if _entity_match(target, entity):
            start = int(entity.get("start", 0))
            end = int(entity.get("end", start))
            suffix = haystack[end:]
            unit_match = re.match(
                r"^\s*(?:billion|million|thousand|percent|%|bps|basis points|usd|dollars?)\b",
                suffix, flags=re.IGNORECASE,
            )
            if unit_match:
                end += unit_match.end()
            return start, end, "numeric_entity"
    return None


def extract_evidence_context(source_text: str, match_start: int, match_end: int) -> str:
    """
    Extract 2-3 sentences of context around a match in source text.
    Falls back to a character window if sentence boundaries are unreliable.
    """
    if not source_text or match_start is None or match_end is None:
        return ""

    # Split source into sentences on . ! ? followed by space or end
    sent_ends = [m.end() for m in re.finditer(r'(?<=[.!?])\s+|(?<=[.!?])$', source_text)]
    sent_starts = [0] + sent_ends[:-1]

    # Find which sentence index contains the match
    match_sent_idx = None
    for i, (ss, se) in enumerate(zip(sent_starts, sent_ends)):
        if ss <= match_start < se or ss <= match_end <= se:
            match_sent_idx = i
            break

    if match_sent_idx is not None:
        # Take the matching sentence, plus one before and one after (2-3 sentences)
        ctx_start_idx = max(0, match_sent_idx - 1)
        ctx_end_idx = min(len(sent_starts), match_sent_idx + 2)
        if ctx_end_idx <= ctx_start_idx + 1:
            ctx_end_idx = min(len(sent_starts), ctx_start_idx + 2)

        ctx_start = sent_starts[ctx_start_idx]
        ctx_end = sent_ends[ctx_end_idx - 1]
        context = source_text[ctx_start:ctx_end].strip()

        if len(context) >= 16:
            return context

    # Fallback: character window
    ctx_start = max(0, match_start - 200)
    ctx_end = min(len(source_text), match_end + 300)
    return source_text[ctx_start:ctx_end].strip()


# ── Main test ───────────────────────────────────────────────────────────────

def extract_verbatim_with_context(
    predicted_answer: str,
    chunk_text: str,
) -> dict:
    """
    Full extraction pipeline: match predicted answer to source chunk,
    return verbatim span + evidence context (2-3 sentences).
    
    Args:
        predicted_answer: The LLM's predicted answer (e.g. "0.80")
        chunk_text: The top-ranked chunk content used for generation
        
    Returns:
        Dict with match details and surrounding context
    """
    result = {
        "predicted_answer": predicted_answer,
        "verbatim_match": {"found": False, "method": None, "span_text": None,
                           "start_offset": None, "end_offset": None},
        "evidence_context": "",
        "normalized_value": predicted_answer,
    }

    cleaned_pred = _clean_text(predicted_answer)
    value_to_match = _extract_final_value_candidate(cleaned_pred) or cleaned_pred
    result["value_to_match"] = value_to_match

    # Try matching strategies in order
    span = _find_text_span(chunk_text, value_to_match)
    if span is None and cleaned_pred and cleaned_pred != value_to_match:
        span = _find_text_span(chunk_text, cleaned_pred)
    if span is None:
        span = _find_entity_aligned_span(chunk_text, value_to_match)

    if span:
        start_offset, end_offset, match_method = span
        span_text = chunk_text[start_offset:end_offset]
        result["verbatim_match"] = {
            "found": True,
            "method": match_method,
            "span_text": span_text,
            "start_offset": start_offset,
            "end_offset": end_offset,
        }
        result["normalized_value"] = span_text

        # Extract 2-3 sentences of context around the match
        context = extract_evidence_context(chunk_text, start_offset, end_offset)
        result["evidence_context"] = context
        result["context_length"] = len(context)
        result["num_sentences"] = len(re.findall(r'[.!?]+\s*', context))

    return result


def test_q01_with_full_chunk():
    """Test with a simulated full chunk that has proper surrounding context.
    
    The actual source document for BNY Mellon Equity Income Fund contains
    a fee table where the total annual fund operating expenses are listed.
    """
    print("═" * 70)
    print("  Test 1: Q01 · L1-003 · BNY Mellon Equity Income Fund (Class I)")
    print("  Using a simulated chunk with full context")
    print("═" * 70)

    # Simulated top-ranked chunk containing the fee table
    simulated_chunk = (
        "Annual Fund Operating Expenses (expenses that you pay each year as "
        "a percentage of the value of your investment): Management fees 0.65%, "
        "Distribution and/or Service (12b-1) fees 0.00%, Other expenses 0.15%, "
        "Total annual fund operating expenses 0.80%. The total annual fund "
        "operating expenses do not correlate to the ratio of expenses to "
        "average net assets given in the Financial Highlights, which reflects "
        "the operating expense ratio excluding the impact of expense offset "
        "arrangements."
    )

    predicted_answer = "0.80"
    gold_answer = "0.8"
    result = extract_verbatim_with_context(predicted_answer, simulated_chunk)

    print(f"\n  Predicted answer: {predicted_answer}")
    print(f"  Gold answer:      {gold_answer}")
    print(f"\n  Value to match:   {result['value_to_match']}")
    print(f"  Match method:     {result['verbatim_match']['method']}")
    print(f"  Verbatim span:    {repr(result['verbatim_match']['span_text'])}")
    print(f"  Offset:           [{result['verbatim_match']['start_offset']}, "
          f"{result['verbatim_match']['end_offset']})")
    print(f"\n── Evidence Context ({result['context_length']} chars, "
          f"{result['num_sentences']} sentences) ──")
    print(f"  {result['evidence_context']}")

    # Verify: gold answer matches predicted
    gold_num = float(re.sub(r"[^0-9.]", "", gold_answer))
    pred_num = float(re.sub(r"[^0-9.]", "", result['value_to_match']))
    print(f"\n── Verification ──")
    print(f"  Numeric match: {pred_num} vs {gold_num} = "
          f"{'✓' if abs(pred_num - gold_num) <= 0.001 else '✗'}")
    print(f"  Verbatim found in chunk: {'✓' if result['verbatim_match']['found'] else '✗'}")
    print(f"  Context has meaningful content: "
          f"{'✓' if result['context_length'] > 16 else '✗'}")

    return result


def test_q01_with_actual_evidence():
    """Test with the actual evidence snippet from the QA file.
    
    The evidence text is only ".80" (verbatim span) without surrounding
    context. This demonstrates why we need the FULL chunk text passed
    as evidence, not just the verbatim span.
    """
    print("\n" + "═" * 70)
    print("  Test 2: Q01 with actual evidence snippet from QA file")
    print("  Shows limited context when only verbatim span is available")
    print("═" * 70)

    qa_file = Path(__file__).parent / "df_santic_qa.json"
    if not qa_file.exists():
        print(f"\nERROR: {qa_file} not found")
        return None

    with open(qa_file) as f:
        data = json.load(f)
    qa = data["qa_pairs"][0]
    evidence = qa.get("evidence", {})
    evidence_text = evidence.get("text", "")

    predicted_answer = "0.80"
    result = extract_verbatim_with_context(predicted_answer, evidence_text)

    print(f"\n  Evidence text (from QA file): {repr(evidence_text)} ({len(evidence_text)} chars)")
    print(f"  Predicted answer: {predicted_answer}")
    print(f"  Match method:     {result['verbatim_match']['method']}")
    print(f"  Verbatim span:    {repr(result['verbatim_match']['span_text'])}")
    print(f"\n── Evidence Context ({result['context_length']} chars) ──")
    if result['context_length'] > 5:
        print(f"  {result['evidence_context']}")
    else:
        print("  (too short to extract meaningful context - need full chunk)")
    print(f"\n  ⚠  The QA file only stores the verbatim span, not the full chunk.")
    print(f"     To get proper context, pass the FULL chunk content as evidence_text.")
    
    return result


def test_mixed_examples():
    """Test with various answer types to show robustness."""
    print("\n" + "═" * 70)
    print("  Test 3: Various answer types (date, text, boolean)")
    print("═" * 70)

    test_cases = [
        # (predicted, chunk_snippet, expected_type)
        ("January 15, 2025", 
         "Shareholders approved the merger effective January 15, 2025, as announced "
         "in the previous quarter. All conditions were met by that date.",
         "date"),
        ("BNY Mellon Investment Adviser, Inc.",
         "The fund's investment adviser is BNY Mellon Investment Adviser, Inc., "
         "a wholly-owned subsidiary of The Bank of New York Mellon Corporation. "
         "The adviser is responsible for the day-to-day operations of the fund.",
         "text"),
        ("Yes",
         "Electronic delivery eligibility: Yes. Shareholders may elect to receive "
         "shareholder communications electronically. To enroll, visit the website.",
         "boolean"),
    ]

    for pred, chunk, etype in test_cases:
        result = extract_verbatim_with_context(pred, chunk)
        print(f"\n  Type: {etype}")
        print(f"  Predicted: {repr(pred)}")
        print(f"  Matched:   {result['verbatim_match']['found']} ({result['verbatim_match']['method']})")
        print(f"  Span:      {repr(result['verbatim_match']['span_text'])}")
        ctx = result['evidence_context']
        print(f"  Context:   {ctx[:80]}{'...' if len(ctx) > 80 else ''}")


if __name__ == "__main__":
    r1 = test_q01_with_full_chunk()
    r2 = test_q01_with_actual_evidence()
    test_mixed_examples()
