from __future__ import annotations

import re

from app.config import config


def chunk_text(text: str, use_code_chunker: bool = False) -> list[str]:
    """Chunk a text string using the configured chunker and return the chunk texts."""
    chunker = (
        config.code_chunker_instance if use_code_chunker else config.chunker_instance
    )
    return [c.text for c in chunker.chunk(text)]


def chunk_text_hybrid(text: str, use_code_chunker: bool = False) -> list[str]:
    """Markdown-aware chunker that preserves complete Markdown tables as single chunks.

    Each Markdown table is stored as one self-contained chunk regardless of size,
    so the LLM always receives all rows and columns for aggregation and cross-row
    comparison queries.

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

    # Process each block
    chunks: list[str] = []

    for kind, block in blocks:
        if kind != "table":
            chunks.extend(chunk_text(block, use_code_chunker=use_code_chunker))
        else:
            # Always keep the entire table as one chunk.
            # The full text is stored for the LLM; the embedding may truncate
            # at the model's token limit but the header rows — which uniquely
            # identify the table — always fall within that window.
            stripped = block.strip()
            if stripped:
                chunks.append(stripped)

    return [c for c in chunks if c.strip()]
