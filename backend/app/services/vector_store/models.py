"""Stable document and search result data structures."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VectorDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    chunk_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    file_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    embedding: list[float] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fields(self) -> "VectorDocument":
        if not self.project_id.strip() or not self.file_id.strip() or not self.chunk_id.strip():
            raise ValueError("chunk_id, project_id, and file_id must not be blank")
        if not self.text.strip():
            raise ValueError("text must not be blank")
        original_filename = self.metadata.get("original_filename")
        if not isinstance(original_filename, str) or not original_filename.strip():
            raise ValueError("metadata.original_filename must be provided")
        return self


class VectorSearchResult(BaseModel):
    chunk_id: str
    project_id: str
    file_id: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
