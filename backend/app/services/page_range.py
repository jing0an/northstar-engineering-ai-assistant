"""Deterministic parsing and mapping of document page references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from app.services.document_resolver import chinese_number

_NUMBER = r"[0-9]+|[一二三四五六七八九十百千万零〇两]+"
_LAST_RE = re.compile(rf"最后\s*(?P<number>{_NUMBER})\s*页")
_RANGE_RE = re.compile(rf"第\s*(?P<start>{_NUMBER})\s*页?\s*(?:到|至|-|－|—|~|～)\s*第?\s*(?P<end>{_NUMBER})\s*页")
_PAIR_RE = re.compile(rf"第\s*(?P<first>{_NUMBER})\s*页?\s*(?:、|,|，|和)\s*第?\s*(?P<second>{_NUMBER})\s*页")
_SINGLE_RE = re.compile(rf"第\s*(?P<number>{_NUMBER})\s*页")
_PRINTED_PAGE_LINE_RE = re.compile(r"(?P<number>[1-9][0-9]*)")
_PRINTED_PAGE_SCAN_LINES = 3


@dataclass(frozen=True)
class DocumentPageMapping:
    """A reliable mapping between user-visible and physical PDF pages."""

    display_to_physical: dict[int, int]

    def __post_init__(self) -> None:
        if not self.display_to_physical:
            raise ValueError("display_to_physical must not be empty")
        displays = sorted(self.display_to_physical)
        if displays != list(range(1, displays[-1] + 1)):
            raise ValueError("display pages must be contiguous and start at 1")
        physical = list(self.display_to_physical.values())
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in displays + physical
        ) or len(set(physical)) != len(physical):
            raise ValueError("page mapping values must be unique positive integers")

    @property
    def max_display_page_number(self) -> int:
        return max(self.display_to_physical)

    def to_physical(self, display_pages: list[int]) -> list[int] | None:
        if any(page not in self.display_to_physical for page in display_pages):
            return None
        return [self.display_to_physical[page] for page in display_pages]

    def to_display(self, physical_page: int) -> int | None:
        for display_page, mapped_physical in self.display_to_physical.items():
            if mapped_physical == physical_page:
                return display_page
        return None


def _number(token: str) -> int | None:
    value = chinese_number(token)
    return value if value is not None and value > 0 else None


def has_page_range_reference(text: str) -> bool:
    """Return whether *text* contains a supported user-visible page reference."""
    return isinstance(text, str) and bool(
        _LAST_RE.search(text) or _RANGE_RE.search(text) or _PAIR_RE.search(text) or _SINGLE_RE.search(text)
    )


def resolve_page_numbers(text: str, max_page_number: int | None = None) -> list[int] | None:
    """Resolve a reference into user-visible display page numbers."""
    if not isinstance(text, str):
        return None
    match = _LAST_RE.search(text)
    if match:
        count = _number(match.group("number"))
        if count is None or max_page_number is None or max_page_number <= 0:
            return None
        return list(range(max(1, max_page_number - count + 1), max_page_number + 1))
    match = _RANGE_RE.search(text)
    if match:
        start, end = _number(match.group("start")), _number(match.group("end"))
        return list(range(min(start, end), max(start, end) + 1)) if start and end else None
    match = _PAIR_RE.search(text)
    if match:
        first, second = _number(match.group("first")), _number(match.group("second"))
        return sorted({first, second}) if first and second else None
    match = _SINGLE_RE.search(text)
    if match:
        page = _number(match.group("number"))
        return [page] if page else None
    return None


def mapping_from_metadata(metadata: Mapping[str, Any]) -> DocumentPageMapping | None:
    """Read an explicitly stored mapping without inferring a page offset."""
    raw_mapping = metadata.get("display_page_mapping")
    if not isinstance(raw_mapping, Mapping):
        return None
    try:
        mapping = {int(display): physical for display, physical in raw_mapping.items()}
        if any(not isinstance(physical, int) or isinstance(physical, bool) for physical in mapping.values()):
            return None
        return DocumentPageMapping(mapping)
    except (TypeError, ValueError):
        return None


def _printed_page_number(text: str) -> int | None:
    """Read one unambiguous page label from the first few non-empty lines."""
    candidates: list[int] = []
    non_empty_lines = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        non_empty_lines += 1
        if non_empty_lines > _PRINTED_PAGE_SCAN_LINES:
            break
        match = _PRINTED_PAGE_LINE_RE.fullmatch(line)
        if match is not None:
            candidates.append(int(match.group("number")))
    return candidates[0] if len(candidates) == 1 else None


def pdf_page_mapping(path: str | Path) -> DocumentPageMapping | None:
    """Build a mapping only when PDF text exposes a complete printed sequence.

    A cover without a printed number is allowed. No mapping is returned for a
    document whose printed page sequence cannot be verified safely.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pairs: list[tuple[int, int]] = []
        for physical_page, page in enumerate(reader.pages, start=1):
            printed_page = _printed_page_number(page.extract_text() or "")
            if printed_page is not None:
                pairs.append((printed_page, physical_page))
        labels = [display for display, _ in pairs]
        if not labels or labels != list(range(1, len(labels) + 1)):
            return None
        return DocumentPageMapping(dict(pairs))
    except Exception:
        return None


def parse_page_range(text: str, max_page_number: int | None = None) -> list[int] | None:
    """Public alias for :func:`resolve_page_numbers`."""
    return resolve_page_numbers(text, max_page_number)
