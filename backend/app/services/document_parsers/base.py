"""Common interfaces for document format parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar


def normalize_extension(value: str | Path) -> str:
    """Return a normalized, dotted extension or an empty string."""
    raw = str(value).strip()
    if not raw:
        return ""
    if raw.startswith(".") and raw.count(".") == 1:
        return raw.casefold()
    suffix = Path(raw).suffix
    return suffix.casefold() if suffix else ""


class DocumentParser(ABC):
    """Minimal parser contract used by the parser registry."""

    supported_extensions: ClassVar[frozenset[str]] = frozenset()
    implemented: ClassVar[bool] = True

    @abstractmethod
    def parse(
        self, file_path: str | Path, file_type: str | None = None
    ) -> list[dict[str, object]]:
        """Parse a document into logical page/content units."""