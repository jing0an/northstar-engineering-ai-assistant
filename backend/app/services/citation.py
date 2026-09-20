"""Deterministic, public-safe citations built from retrieval results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.services.document_resolver import DocumentCandidate
from app.services.page_range import DocumentPageMapping


class Citation(BaseModel):
    """A user-visible document source without internal identifiers."""

    original_filename: str = Field(min_length=1)
    document_version: int | None = Field(default=None, ge=1)
    page_number: int | None = Field(default=None, ge=1)
    chunk_index: int | None = Field(default=None, ge=0)


def _metadata(result: Any) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        value = result.get("metadata", {})
    else:
        value = getattr(result, "metadata", {})
    return value if isinstance(value, Mapping) else {}


def _field(result: Any, name: str, metadata: Mapping[str, Any]) -> Any:
    if isinstance(result, Mapping) and name in result:
        return result.get(name)
    if name in metadata:
        return metadata.get(name)
    return getattr(result, name, None)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def build_citations(
    results: Iterable[Any],
    expected_document: DocumentCandidate | None = None,
    page_mapping: DocumentPageMapping | None = None,
) -> list[Citation]:
    """Build deduplicated citations from actual retrieval results.

    When a resolver selected a document, project/file/version mismatches are
    discarded instead of producing a misleading public citation.
    """
    unique: dict[tuple[str, int | None, int | None], Citation] = {}
    for result in results:
        metadata = _metadata(result)
        project_id = _field(result, "project_id", metadata)
        file_id = _field(result, "file_id", metadata)
        if expected_document is not None:
            if project_id != expected_document.project_id or file_id != expected_document.file_id:
                continue

        filename = _field(result, "original_filename", metadata)
        if not isinstance(filename, str) or not filename.strip():
            continue
        filename = filename.strip()
        version = _positive_int(_field(result, "document_version", metadata))
        if expected_document is not None and version != expected_document.document_version:
            continue
        page_number = _positive_int(_field(result, "page_number", metadata))
        if page_number is not None and page_mapping is not None:
            page_number = page_mapping.to_display(page_number)
            if page_number is None:
                continue
        chunk_index = _non_negative_int(_field(result, "chunk_index", metadata))
        key = (filename, version, page_number)
        if key not in unique:
            unique[key] = Citation(
                original_filename=filename,
                document_version=version,
                page_number=page_number,
                chunk_index=chunk_index,
            )

    return sorted(
        unique.values(),
        key=lambda item: (
            item.original_filename,
            item.document_version if item.document_version is not None else 0,
            item.page_number if item.page_number is not None else 0,
        ),
    )

