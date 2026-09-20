import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reportlab.pdfgen import canvas

from app.services.document_parser import extract_pages
from app.services.document_parsers.pdf_enhanced import (
    assess_page_quality,
    extract_pages_enhanced,
    sort_text_spans,
)

TARGET_PDF = (
        Path(__file__).resolve().parents[1]
        / "storage"
        / "BJ-KC-2024-01"
        / "125ddc347dea4ff7b4ed5ecabebc2fd4.pdf"
)


def make_pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, text)
    pdf.save()
    return buffer.getvalue()


class EnhancedPdfParserTest(unittest.TestCase):
    def test_normal_page_keeps_pypdf_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "normal.pdf"
            source = "This is a normal PDF page with enough text to avoid quality fallback. " * 6
            path.write_bytes(make_pdf(source))
            baseline = extract_pages(path, "pdf")
            result = extract_pages_enhanced(path, extract_pages)
            self.assertEqual(result, baseline)

    def test_quality_detector_flags_replacement_and_complex_layout(self) -> None:
        quality = assess_page_quality("abc\ufffd\x02", span_count=12, drawing_count=10)
        self.assertTrue(quality.needs_enhancement)
        self.assertEqual(quality.replacement_count, 1)
        self.assertEqual(quality.control_count, 1)
        self.assertTrue(quality.layout_complex)

    def test_coordinates_are_sorted_by_row_then_column(self) -> None:
        spans = [
            {"text": "B", "bbox": (100, 20, 110, 30)},
            {"text": "A", "bbox": (20, 20, 30, 30)},
            {"text": "C", "bbox": (20, 5, 30, 15)},
        ]
        ordered = sort_text_spans(spans)
        self.assertEqual([item["text"] for item in ordered], ["C", "A", "B"])

    def test_image_metadata_does_not_create_table_text(self) -> None:
        quality = assess_page_quality("valid text", image_count=1)
        self.assertFalse(quality.needs_enhancement)

    def test_pymupdf_failure_falls_back_to_pypdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fallback.pdf"
            path.write_bytes(make_pdf("short"))
            baseline = extract_pages(path, "pdf")
            with patch(
                    "app.services.document_parsers.pdf_enhanced._extract_page_layout",
                    side_effect=RuntimeError("probe failure"),
            ):
                result = extract_pages_enhanced(path, extract_pages)
            self.assertEqual(result, baseline)

    def test_real_target_page_ten_uses_enhanced_layout_metadata(self) -> None:
        self.assertTrue(TARGET_PDF.is_file())
        pages = extract_pages_enhanced(TARGET_PDF, extract_pages)
        page = pages[9]
        metadata = page.get("metadata", {})
        self.assertEqual(page["page_number"], 10)
        self.assertEqual(metadata.get("parser_method"), "pymupdf_enhanced")
        self.assertGreater(metadata.get("span_count", 0), 0)
        self.assertGreaterEqual(metadata.get("image_count", 0), 1)
        self.assertGreater(len(page.get("blocks", [])), 0)
        self.assertIn("9-2-51", page["text"])
        self.assertNotIn("雷达图", page["text"])


if __name__ == "__main__":
    unittest.main()
