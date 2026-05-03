from __future__ import annotations

import re

from app.config import config


def chunk_text(text: str, use_code_chunker: bool = False) -> list[str]:
    """Chunk a text string using the configured chunker and return the chunk texts."""
    chunker = (
        config.code_chunker_instance if use_code_chunker else config.chunker_instance
    )
    return [c.text for c in chunker.chunk(text)]


# Save reference before chunk_text is rebound to chunk_text_hybrid below.
_chunk_text_recursive = chunk_text


def chunk_text_hybrid(text: str, use_code_chunker: bool = False) -> list[str]:
    """Markdown-aware chunker that preserves complete Markdown tables as single chunks.

    Each Markdown table is stored as one self-contained chunk regardless of size,
    so the LLM always receives all rows and columns for aggregation and cross-row
    comparison queries.

    Context sandwich: the last non-empty line of the preceding prose block
    (typically a heading or a caption like "We repurchased the following shares…")
    is prepended to each table chunk, and the first non-empty line of the following
    prose block is appended.  Together these give the retrieval embedding both
    upstream and downstream context so tables are not orphaned from explanatory text
    (e.g. footnotes like "For the three months ended September 30, 2025 and 2024, we
    repurchased 8 million shares … for $4.0 billion and $2.8 billion").

    Embedding note: the embedding model (all-MiniLM-L6-v2) truncates input at 512
    tokens when computing vectors.  For large tables the embedding therefore
    represents the header + top rows — which is sufficient to locate the correct
    table via vector similarity, because financial table headers are unique
    identifiers.  BM25 full-text search operates on the complete stored text, so
    keyword hits anywhere in the table still work.

    Prose sections fall back to the standard RecursiveChunker via chunk_text().
    """
    TABLE_LINE = re.compile(r"^\s*\|")

    # Split document into alternating table / prose blocks
    blocks: list[tuple[str, str]] = []  # (kind, text)
    current_lines: list[str] = []
    in_table = False

    for line in text.splitlines(keepends=True):
        is_table_line = bool(TABLE_LINE.match(line))
        if is_table_line != in_table:
            if current_lines:
                blocks.append(("table" if in_table else "prose", "".join(current_lines)))
            current_lines = []
            in_table = is_table_line
        current_lines.append(line)

    if current_lines:
        blocks.append(("table" if in_table else "prose", "".join(current_lines)))

    # Process each block.
    # - last_prose_tail: last non-empty line of the preceding prose block → prepended to table.
    # - last_table_chunk_idx: index in `chunks` of the most recent table chunk, so that
    #   when the next prose block arrives we can append its first sentence as post-context.
    chunks: list[str] = []
    last_prose_tail: str = ""
    last_table_chunk_idx: int = -1

    for kind, block in blocks:
        if kind != "table":
            non_empty = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
            # Append first non-empty line of this prose block to the preceding table chunk
            # so the table has downstream context (e.g. footnote explaining the columns).
            if non_empty and last_table_chunk_idx >= 0:
                chunks[last_table_chunk_idx] += "\n" + non_empty[0]
            last_table_chunk_idx = -1
            if non_empty:
                last_prose_tail = non_empty[-1]
            # Empty blocks (blank lines between prose and table) do NOT reset
            # last_prose_tail — the preceding caption should still apply.
            chunks.extend(_chunk_text_recursive(block, use_code_chunker=use_code_chunker))
        else:
            stripped = block.strip()
            if not stripped:
                continue
            # Prepend the preceding prose tail (heading / caption) when present.
            if last_prose_tail:
                stripped = last_prose_tail + "\n" + stripped
                last_prose_tail = ""  # consume once per table
            chunks.append(stripped)
            last_table_chunk_idx = len(chunks) - 1

    return [c for c in chunks if c.strip()]


# chunk_text_hybrid is available but chunk_text remains the original recursive splitter.
