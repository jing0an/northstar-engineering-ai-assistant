"""Agent tool for project-scoped document retrieval."""

from __future__ import annotations

import inspect
from typing import Any

from app.services.citation import build_citations
from app.services.assistant_errors import citation_generation_failed
from app.services.embedding.bge_m3 import BGEM3EmbeddingProvider
from app.services.retrieval import RetrievalService
from app.services.vector_store.qdrant import QdrantVectorStore

_retrieval_service: RetrievalService | None = None


def _get_default_retrieval_service() -> RetrievalService:
    """Create the real retrieval service lazily on first tool use."""
    global _retrieval_service

    if _retrieval_service is None:
        embedding_provider = BGEM3EmbeddingProvider(device="cpu")
        embedding_provider.embed_text("初始化")

        vector_store = QdrantVectorStore(
            dimension=embedding_provider.dimension,
        )

        _retrieval_service = RetrievalService(
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )

    return _retrieval_service


def search_project_documents(
    query: str,
    project_id: str,
    top_k: int = 5,
    file_id: str | None = None,
    original_filename: str | None = None,
    is_current: bool | None = True,
    document_version: int | None = None,
    page_numbers: list[int] | None = None,
    retrieval_service: RetrievalService | None = None,
) -> dict[str, Any]:
    """Search document chunks belonging to one project."""

    service = retrieval_service or _get_default_retrieval_service()
    retrieve_kwargs = {
        "query": query,
        "project_id": project_id,
        "top_k": top_k,
        "file_id": file_id,
        "original_filename": original_filename,
        "document_version": document_version,
        "is_current": is_current,
        "page_numbers": page_numbers,
    }
    parameters = inspect.signature(service.retrieve).parameters
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if not accepts_kwargs:
        retrieve_kwargs = {
            key: value for key, value in retrieve_kwargs.items() if key in parameters
        }
    results = service.retrieve(**retrieve_kwargs)
    try:
        citations = [citation.model_dump() for citation in build_citations(results)]
    except Exception as error:
        raise citation_generation_failed() from error

    return {
        "query": query,
        "project_id": project_id,
        "file_id": file_id,
        "original_filename": original_filename,
        "page_numbers": page_numbers,
        "page_filter_applied": page_numbers is not None,
        "message": (
            "目标页没有找到足够的可检索文本证据；图片或扫描页面可能需要 OCR/视觉解析。"
            if page_numbers is not None and not results else None
        ),
        "citations": citations,
        "results": [
            {
                "chunk_id": result.chunk_id,
                "project_id": result.project_id,
                "file_id": result.file_id,
                "original_filename": result.metadata.get("original_filename"),
                "page_number": result.metadata.get("page_number"),
                "text": result.text,
                "score": result.score,
                "metadata": result.metadata,
            }
            for result in results
        ],
        # Backwards-compatible key with the same public-safe citation shape.
        "sources": citations,
    }
