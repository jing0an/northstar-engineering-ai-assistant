"""OCR provider abstraction and optional local providers."""

from .base import OCRBlock, OCRProvider, OCRResult
from .exceptions import OCRExecutionError, OCRProviderError, OCRProviderUnavailableError, OCRTimeoutError
from .provider import PaddleOCRProvider, UnavailableOCRProvider

__all__ = [
    "OCRBlock",
    "OCRProvider",
    "OCRResult",
    "OCRProviderError",
    "OCRProviderUnavailableError",
    "OCRExecutionError",
    "OCRTimeoutError",
    "PaddleOCRProvider",
    "UnavailableOCRProvider",
]