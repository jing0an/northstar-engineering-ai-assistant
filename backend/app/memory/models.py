"""Validated, persistence-agnostic Memory model for A2.1."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .types import MemoryScope, MemorySource, MemoryType


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Memory(BaseModel):
    """A single explicitly-created memory record.

    This model only validates data. It does not persist, infer, or update
    memories automatically.
    """

    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(min_length=1)
    scope: MemoryScope
    user_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    content: str = Field(min_length=1)
    memory_type: MemoryType
    source: MemorySource
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("memory_id", "content", "user_id", "project_id")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("string fields must not be blank")
        return value.strip() if value is not None else None

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_scope_identifiers(self) -> "Memory":
        if self.scope in {
            MemoryScope.USER,
            MemoryScope.PROJECT,
            MemoryScope.CONVERSATION,
        } and self.user_id is None:
            raise ValueError(f"user_id is required for {self.scope.value} scope")
        if self.scope is MemoryScope.PROJECT and self.project_id is None:
            raise ValueError("project_id is required for project scope")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


MemoryRecord = Memory