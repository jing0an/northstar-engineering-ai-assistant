"""Document-to-vector ingestion orchestration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from app.services.embedding.base import EmbeddingProvider
from app.services.vector_store.base import VectorStore
from app.services.vector_store.models import VectorDocument

DocumentParser = Callable[[str | Path, str], str]
PageParser = Callable[[str | Path, str], list[dict[str, object]]]
TextChunker = Callable[[str], list[str]]


class DocumentIngestionError(RuntimeError):
    """Base error for a failed ingestion stage."""

    stage: str = "ingestion"


class IngestionFileNotFoundError(DocumentIngestionError):
    stage = "file"


class UnsupportedDocumentTypeError(DocumentIngestionError):
    stage = "file_type"


class TextExtractionError(DocumentIngestionError):
    stage = "text_extraction"


class EmptyDocumentTextError(TextExtractionError):
    stage = "empty_text"


class ChunkingError(DocumentIngestionError):
    stage = "chunking"


class EmbeddingError(DocumentIngestionError):
    stage = "embedding"


class VectorStoreWriteError(DocumentIngestionError):
    stage = "vector_store"


class IngestionResult(BaseModel):
    file_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    chunk_count: int = Field(ge=0)
    vector_count: int = Field(ge=0)
    status: Literal["completed"] = "completed"


class DocumentIngestionService:
    """Coordinate parsing, chunking, embedding, and vector persistence."""

    ALLOWED_FILE_TYPES = frozenset({"pdf", "docx"})

    def __init__(
        self,
        parser: DocumentParser,
        chunker: TextChunker,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        page_parser: PageParser | None = None,
    ) -> None:
        self.parser = parser
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.page_parser = page_parser

    @staticmethod
    def _required_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()

    @classmethod
    def _normalize_file_type(cls, file_type: str) -> str:
        normalized = cls._required_text(file_type, "file_type").lower().lstrip(".")
        if normalized not in cls.ALLOWED_FILE_TYPES:
            raise UnsupportedDocumentTypeError(
                f"Unsupported document type: {file_type}. Only pdf and docx are supported."
            )
        return normalized

    @staticmethod
    def _chunk_id(project_id: str, file_id: str, chunk_index: int) -> str:
        return str(uuid5(NAMESPACE_URL, f"northstar:{project_id}:{file_id}:{chunk_index}"))

    def _chunk_text(self, text: str, path: Path) -> list[str]:
        try:
            chunks = self.chunker(text)
        except Exception as error:
            raise ChunkingError(f"Failed to chunk document: {path}") from error
        if not isinstance(chunks, list) or any(not isinstance(chunk, str) for chunk in chunks):
            raise ChunkingError("Text chunker must return a list of strings")
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def _page_aware_chunks(
        self, path: Path, normalized_type: str
    ) -> tuple[list[str], list[int]]:
        try:
            pages = self.page_parser(path, normalized_type)
        except DocumentIngestionError:
            raise
        except Exception as error:
            raise TextExtractionError(f"Failed to extract text from {path}") from error

        if not isinstance(pages, list):
            raise TextExtractionError("Page parser must return a list of page dictionaries")

        chunks: list[str] = []
        page_numbers: list[int] = []
        for page in pages:
            if not isinstance(page, dict):
                raise TextExtractionError("Page parser returned a non-dict page")
            if "text" not in page or not isinstance(page["text"], str):
                raise TextExtractionError("Page parser pages must contain string text")

            page_number = page.get("page_number")
            if (
                not isinstance(page_number, int)
                or isinstance(page_number, bool)
                or page_number <= 0
            ):
                raise TextExtractionError(
                    "Page parser page_number must be a positive integer"
                )

            page_text = page["text"]
            if not page_text.strip():
                continue

            page_chunks = self._chunk_text(page_text, path)
            for chunk in page_chunks:
                chunks.append(chunk)
                page_numbers.append(page_number)

        if not chunks:
            raise EmptyDocumentTextError(f"Document contains no extractable text: {path}")
        return chunks, page_numbers

    def ingest(
        self,
        file_id: str,
        project_id: str,
        file_path: str | Path,
        file_type: str,
        original_filename: str,
        document_version: int | None = None,
        is_current: bool | None = None,
        uploaded_at: str | None = None,
        is_duplicate: bool | None = None,
        duplicate_of_file_id: str | None = None,
    ) -> IngestionResult:
        file_id = self._required_text(file_id, "file_id")
        project_id = self._required_text(project_id, "project_id")
        original_filename = self._required_text(original_filename, "original_filename")
        normalized_type = self._normalize_file_type(file_type)
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise IngestionFileNotFoundError(f"Document file does not exist: {path}")

        if self.page_parser is not None:
            chunks, page_numbers = self._page_aware_chunks(path, normalized_type)
        else:
            try:
                text = self.parser(path, normalized_type)
            except DocumentIngestionError:
                raise
            except Exception as error:
                raise TextExtractionError(f"Failed to extract text from {path}") from error
            if not isinstance(text, str):
                raise TextExtractionError("Document parser returned a non-string result")
            if not text.strip():
                raise EmptyDocumentTextError(
                    f"Document contains no extractable text: {path}"
                )

            chunks = self._chunk_text(text, path)
            if not chunks:
                raise ChunkingError("Text chunker returned no non-empty chunks")
            page_numbers = []

        try:
            embeddings = self.embedding_provider.embed_texts(chunks)
        except Exception as error:
            raise EmbeddingError(f"Failed to embed document chunks: {path}") from error
        if not isinstance(embeddings, list) or len(embeddings) != len(chunks):
            raise EmbeddingError("Embedding provider returned an invalid batch size")

        documents: list[VectorDocument] = []
        for chunk_index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_id = self._chunk_id(project_id, file_id, chunk_index)
            metadata: dict[str, Any] = {
                "project_id": project_id,
                "file_id": file_id,
                "chunk_id": chunk_id,
                "original_filename": original_filename,
                "file_type": normalized_type,
                "chunk_index": chunk_index,
            }
            if self.page_parser is not None:
                metadata["page_number"] = page_numbers[chunk_index]
            if document_version is not None:
                metadata["document_version"] = document_version
            if is_current is not None:
                metadata["is_current"] = is_current
            if uploaded_at is not None:
                metadata["uploaded_at"] = uploaded_at
            if is_duplicate is not None:
                metadata["is_duplicate"] = is_duplicate
            if duplicate_of_file_id is not None:
                metadata["duplicate_of_file_id"] = duplicate_of_file_id
            documents.append(
                VectorDocument(
                    chunk_id=chunk_id,
                    project_id=project_id,
                    file_id=file_id,
                    text=chunk,
                    embedding=embedding,
                    metadata=metadata,
                )
            )

        try:
            vector_count = self.vector_store.add_documents(documents)
        except Exception as error:
            raise VectorStoreWriteError(f"Failed to write document vectors: {path}") from error
        if not isinstance(vector_count, int) or vector_count != len(documents):
            raise VectorStoreWriteError(
                f"Vector store wrote {vector_count!r} vectors; expected {len(documents)}"
            )
        return IngestionResult(
            file_id=file_id,
            project_id=project_id,
            chunk_count=len(chunks),
            vector_count=vector_count,
        )