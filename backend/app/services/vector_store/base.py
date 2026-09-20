"""Provider-neutral vector store contract."""

from collections.abc import Sequence
from typing import Any, Protocol

from .models import VectorDocument, VectorSearchResult


class VectorStore(Protocol):
    def add_documents(self, documents: Sequence[VectorDocument]) -> int: ...

    def search(
            self,
            query_embedding: Sequence[float],
            top_k: int = 5,
            project_id: str | None = None,
            file_id: str | None = None,
            original_filename: str | None = None,
            is_current: bool | None = None,
            document_version: int | None = None,
            page_numbers: Sequence[int] | None = None,
    ) -> list[VectorSearchResult]: ...

    def delete(
        self,
        *,
        chunk_ids: Sequence[str] | None = None,
        file_id: str | None = None,
        project_id: str | None = None,
    ) -> None: ...

    def update_file_metadata(
        self,
        *,
        project_id: str,
        file_id: str,
        metadata: dict[str, Any],
    ) -> None: ...

