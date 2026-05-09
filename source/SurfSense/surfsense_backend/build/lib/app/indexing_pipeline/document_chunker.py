from __future__ import annotations

import functools
import re

from chonkie import CodeChunker, RecursiveChunker

from app.config import config


@functools.lru_cache(maxsize=16)
def _build_chunker(use_code_chunker: bool, chunk_size: int):
    if use_code_chunker:
        return CodeChunker(chunk_size=chunk_size)
    return RecursiveChunker(chunk_size=chunk_size)


def chunk_text(
    text: str,
    use_code_chunker: bool = False,
    chunk_size: int | None = None,
) -> list[str]:
    """Chunk a text string using the configured chunker and return the chunk texts."""
    if chunk_size is not None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer")
        chunker = _build_chunker(use_code_chunker, int(chunk_size))
    else:
        chunker = (
            config.code_chunker_instance if use_code_chunker else config.chunker_instance
        )
    return [c.text for c in chunker.chunk(text)]


def chunk_recursive(
    text: str,
    use_code_chunker: bool = False,
    chunk_size: int | None = None,
) -> list[str]:
    """Explicit recursive chunking alias (same behavior as chunk_text)."""
    return chunk_text(
        text,
        use_code_chunker=use_code_chunker,
        chunk_size=chunk_size,
    )


def chunk_text_hybrid(
    text: str,
    use_code_chunker: bool = False,
    chunk_size: int | None = None,
) -> list[str]:
    """Markdown-aware hybrid chunker preserving tables as complete chunks with context."""
    table_line = re.compile(r"^\s*\|")

    blocks: list[tuple[str, str]] = []
    current_lines: list[str] = []
    in_table = False

    for line in text.splitlines(keepends=True):
        is_table_line = bool(table_line.match(line))
        if is_table_line != in_table:
            if current_lines:
                blocks.append(("table" if in_table else "prose", "".join(current_lines)))
            current_lines = []
            in_table = is_table_line
        current_lines.append(line)

    if current_lines:
        blocks.append(("table" if in_table else "prose", "".join(current_lines)))

    chunks: list[str] = []
    last_prose_tail = ""
    last_table_chunk_idx = -1

    for kind, block in blocks:
        if kind != "table":
            non_empty = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
            if non_empty and last_table_chunk_idx >= 0:
                chunks[last_table_chunk_idx] += "\n" + non_empty[0]
            last_table_chunk_idx = -1
            if non_empty:
                last_prose_tail = non_empty[-1]
            chunks.extend(
                chunk_recursive(
                    block,
                    use_code_chunker=use_code_chunker,
                    chunk_size=chunk_size,
                )
            )
            continue

        stripped = block.strip()
        if not stripped:
            continue
        if last_prose_tail:
            stripped = last_prose_tail + "\n" + stripped
            last_prose_tail = ""
        chunks.append(stripped)
        last_table_chunk_idx = len(chunks) - 1

    return [c for c in chunks if c.strip()]


def chunk_hybrid(
    text: str,
    use_code_chunker: bool = False,
    chunk_size: int | None = None,
) -> list[str]:
    """Alias for hybrid chunking strategy."""
    return chunk_text_hybrid(
        text,
        use_code_chunker=use_code_chunker,
        chunk_size=chunk_size,
    )


def sandwich_chunk(
    text: str,
    use_code_chunker: bool = False,
    chunk_size: int | None = None,
) -> list[str]:
    """Context-sandwich strategy alias; implemented via hybrid chunking."""
    return chunk_text_hybrid(
        text,
        use_code_chunker=use_code_chunker,
        chunk_size=chunk_size,
    )


def chunk_with_strategy(
    text: str,
    strategy: str | None = None,
    use_code_chunker: bool = False,
    chunk_size: int | None = None,
) -> list[str]:
    normalized = (strategy or "chunk_text").strip().lower()
    if normalized in {"sandwitch_chunk", "sandwich_chunk"}:
        return sandwich_chunk(
            text,
            use_code_chunker=use_code_chunker,
            chunk_size=chunk_size,
        )
    if normalized == "chunk_hybrid":
        return chunk_hybrid(
            text,
            use_code_chunker=use_code_chunker,
            chunk_size=chunk_size,
        )
    if normalized == "chunk_recursive":
        return chunk_recursive(
            text,
            use_code_chunker=use_code_chunker,
            chunk_size=chunk_size,
        )
    return chunk_text(
        text,
        use_code_chunker=use_code_chunker,
        chunk_size=chunk_size,
    )
