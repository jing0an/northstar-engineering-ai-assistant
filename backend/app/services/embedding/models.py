"""Shared embedding configuration and result models."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_EMBEDDING_MODEL = "fake-deterministic-v1"
DEFAULT_EMBEDDING_DIMENSION = 32


class EmbeddingRecord(BaseModel):
    """An embedding together with the source text and provider metadata."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    embedding: list[float] = Field(min_length=1)
    model: str = Field(min_length=1)
    dimension: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_consistency(self) -> "EmbeddingRecord":
        if not self.text.strip():
            raise ValueError("text must not be blank")
        if len(self.embedding) != self.dimension:
            raise ValueError("embedding length must match dimension")
        return self
