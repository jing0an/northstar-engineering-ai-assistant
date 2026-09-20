"""Structured previews for document formats supported by the preview API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.document_parsers.parsers import DocxParser


class DocumentPreviewError(RuntimeError):
    """Raised when a document cannot be converted into a preview."""


def _text(value: object) -> str:
    return value if isinstance(value, str) else str(value)


def build_docx_preview(
    file_path: str | Path,
    *,
    file_id: str,
    project_id: str,
    document_version: int | None,
    original_filename: str,
) -> dict[str, Any]:
    """Convert the existing DOCX parser output into a small stable JSON shape."""
    try:
        pages = DocxParser().parse(file_path, "docx")
    except Exception as error:
        raise DocumentPreviewError("DOCX 文档预览解析失败") from error

    if not pages or not isinstance(pages[0], dict):
        raise DocumentPreviewError("DOCX 文档没有可预览内容")

    raw_blocks = pages[0].get("blocks", [])
    if not isinstance(raw_blocks, list):
        raise DocumentPreviewError("DOCX 预览结构无效")

    blocks: list[dict[str, Any]] = []
    pending_list: list[str] = []

    def flush_list() -> None:
        nonlocal pending_list
        if pending_list:
            blocks.append({"type": "list", "items": pending_list})
            pending_list = []

    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        block_type = raw.get("type")
        if block_type == "list_item":
            pending_list.append(_text(raw.get("text", "")))
            continue

        flush_list()
        if block_type == "heading":
            level = raw.get("level")
            blocks.append({
                "type": "heading",
                "level": level if isinstance(level, int) and level > 0 else 1,
                "text": _text(raw.get("text", "")),
            })
        elif block_type == "paragraph":
            blocks.append({"type": "paragraph", "text": _text(raw.get("text", ""))})
        elif block_type == "table":
            rows = raw.get("rows", [])
            normalized_rows = [
                [_text(cell) for cell in row]
                for row in rows
                if isinstance(row, list)
            ] if isinstance(rows, list) else []
            blocks.append({"type": "table", "rows": normalized_rows})
        elif block_type == "image":
            blocks.append({
                "type": "image",
                "count": raw.get("count", 0),
                "available": False,
            })

    flush_list()
    return {
        "file_id": file_id,
        "project_id": project_id,
        "document_version": document_version,
        "file_type": "docx",
        "original_filename": original_filename,
        "blocks": blocks,
    }
