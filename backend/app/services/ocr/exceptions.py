"""Controlled OCR errors exposed by the fallback layer."""


class OCRProviderError(RuntimeError):
    """Base error for OCR provider failures."""


class OCRProviderUnavailableError(OCRProviderError):
    """Raised when no local OCR engine is available."""


class OCRExecutionError(OCRProviderError):
    """Raised when an OCR engine fails to process an image."""


class OCRTimeoutError(OCRProviderError):
    """Raised when OCR exceeds its execution timeout."""