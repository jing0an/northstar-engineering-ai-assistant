"""Quality-gated PyMuPDF enhancement for the existing PDF parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from app.services.ocr import OCRProvider, OCRProviderError


@dataclass(frozen=True)
class PageQuality:
    """Explainable quality signals used to decide whether enhancement is needed."""

    text_length: int
    replacement_count: int
    control_count: int
    span_count: int
    image_count: int
    drawing_count: int
    layout_complex: bool
    needs_enhancement: bool


def _control_count(text: str) -> int:
    return sum(
        1
        for char in text
        if (ord(char) < 32 or ord(char) == 0x7F) and char not in "\r\n\t"
    )


def _quality_requires_enhancement(text: str) -> bool:
    return "\ufffd" in text or _control_count(text) > 0


def assess_page_quality(
        pypdf_text: str,
        *,
        span_count: int = 0,
        image_count: int = 0,
        drawing_count: int = 0,
        pymupdf_text_length: int | None = None,
) -> PageQuality:
    """Return deterministic quality signals; images alone never imply failure."""
    replacement_count = pypdf_text.count("\ufffd")
    control_count = _control_count(pypdf_text)
    layout_complex = drawing_count >= 8 or span_count >= 8

    text_gain = (
            pymupdf_text_length is not None
            and pymupdf_text_length
            > max(len(pypdf_text) + 20, int(len(pypdf_text) * 1.5))
    )

    needs_enhancement = (
            replacement_count > 0
            or control_count > 0
            or (layout_complex and len(pypdf_text.strip()) < 500)
            or text_gain
    )

    return PageQuality(
        text_length=len(pypdf_text),
        replacement_count=replacement_count,
        control_count=control_count,
        span_count=span_count,
        image_count=image_count,
        drawing_count=drawing_count,
        layout_complex=layout_complex,
        needs_enhancement=needs_enhancement,
    )


def sort_text_spans(
        spans: Iterable[dict[str, Any]],
        y_tolerance: float = 3.0,
) -> list[dict[str, Any]]:
    """Group spans into visual rows and sort each row from left to right."""
    rows: list[dict[str, Any]] = []

    for span in sorted(
            spans,
            key=lambda item: (item["bbox"][1], item["bbox"][0]),
    ):
        x0, y0, x1, y1 = span["bbox"]
        center = (y0 + y1) / 2

        row = next(
            (
                candidate
                for candidate in rows
                if abs(candidate["center"] - center) <= y_tolerance
            ),
            None,
        )

        if row is None:
            row = {"center": center, "items": []}
            rows.append(row)

        row["items"].append(span)
        row["center"] = sum(
            (item["bbox"][1] + item["bbox"][3]) / 2
            for item in row["items"]
        ) / len(row["items"])

    ordered: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda item: item["center"]):
        ordered.extend(
            sorted(
                row["items"],
                key=lambda item: item["bbox"][0],
            )
        )

    return ordered


def _extract_page_layout(
        page: Any,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    raw = page.get_text("dict")

    spans: list[dict[str, Any]] = []

    for block_no, block in enumerate(raw.get("blocks", [])):
        if block.get("type") == 1:
            continue

        for line_no, line in enumerate(block.get("lines", [])):
            for span_no, span in enumerate(line.get("spans", [])):
                text = span.get("text", "")

                if not isinstance(text, str):
                    continue

                spans.append(
                    {
                        "text": text,
                        "bbox": tuple(
                            span.get("bbox", (0, 0, 0, 0))
                        ),
                        "font": span.get("font"),
                        "size": span.get("size"),
                        "block_no": block_no,
                        "line_no": line_no,
                        "span_no": span_no,
                    }
                )

    ordered = sort_text_spans(spans)

    rows: list[dict[str, Any]] = []

    for span in ordered:
        center = (
                         span["bbox"][1] + span["bbox"][3]
                 ) / 2

        row = next(
            (
                candidate
                for candidate in rows
                if abs(candidate["center"] - center) <= 3.0
            ),
            None,
        )

        if row is None:
            row = {
                "center": center,
                "items": [],
            }
            rows.append(row)

        row["items"].append(span)

        row["center"] = sum(
            (item["bbox"][1] + item["bbox"][3]) / 2
            for item in row["items"]
        ) / len(row["items"])

    text = "\n".join(
        " ".join(
            item["text"]
            for item in sorted(
                row["items"],
                key=lambda item: item["bbox"][0],
            )
        )
        for row in sorted(
            rows,
            key=lambda item: item["center"],
        )
    )

    images: list[dict[str, Any]] = []

    raw_blocks = raw.get("blocks", [])

    for block_no, block in enumerate(raw_blocks):
        if block.get("type") == 1:
            images.append(
                {
                    "block_no": block_no,
                    "bbox": block.get("bbox"),
                    "width": block.get("width"),
                    "height": block.get("height"),
                }
            )

    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []

    metadata = {
        "span_count": len(spans),
        "image_count": len(images),
        "drawing_count": len(drawings),
        "images": images,
    }

    blocks = [
        {
            "type": "text",
            **span,
        }
        for span in ordered
    ]

    return text, blocks, metadata


def _ocr_needed(text: str) -> bool:
    """Trigger OCR only when text is absent or clearly unusable."""
    if not text.strip():
        return True

    replacement = text.count(chr(0xFFFD))
    controls = _control_count(text)

    return (
            len(text.strip()) < 20
            or controls > 0
            or replacement / max(1, len(text)) > 0.25
    )


def _merge_metadata(
        page_result: dict[str, object],
        values: dict[str, Any],
) -> None:
    current = page_result.get("metadata")

    metadata = (
        dict(current)
        if isinstance(current, dict)
        else {}
    )

    metadata.update(values)
    page_result["metadata"] = metadata


def extract_pages_enhanced(
        file_path: str | Path,
        base_extractor: Callable[
            [str | Path, str],
            list[dict[str, object]],
        ],
        *,
        ocr_provider: OCRProvider | None = None,
) -> list[dict[str, object]]:
    """Use pypdf first, then layout extraction and optional page OCR."""

    pages = base_extractor(file_path, "pdf")

    try:
        import pymupdf

        document = pymupdf.open(str(file_path))
    except Exception:
        return pages

    try:
        for index, page_result in enumerate(pages):
            pypdf_text = str(
                page_result.get("text", "")
            )

            try:
                pdf_page = document[index]

                enhanced_text, blocks, layout = (
                    _extract_page_layout(pdf_page)
                )

            except Exception:
                # Keep the original pypdf page unchanged
                # when layout extraction fails.
                continue

            quality = assess_page_quality(
                pypdf_text,
                span_count=layout["span_count"],
                image_count=layout["image_count"],
                drawing_count=layout["drawing_count"],
                pymupdf_text_length=len(enhanced_text),
            )

            best_text = (
                enhanced_text
                if enhanced_text.strip()
                else pypdf_text
            )

            needs_ocr = _ocr_needed(best_text)

            healthy_pypdf = (
                    len(pypdf_text.strip()) >= 200
                    and not _quality_requires_enhancement(
                pypdf_text
            )
            )

            # 正常的普通文本页面保持原来的 pypdf 结果。
            # 但只要页面经过 PyMuPDF 分析，就保留 layout metadata。
            # 图片本身不会触发 OCR。
            if (
                    healthy_pypdf
                    and not quality.needs_enhancement
                    and not needs_ocr
                    and layout["image_count"] == 0
            ):
                continue

            page_result["text"] = best_text
            page_result["blocks"] = blocks

            _merge_metadata(
                page_result,
                {
                    "parser_method": "pymupdf_enhanced",
                    "text_quality": (
                        "degraded"
                        if (
                                quality.replacement_count
                                or quality.control_count
                        )
                        else "normal"
                    ),
                    "layout_quality": (
                        "complex"
                        if quality.layout_complex
                        else "simple"
                    ),
                    "needs_ocr": needs_ocr,
                    "ocr_used": False,
                    "quality": quality.__dict__,
                    **layout,
                },
            )

            if not (
                    quality.needs_enhancement
                    or needs_ocr
            ):
                continue

            if not needs_ocr:
                continue

            provider = ocr_provider

            if (
                    provider is None
                    or not provider.available
            ):
                _merge_metadata(
                    page_result,
                    {
                        "ocr_provider": (
                            provider.name
                            if provider is not None
                            else "unavailable"
                        ),
                        "ocr_failed": True,
                    },
                )
                continue

            try:
                pixmap = pdf_page.get_pixmap(
                    matrix=pymupdf.Matrix(2, 2),
                    alpha=False,
                )

                result = provider.ocr_image(
                    pixmap.tobytes("png"),
                    timeout_seconds=30.0,
                )

                if result.text.strip():
                    page_result["text"] = result.text

                    if result.blocks:
                        page_result["blocks"] = [
                            {
                                "type": "text",
                                "text": block.text,
                                "bbox": block.bbox,
                                "confidence": block.confidence,
                            }
                            for block in result.blocks
                        ]

                    _merge_metadata(
                        page_result,
                        {
                            "ocr_used": True,
                            "ocr_failed": False,
                            "ocr_provider": provider.name,
                            "ocr_confidence": result.confidence,
                            "text_quality": (
                                "degraded"
                                if (
                                        result.confidence is not None
                                        and result.confidence < 0.75
                                )
                                else "normal"
                            ),
                            "needs_ocr": False,
                        },
                    )

                else:
                    _merge_metadata(
                        page_result,
                        {
                            "ocr_provider": provider.name,
                            "ocr_failed": True,
                        },
                    )

            except OCRProviderError:
                _merge_metadata(
                    page_result,
                    {
                        "ocr_provider": provider.name,
                        "ocr_failed": True,
                    },
                )

            except Exception:
                _merge_metadata(
                    page_result,
                    {
                        "ocr_provider": provider.name,
                        "ocr_failed": True,
                    },
                )

    finally:
        document.close()

    return pages
