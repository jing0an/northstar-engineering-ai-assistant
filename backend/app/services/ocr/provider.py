"""Optional local OCR providers with safe unavailable behavior."""

from __future__ import annotations

from .base import OCRProvider, OCRResult
from .exceptions import OCRExecutionError, OCRProviderUnavailableError, OCRTimeoutError


class UnavailableOCRProvider(OCRProvider):
    name = "unavailable"

    @property
    def available(self) -> bool:
        return False

    def ocr_image(self, image: bytes, *, timeout_seconds: float = 30.0) -> OCRResult:
        raise OCRProviderUnavailableError("当前环境未安装可用的本地 OCR 组件")


class PaddleOCRProvider(OCRProvider):
    """Lazy PaddleOCR adapter; importing it never changes project dependencies."""

    name = "paddleocr"

    def __init__(self) -> None:
        self._engine = None
        try:
            from paddleocr import PaddleOCR
        except Exception:
            return
        try:
            self._engine = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
        except Exception:
            self._engine = None

    @property
    def available(self) -> bool:
        return self._engine is not None

    def ocr_image(self, image: bytes, *, timeout_seconds: float = 30.0) -> OCRResult:
        if not self.available:
            raise OCRProviderUnavailableError("PaddleOCR 当前不可用")
        try:
            result = self._engine.predict(image)
            texts: list[str] = []
            confidences: list[float] = []
            for item in result:
                data = getattr(item, "json", None)
                payload = data() if callable(data) else data
                if isinstance(payload, dict):
                    res = payload.get("res", payload)
                    rec_texts = res.get("rec_texts", []) if isinstance(res, dict) else []
                    rec_scores = res.get("rec_scores", []) if isinstance(res, dict) else []
                    texts.extend(str(value) for value in rec_texts)
                    confidences.extend(float(value) for value in rec_scores if isinstance(value, (int, float)))
            confidence = sum(confidences) / len(confidences) if confidences else None
            return OCRResult(text="\n".join(texts), confidence=confidence)
        except Exception as error:
            raise OCRExecutionError("PaddleOCR 执行失败") from error