"""Qdrant-backed vector store with project payload isolation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .config import QDRANT_COLLECTION, QDRANT_HOST, QDRANT_PORT
from .models import VectorDocument, VectorSearchResult

DEFAULT_QDRANT_HOST = QDRANT_HOST
DEFAULT_QDRANT_PORT = QDRANT_PORT
DEFAULT_COLLECTION_NAME = QDRANT_COLLECTION


class QdrantVectorStore:
    def __init__(
        self,
        dimension: int,
        *,
        host: str = DEFAULT_QDRANT_HOST,
        port: int = DEFAULT_QDRANT_PORT,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        client: Any | None = None,
    ) -> None:
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
            raise ValueError("dimension must be a positive integer")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host must be a non-empty string")
        if not isinstance(port, int) or isinstance(port, bool) or port <= 0:
            raise ValueError("port must be a positive integer")
        if not isinstance(collection_name, str) or not collection_name.strip():
            raise ValueError("collection_name must be a non-empty string")
        self.dimension = dimension
        self.host = host.strip()
        self.port = port
        self.collection_name = collection_name.strip()
        self.client = client if client is not None else self._create_client(self.host, self.port)
        self._ensure_collection()

    @staticmethod
    def _create_client(host: str, port: int) -> Any:
        try:
            from qdrant_client import QdrantClient
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("qdrant-client is required for QdrantVectorStore") from error
        return QdrantClient(host=host, port=port)

    def _collection_exists(self) -> bool:
        checker = getattr(self.client, "collection_exists", None)
        if callable(checker):
            return bool(checker(self.collection_name))
        try:
            self.client.get_collection(self.collection_name)
        except Exception:
            return False
        return True

    @staticmethod
    def _collection_dimension(info: Any) -> int | None:
        config = getattr(info, "config", None)
        params = getattr(config, "params", None)
        vectors = getattr(params, "vectors", None)
        if vectors is None and isinstance(info, dict):
            vectors = info.get("config", {}).get("params", {}).get("vectors")
        value = vectors.get("size") if isinstance(vectors, dict) else getattr(vectors, "size", None)
        return value if isinstance(value, int) else None

    def _ensure_collection(self) -> None:
        if self._collection_exists():
            existing = self._collection_dimension(self.client.get_collection(self.collection_name))
            if existing is not None and existing != self.dimension:
                raise ValueError(
                    f"Collection {self.collection_name!r} dimension mismatch: expected {self.dimension}, found {existing}"
                )
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={"size": self.dimension, "distance": "Cosine"},
        )

    @staticmethod
    def _point_id(chunk_id: str, project_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"northstar:{project_id}:{chunk_id}"))

    @staticmethod
    def _match_condition(key: str, value: Any) -> dict[str, Any]:
        return {"key": key, "match": {"value": value}}

    def add_documents(self, documents: Sequence[VectorDocument]) -> int:
        if not isinstance(documents, Sequence) or isinstance(documents, (str, bytes)):
            raise TypeError("documents must be a sequence of VectorDocument")
        documents = list(documents)
        if not documents:
            return 0
        points = []
        for document in documents:
            if not isinstance(document, VectorDocument):
                raise TypeError("documents must contain VectorDocument instances")
            if len(document.embedding) != self.dimension:
                raise ValueError("document embedding dimension does not match the collection")
            payload = {
                **document.metadata,
                "project_id": document.project_id,
                "file_id": document.file_id,
                "chunk_id": document.chunk_id,
                "text": document.text,
            }
            points.append({"id": self._point_id(document.chunk_id, document.project_id), "vector": document.embedding, "payload": payload})
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        return len(points)

    def update_file_metadata(
        self,
        *,
        project_id: str,
        file_id: str,
        metadata: dict[str, Any],
    ) -> None:
        """Update payload metadata for one existing file without touching vectors."""
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must not be blank")
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError("file_id must not be blank")
        if not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary")
        if not metadata:
            return
        try:
            from qdrant_client.http import models
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("qdrant-client is required for payload updates") from error
        selector = models.Filter(
            must=[
                models.FieldCondition(
                    key="project_id",
                    match=models.MatchValue(value=project_id.strip()),
                ),
                models.FieldCondition(
                    key="file_id",
                    match=models.MatchValue(value=file_id.strip()),
                ),
            ]
        )
        self.client.set_payload(
            collection_name=self.collection_name,
            payload=dict(metadata),
            points=selector,
            wait=True,
        )

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
    ) -> list[VectorSearchResult]:
        if not isinstance(query_embedding, Sequence) or isinstance(query_embedding, (str, bytes)):
            raise TypeError("query_embedding must be a sequence of numbers")
        if len(query_embedding) != self.dimension:
            raise ValueError("query embedding dimension does not match the collection")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must not be blank")
        if file_id is not None and (not isinstance(file_id, str) or not file_id.strip()):
            raise ValueError("file_id must not be blank")

        if original_filename is not None and (
                not isinstance(original_filename, str) or not original_filename.strip()
        ):
            raise ValueError("original_filename must not be blank")
        if is_current is not None and not isinstance(is_current, bool):
            raise ValueError("is_current must be a boolean when provided")
        if document_version is not None and (not isinstance(document_version, int) or isinstance(document_version, bool) or document_version <= 0):
            raise ValueError("document_version must be a positive integer when provided")
        if page_numbers is not None and (
            isinstance(page_numbers, (str, bytes)) or not isinstance(page_numbers, Sequence)
        ):
            raise ValueError("page_numbers must be a sequence of positive integers when provided")
        normalized_page_numbers = tuple(sorted(set(page_numbers))) if page_numbers is not None else ()
        if any(not isinstance(page, int) or isinstance(page, bool) or page <= 0 for page in normalized_page_numbers):
            raise ValueError("page_numbers must contain positive integers")
        kwargs: dict[str, Any] = {
            "collection_name": self.collection_name,
            "query": list(query_embedding),
            "limit": top_k,
            "with_payload": True,
        }
        conditions = []

        if project_id:
            conditions.append(
                self._match_condition("project_id", project_id.strip())
            )

        if file_id:
            conditions.append(
                self._match_condition("file_id", file_id.strip())
            )

        if original_filename:
            conditions.append(
                self._match_condition(
                    "original_filename",
                    original_filename.strip(),
                )
            )

        if is_current is not None:
            conditions.append(self._match_condition("is_current", is_current))

        if document_version is not None:
            conditions.append(self._match_condition("document_version", document_version))

        if conditions or normalized_page_numbers:
            query_filter: dict[str, Any] = {"must": conditions}
            if normalized_page_numbers:
                query_filter["should"] = [
                    self._match_condition("page_number", page)
                    for page in normalized_page_numbers
                ]
            kwargs["query_filter"] = query_filter
        query_points = getattr(self.client, "query_points", None)
        if callable(query_points):
            response = query_points(**kwargs)
            points = getattr(response, "points", response)
        else:
            kwargs["query_vector"] = kwargs.pop("query")
            response = self.client.search(**kwargs)
            points = response
        results = []
        for point in points or []:
            payload = getattr(point, "payload", None) or (point.get("payload", {}) if isinstance(point, dict) else {})
            score = getattr(point, "score", None)
            if score is None and isinstance(point, dict):
                score = point.get("score", 0.0)
            results.append(VectorSearchResult(
                chunk_id=str(payload.get("chunk_id", "")), project_id=str(payload.get("project_id", "")),
                file_id=str(payload.get("file_id", "")), text=str(payload.get("text", "")),
                score=float(score or 0.0), metadata=dict(payload),
            ))
        return results

    def delete(self, *, chunk_ids: Sequence[str] | None = None, file_id: str | None = None, project_id: str | None = None) -> None:
        if chunk_ids:
            ids = [str(value) for value in chunk_ids]
            if any(not value.strip() for value in ids):
                raise ValueError("chunk_ids must not contain blank values")
            conditions = [self._match_condition("chunk_id", value) for value in ids]
            if project_id:
                conditions.append(self._match_condition("project_id", project_id))
            self.client.delete(collection_name=self.collection_name, points_selector={"filter": {"must": conditions}}, wait=True)
            return
        conditions = []
        if file_id:
            conditions.append(self._match_condition("file_id", file_id))
        if project_id:
            conditions.append(self._match_condition("project_id", project_id))
        if not conditions:
            raise ValueError("provide chunk_ids, file_id, or project_id")
        self.client.delete(collection_name=self.collection_name, points_selector={"filter": {"must": conditions}}, wait=True)

    def health(self) -> bool:
        try:
            self.client.get_collections()
        except Exception:
            return False
        return True


