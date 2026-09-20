"""Deterministic, offline embedding provider used by tests and local demos."""

from __future__ import annotations

import hashlib

from .models import DEFAULT_EMBEDDING_DIMENSION, DEFAULT_EMBEDDING_MODEL


class FakeEmbeddingProvider:
    """Generate stable pseudo-vectors without network access or API keys."""

    def __init__(
        self,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
            raise ValueError("dimension must be a positive integer")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        self.dimension = dimension
        self.model = model.strip()

    @staticmethod
    def _validate_text(text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized = text.strip()
        if not normalized:
            raise ValueError("text must not be empty or blank")
        return normalized

    def embed_text(self, text: str) -> list[float]:
        normalized = self._validate_text(text)
        # Domain-separate each coordinate so vectors are deterministic while
        # still changing when the input text changes.
        values: list[float] = []
        for index in range(self.dimension):
            digest = hashlib.sha256(f"{self.model}:{index}:{normalized}".encode("utf-8")).digest()
            integer = int.from_bytes(digest[:8], "big")
            values.append((integer / 2**64) * 2.0 - 1.0)
        return values

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list):
            raise TypeError("texts must be a list of strings")
        return [self.embed_text(text) for text in texts]
