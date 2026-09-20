"""Deterministic text chunking for document-processing pipelines."""

from __future__ import annotations

import re

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120

_SPACE_RE = re.compile(r"[ \t]+")
_SENTENCE_END_RE = re.compile(r"[。！？!?；;.!?]$")


def _normalize_text(text: str) -> str:
    """Trim lines and collapse incidental horizontal whitespace."""
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _find_preferred_break(text: str, start: int, window_end: int, chunk_size: int) -> int:
    """Find a natural break near the end of the current window."""
    search_start = start + max(1, chunk_size // 2)
    candidates: list[int] = []
    for index in range(search_start, window_end):
        if text[index] == "\n" or _SENTENCE_END_RE.search(text[index]):
            candidates.append(index + 1)
    if candidates:
        return candidates[-1]

    # For text with spaces, avoid splitting an English word where possible.
    whitespace = max(text.rfind(" ", search_start, window_end), text.rfind("\t", search_start, window_end))
    if whitespace > start:
        return whitespace
    return window_end


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into ordered, non-empty, partially overlapping chunks.

    Text is normalized first, then split at paragraph/newline or sentence
    boundaries when available. A hard character boundary is used for a single
    oversized sentence or paragraph.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must not be negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = _normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        window_end = min(start + chunk_size, len(normalized))
        end = window_end
        if window_end < len(normalized):
            end = _find_preferred_break(normalized, start, window_end, chunk_size)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        # The guard guarantees forward progress even when a natural boundary
        # is immediately followed by the requested overlap.
        start = max(start + 1, end - chunk_overlap)

    return chunks
