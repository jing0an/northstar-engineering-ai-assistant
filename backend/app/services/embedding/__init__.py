"""Provider-neutral embedding interfaces and deterministic test provider."""

from .base import EmbeddingProvider
from .bge_m3 import (
    BGE_M3EmbeddingProvider,
    BGEM3EmbeddingProvider,
    DEFAULT_BGE_M3_MODEL,
)
from .fake import FakeEmbeddingProvider
from .models import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingRecord,
)

__all__ = [
    "EmbeddingProvider",
    "BGEM3EmbeddingProvider",
    "BGE_M3EmbeddingProvider",
    "DEFAULT_BGE_M3_MODEL",
    "FakeEmbeddingProvider",
    "EmbeddingRecord",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL",
]
