"""Provider-neutral OCR contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OCRBlock:
    text: str
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float | None = None
    blocks: tuple[OCRBlock, ...] = ()


class OCRProvider(ABC):
    """Minimal page-image OCR interface."""

    name: str = "unknown"

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether this provider can execute OCR in the current environment."""

    @abstractmethod
    def ocr_image(self, image: bytes, *, timeout_seconds: float = 30.0) -> OCRResult:
        """Recognize text from one rendered page image."""