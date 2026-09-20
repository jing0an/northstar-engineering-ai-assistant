"""Provider-neutral embedding contract."""

from typing import Protocol


class EmbeddingProvider(Protocol):
    """Interface implemented by fake and future remote embedding providers."""

    model: str
    dimension: int

    def embed_text(self, text: str) -> list[float]:
        """Return one fixed-dimension vector for a non-empty text."""
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return vectors in the same order as the input texts."""
        ...
