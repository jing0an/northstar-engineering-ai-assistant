import io, tempfile, unittest
from pathlib import Path
from reportlab.pdfgen import canvas
from app.services.document_parser import extract_pages
from app.services.document_parsers.pdf_enhanced import assess_page_quality, extract_pages_enhanced
from app.services.ocr import OCRExecutionError, OCRResult

TARGET_PDF = (
        Path(__file__).resolve().parents[1]
        / "storage"
        / "BJ-KC-2024-01"
        / "125ddc347dea4ff7b4ed5ecabebc2fd4.pdf"
)


def make_pdf(text):
    s = io.BytesIO();
    c = canvas.Canvas(s);
    c.drawString(72, 720, text);
    c.save();
    return s.getvalue()


class FakeProvider:
    name = "fake"

    def __init__(self, result=None, error=None): self.result = result; self.error = error; self.calls = 0

    @property
    def available(self): return True

    def ocr_image(self, image: bytes, *, timeout_seconds: float = 30.0):
        self.calls += 1
        if self.error: raise self.error
        return self.result


class PdfOcrFallbackTest(unittest.TestCase):
    def test_bad_text_uses_ocr(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scan.pdf";
            p.write_bytes(make_pdf("x"));
            provider = FakeProvider(OCRResult("OCR 文字", .92));
            r = extract_pages_enhanced(p, extract_pages, ocr_provider=provider);
            self.assertEqual(r[0]["page_number"], 1);
            self.assertEqual(r[0]["text"], "OCR 文字");
            self.assertTrue(r[0]["metadata"]["ocr_used"]);
            self.assertEqual(provider.calls, 1)

    def test_ocr_failure_keeps_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scan.pdf";
            p.write_bytes(make_pdf("x"));
            provider = FakeProvider(error=OCRExecutionError("failed"));
            r = extract_pages_enhanced(p, extract_pages, ocr_provider=provider);
            self.assertTrue(r[0]["metadata"]["ocr_failed"]);
            self.assertEqual(r[0]["page_number"], 1)

    def test_image_alone_does_not_trigger(self):
        quality = assess_page_quality("reliable text", image_count=1)
        self.assertFalse(quality.needs_enhancement)
        self.assertTrue(TARGET_PDF.is_file())
        pages = extract_pages_enhanced(TARGET_PDF, extract_pages)
        self.assertGreaterEqual(pages[9]["metadata"].get("image_count", 0), 1)
        self.assertNotIn("雷达图", pages[9]["text"])
