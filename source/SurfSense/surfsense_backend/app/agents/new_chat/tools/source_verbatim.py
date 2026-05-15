import re
from typing import Any

from langchain_core.tools import tool


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

    bool_matches = list(
        re.finditer(r"\b(?:yes|no|true|false|n/?a)\b", cleaned, flags=re.IGNORECASE)
    )
    if bool_matches:
        return bool_matches[-1].group(0)

    value_matches = list(
        re.finditer(
            r"[$\u20ac\u00a3\u00a5]?[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?"
            r"(?:\s*(?:billion|million|thousand|percent|%|bps|basis points|usd|dollars?))?"
            r"|[$\u20ac\u00a3\u00a5]?[-+]?\d+(?:\.\d+)?"
            r"(?:\s*(?:billion|million|thousand|percent|%|bps|basis points|usd|dollars?))?",
            cleaned,
            flags=re.IGNORECASE,
        )
    )
    if value_matches:
        return value_matches[-1].group(0).strip(" .,:;")

    chunks = [chunk.strip() for chunk in re.split(r"[\n\r]+", cleaned) if chunk.strip()]
    if chunks:
        tail = chunks[-1].strip(" .,:;")
        if len(tail) <= 120:
            return tail
    return cleaned


def _find_text_span(haystack: str, needle: str) -> tuple[int, int, str] | None:
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
    return None


def _scale_factor(window: str) -> float:
    w = window.lower()
    if "billion" in w or re.search(r"(?<=\d)b\b", w):
        return 1_000_000_000.0
    if "million" in w or re.search(r"(?<=\d)m\b", w):
        return 1_000_000.0
    if "thousand" in w or re.search(r"(?<=\d)k\b", w):
        return 1_000.0
    return 1.0


def _unit_type(window: str) -> str:
    w = window.lower()
    if any(k in w for k in ["%", "percent", "percentage"]):
        return "percent"
    if any(k in w for k in ["bps", "basis points"]):
        return "bps"
    if "$" in w or "usd" in w or "dollar" in w:
        return "currency"
    return "count"


def _extract_numeric_entities(value: str) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
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
        utype = _unit_type(window)
        scale = _scale_factor(window) if utype in {"currency", "count"} else 1.0
        entities.append(
            {
                "raw": raw,
                "start": match.start(),
                "end": match.end(),
                "type": utype,
                "normalized": base * scale,
            }
        )
    return entities


def _entity_match(gold: dict[str, Any], pred: dict[str, Any], tolerance: float = 0.01) -> bool:
    if gold["type"] != pred["type"]:
        return False
    gv = float(gold["normalized"])
    pv = float(pred["normalized"])
    allowed = max(1e-9, abs(gv) * tolerance)
    return abs(gv - pv) <= allowed


def _find_entity_aligned_span(haystack: str, candidate: str) -> tuple[int, int, str] | None:
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
                suffix,
                flags=re.IGNORECASE,
            )
            if unit_match:
                end += unit_match.end()
            return start, end, "numeric_entity"
    return None


def create_source_verbatim_tool():
    @tool
    async def source_verbatim(
        predicted_answer: str,
        evidence_text: str,
        strict_exact: bool = True,
    ) -> dict[str, Any]:
        """
        Align a predicted value to an exact source-text span and return offsets.

        Use this tool when you need a final answer that must match source text verbatim.

        Args:
            predicted_answer: The model-generated candidate answer.
            evidence_text: Source text to align against.
            strict_exact: When true, only exact source span text is considered verbatim.

        Returns:
            Dict containing normalized value, span text, start/end offsets, and match flags.
        """
        cleaned_pred = _clean_text(predicted_answer)
        final_candidate = _extract_final_value_candidate(cleaned_pred)
        value_to_match = final_candidate or cleaned_pred
        source = evidence_text or ""

        span = _find_text_span(source, value_to_match)
        if span is None and cleaned_pred and cleaned_pred != value_to_match:
            span = _find_text_span(source, cleaned_pred)
        if span is None:
            span = _find_entity_aligned_span(source, value_to_match)

        start_offset: int | None = None
        end_offset: int | None = None
        span_text: str | None = None
        match_method: str | None = None
        source_span_match = False
        source_verbatim_match = False


        # Extract evidence context: full sentence or chunk containing the match
        evidence_context = None
        if span is not None and start_offset is not None and end_offset is not None:
            # Try to extract the full sentence containing the match
            import re
            # Find sentence boundaries (simple heuristic: ., !, ? followed by space or end)
            before = source[:start_offset]
            after = source[end_offset:]
            sent_start = max(before.rfind('.'), before.rfind('!'), before.rfind('?')) + 1
            sent_end_rel = min([i for i in [after.find('.'), after.find('!'), after.find('?')] if i != -1] + [len(after)])
            sent_end = end_offset + sent_end_rel if sent_end_rel != -1 else len(source)
            context = source[sent_start:sent_end].strip()
            # If sentence is too short or boundaries not found, fallback to full chunk
            if len(context) < 16:
                # Use up to 120 chars before/after as fallback
                context = source[max(0, start_offset-120):min(len(source), end_offset+120)].strip()
            evidence_context = context

        normalized_value = span_text if source_verbatim_match and span_text is not None else value_to_match

        return {
            "normalized_value": normalized_value,
            "candidate_value": value_to_match,
            "source_span_match": source_span_match,
            "source_verbatim_match": source_verbatim_match,
            "match_method": match_method,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "span_text": span_text,
            "offset_convention": {
                "reference": "evidence_text",
                "library": "python3-str",
                "unit": "unicode_codepoint",
                "index_base": 0,
                "range": "[start_offset, end_offset)",
            },
            "evidence_context": evidence_context,
        }

    return source_verbatim
