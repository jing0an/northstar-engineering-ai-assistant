import unittest
from app.services.ocr import OCRBlock, OCRResult, OCRProvider, OCRProviderUnavailableError, OCRTimeoutError, UnavailableOCRProvider
class FakeProvider(OCRProvider):
    name = "fake"
    @property
    def available(self): return True
    def ocr_image(self, image: bytes, *, timeout_seconds: float = 30.0): return OCRResult("中文", 0.91, (OCRBlock("中文", (1,2,3,4), 0.91),))
class OCRProviderTest(unittest.TestCase):
    def test_contract_and_result(self):
        result=FakeProvider().ocr_image(b"image", timeout_seconds=2.5); self.assertEqual(result.text,"中文"); self.assertEqual(result.confidence,0.91); self.assertEqual(result.blocks[0].bbox,(1,2,3,4))
    def test_timeout_error_is_provider_error(self):
        class TimeoutProvider(FakeProvider):
            def ocr_image(self, image: bytes, *, timeout_seconds: float = 30.0):
                raise OCRTimeoutError("timeout")
        with self.assertRaises(OCRTimeoutError):
            TimeoutProvider().ocr_image(b"image", timeout_seconds=0.1)

    def test_unavailable_provider_is_explicit(self):
        provider=UnavailableOCRProvider(); self.assertFalse(provider.available)
        with self.assertRaises(OCRProviderUnavailableError): provider.ocr_image(b"image")

