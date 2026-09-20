"""Project-scoped document retrieval orchestration."""

from __future__ import annotations

from collections.abc import Sequence
import inspect
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.embedding.base import EmbeddingProvider
from app.services.vector_store.base import VectorStore
from app.services.vector_store.models import VectorSearchResult


class RetrievalResult(BaseModel):
    """A document chunk returned for a project-scoped query."""

    model_config = ConfigDict(extra="allow")

    chunk_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    file_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_non_blank(self) -> "RetrievalResult":
        if not self.chunk_id.strip() or not self.project_id.strip() or not self.file_id.strip():
            raise ValueError("chunk_id, project_id, and file_id must not be blank")
        if not self.text.strip():
            raise ValueError("text must not be blank")
        return self


class RetrievalService:
    """Embed a query and search the vector store within one project."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    @staticmethod
    def _required_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _validate_top_k(top_k: int) -> int:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        return top_k

    @staticmethod
    def _as_result(value: RetrievalResult | VectorSearchResult | dict[str, Any]) -> RetrievalResult:
        if isinstance(value, RetrievalResult):
            return value
        if isinstance(value, VectorSearchResult):
            return RetrievalResult.model_validate(value.model_dump())
        if isinstance(value, dict):
            return RetrievalResult.model_validate(value)
        raise TypeError("vector store returned an invalid retrieval result")

    def retrieve(
            self,
            query: str,
            project_id: str,
            top_k: int = 5,
            file_id: str | None = None,
            original_filename: str | None = None,
            is_current: bool | None = None,
            document_version: int | None = None,
            page_numbers: Sequence[int] | None = None,
    ) -> list[RetrievalResult]:
        """Return matching chunks within a project, optionally limited to one file."""
        normalized_query = self._required_text(query, "query")
        normalized_project_id = self._required_text(project_id, "project_id")
        normalized_top_k = self._validate_top_k(top_k)

        normalized_file_id = (
            self._required_text(file_id, "file_id")
            if file_id is not None
            else None
        )
        normalized_original_filename = (
            self._required_text(original_filename, "original_filename")
            if original_filename is not None
            else None
        )
        if is_current is not None and not isinstance(is_current, bool):
            raise ValueError("is_current must be a boolean when provided")
        if document_version is not None and (not isinstance(document_version, int) or isinstance(document_version, bool) or document_version <= 0):
            raise ValueError("document_version must be a positive integer when provided")
        normalized_page_numbers: tuple[int, ...] | None = None
        if page_numbers is not None:
            if isinstance(page_numbers, (str, bytes)) or not isinstance(page_numbers, Sequence):
                raise ValueError("page_numbers must be a sequence of positive integers when provided")
            normalized_page_numbers = tuple(sorted(set(page_numbers)))
            if not normalized_page_numbers or any(
                not isinstance(page, int) or isinstance(page, bool) or page <= 0
                for page in normalized_page_numbers
            ):
                raise ValueError("page_numbers must contain positive integers")

        try:
            query_embedding = self.embedding_provider.embed_text(normalized_query)
        except Exception as error:
            raise RuntimeError("Failed to embed retrieval query") from error

        if not isinstance(query_embedding, Sequence) or isinstance(
                query_embedding, (str, bytes)
        ):
            raise RuntimeError("Embedding provider returned an invalid query vector")

        try:
            search_kwargs = {
                "top_k": normalized_top_k,
                "project_id": normalized_project_id,
                "file_id": normalized_file_id,
                "original_filename": normalized_original_filename,
                "page_numbers": normalized_page_numbers,
            }
            if document_version is not None:
                search_kwargs["document_version"] = document_version
            if is_current is not None:
                search_kwargs["is_current"] = is_current
            parameters = inspect.signature(self.vector_store.search).parameters
            accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            if not accepts_kwargs:
                search_kwargs = {
                    key: value
                    for key, value in search_kwargs.items()
                    if key in parameters
                }
            raw_results = self.vector_store.search(query_embedding, **search_kwargs)
        except Exception as error:
            raise RuntimeError("Failed to search project vectors") from error

        if raw_results is None:
            return []

        if not isinstance(raw_results, Sequence) or isinstance(
                raw_results, (str, bytes)
        ):
            raise RuntimeError("Vector store returned an invalid result list")

        results: list[RetrievalResult] = []

        for raw_result in raw_results:
            result = self._as_result(raw_result)

            # Project isolation is always enforced at the retrieval boundary.
            if result.project_id != normalized_project_id:
                continue

            # File isolation is enforced again here even though the vector store
            # already receives the filters.
            if normalized_file_id is not None and result.file_id != normalized_file_id:
                continue

            if normalized_original_filename is not None:
                result_filename = str(
                    result.metadata.get("original_filename", "")
                ).strip()

                if result_filename != normalized_original_filename:
                    continue

            if document_version is not None and result.metadata.get("document_version") != document_version:
                continue

            if is_current is not None and result.metadata.get("is_current") is not is_current:
                continue

            if normalized_page_numbers is not None and result.metadata.get("page_number") not in normalized_page_numbers:
                continue

            results.append(result)

        return results





