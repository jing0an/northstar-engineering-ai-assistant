"""Local BGE-M3 embedding provider with lazy model loading."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

DEFAULT_BGE_M3_MODEL = "BAAI/bge-m3"


class BGEM3EmbeddingProvider:
    """Encode text with ``BAAI/bge-m3`` using sentence-transformers.

    Importing this module does not import or instantiate sentence-transformers.
    The model is loaded on the first call to :meth:`embed_text` or
    :meth:`embed_texts`, and sentence-transformers selects CPU when no device
    is supplied (or when ``device="cpu"`` is configured).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_BGE_M3_MODEL,
        *,
        device: str | None = None,
        normalize_embeddings: bool = True,
        model: Any | None = None,
    ) -> None:
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name must be a non-empty string")
        if not isinstance(normalize_embeddings, bool):
            raise TypeError("normalize_embeddings must be a boolean")
        self.model = model_name.strip()
        self.device = device
        self.normalize_embeddings = normalize_embeddings
        self._model: Any | None = model
        self.dimension: int | None = None
        if model is not None:
            self.dimension = self._read_model_dimension(model)

    @property
    def model_name(self) -> str:
        """Alias used by configuration code that distinguishes model names."""
        return self.model

    @staticmethod
    def _validate_text(text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized = text.strip()
        if not normalized:
            raise ValueError("text must not be empty or blank")
        return normalized

    @staticmethod
    def _read_model_dimension(model: Any) -> int | None:
        getter = getattr(model, "get_sentence_embedding_dimension", None)
        if not callable(getter):
            return None
        dimension = getter()
        if dimension is None:
            return None
        if not isinstance(dimension, int) or dimension <= 0:
            raise ValueError("model returned an invalid embedding dimension")
        return dimension

    def _load_model(self) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "sentence-transformers is required for BGEM3EmbeddingProvider"
            ) from error

        kwargs: dict[str, Any] = {}
        if self.device is not None:
            kwargs["device"] = self.device
        return SentenceTransformer(self.model, **kwargs)

    def _ensure_model(self) -> Any:
        if self._model is None:
            self._model = self._load_model()
            self.dimension = self._read_model_dimension(self._model)
        return self._model

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list):
            raise TypeError("texts must be a list of strings")
        normalized_texts = [self._validate_text(text) for text in texts]
        if not normalized_texts:
            return []

        model = self._ensure_model()
        encoded = model.encode(
            normalized_texts,
            convert_to_numpy=True,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )
        raw_vectors = encoded.tolist() if hasattr(encoded, "tolist") else encoded
        if not isinstance(raw_vectors, Sequence) or isinstance(raw_vectors, (str, bytes)):
            raise ValueError("embedding model returned an invalid result")
        if raw_vectors and isinstance(raw_vectors[0], (int, float)):
            raw_vectors = [raw_vectors]
        vectors = [[float(value) for value in vector] for vector in raw_vectors]
        if len(vectors) != len(normalized_texts) or not vectors or not all(vectors):
            raise ValueError("embedding model returned an invalid batch size")

        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise ValueError("embedding model returned inconsistent dimensions")
        if self.dimension is not None and self.dimension != dimension:
            raise ValueError("embedding model output dimension changed")
        self.dimension = dimension
        return vectors


# Keep both spellings convenient for callers while retaining one implementation.
BGE_M3EmbeddingProvider = BGEM3EmbeddingProvider
