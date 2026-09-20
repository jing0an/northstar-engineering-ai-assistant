import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.auth.dependencies import check_project_access, get_current_user
from app.auth.models import User

from app.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
    IngestionFileNotFoundError,
)
from app.services.document_parser import extract_pages, extract_text
from app.services.document_preview import DocumentPreviewError, build_docx_preview
from app.services.embedding.bge_m3 import BGEM3EmbeddingProvider
from app.services.file_storage import FileUploadError, file_storage
from app.services.text_chunker import chunk_text
from app.services.vector_store import (
    QDRANT_COLLECTION,
    QDRANT_HOST,
    QDRANT_PORT,
    QdrantVectorStore,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


def _create_ingestion_service() -> DocumentIngestionService:
    embedding_provider = BGEM3EmbeddingProvider(device="cpu")
    embedding_provider.embed_text("初始化")

    vector_store = QdrantVectorStore(
        embedding_provider.dimension,
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        collection_name=QDRANT_COLLECTION,
    )
    return DocumentIngestionService(
        parser=extract_text,
        page_parser=extract_pages,
        chunker=chunk_text,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )


def _stored_file_path(metadata: dict) -> Path:
    project_id = metadata.get("project_id")
    stored_filename = metadata.get("stored_filename")
    if not isinstance(project_id, str) or not isinstance(stored_filename, str):
        raise IngestionFileNotFoundError("File metadata is missing the stored file path.")
    if not stored_filename or stored_filename in {".", ".."} or "/" in stored_filename or "\\" in stored_filename:
        raise IngestionFileNotFoundError("File metadata contains an invalid stored file path.")
    return file_storage.storage_root / project_id / stored_filename


def _best_effort_delete_file_vectors(ingestion: DocumentIngestionService | None, metadata: dict) -> None:
    if ingestion is None:
        return
    delete = getattr(ingestion.vector_store, "delete", None)
    if not callable(delete):
        return
    try:
        delete(file_id=str(metadata["file_id"]), project_id=str(metadata["project_id"]))
    except Exception:
        logger.exception("Failed to clean vectors for file %s", metadata.get("file_id"))


def _restore_previous_current_vectors(
        ingestion: DocumentIngestionService | None,
        metadata: dict,
        previous_current_ids: list[str],
) -> None:
    if ingestion is None:
        return
    update = getattr(ingestion.vector_store, "update_file_metadata", None)
    if not callable(update):
        return
    project_id = str(metadata["project_id"])
    try:
        update(project_id=project_id, file_id=str(metadata["file_id"]), metadata={"is_current": False})
        for file_id in previous_current_ids:
            update(project_id=project_id, file_id=file_id, metadata={"is_current": True})
    except Exception:
        logger.exception("Failed to restore current vector metadata for file %s", metadata.get("file_id"))


def _run_ingestion(metadata: dict) -> tuple[dict, object]:
    """Ingest one existing metadata record and activate it only on success."""
    project_id = str(metadata["project_id"])
    file_id = str(metadata["file_id"])
    previous_current_ids = file_storage.current_file_ids(
        project_id,
        str(metadata["original_filename"]),
        exclude_file_id=file_id,
    )
    ingestion: DocumentIngestionService | None = None

    try:
        ingestion = _create_ingestion_service()
        result = ingestion.ingest(
            file_id=file_id,
            project_id=project_id,
            file_path=_stored_file_path(metadata),
            file_type=str(metadata["file_type"]),
            original_filename=str(metadata["original_filename"]),
            document_version=int(metadata["document_version"]),
            # A processing version must not appear in default current-only RAG.
            is_current=False,
            uploaded_at=str(metadata["uploaded_at"]),
            is_duplicate=bool(metadata.get("is_duplicate", False)),
            duplicate_of_file_id=metadata.get("duplicate_of_file_id"),
        )
    except DocumentIngestionError as error:
        if error.stage == "vector_store":
            _best_effort_delete_file_vectors(ingestion, metadata)
        file_storage.mark_ingestion_failed(
            project_id, file_id, stage=error.stage, message=str(error)
        )
        raise
    except Exception as error:
        _best_effort_delete_file_vectors(ingestion, metadata)
        file_storage.mark_ingestion_failed(
            project_id, file_id, stage="ingestion", message=str(error)
        )
        raise DocumentIngestionError(f"Failed to initialize ingestion: {error}") from error

    try:
        update = getattr(ingestion.vector_store, "update_file_metadata", None)
        if not callable(update):
            raise RuntimeError("Vector store does not support file metadata updates")
        for previous_file_id in previous_current_ids:
            update(
                project_id=project_id,
                file_id=previous_file_id,
                metadata={"is_current": False},
            )
        update(
            project_id=project_id,
            file_id=file_id,
            metadata={"is_current": True},
        )
        persisted = file_storage.complete_ingestion_and_activate(
            project_id,
            file_id,
            chunk_count=result.chunk_count,
            vector_count=result.vector_count,
        )
        return persisted, result
    except Exception as error:
        _restore_previous_current_vectors(ingestion, metadata, previous_current_ids)
        _best_effort_delete_file_vectors(ingestion, metadata)
        failure = DocumentIngestionError(f"Failed to activate ingested file: {error}")
        failure.stage = "vector_store"
        file_storage.mark_ingestion_failed(
            project_id, file_id, stage=failure.stage, message=str(failure)
        )
        raise failure from error

@router.post("/upload", status_code=201)
async def upload_file(
        project_id: str = Form(...),
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
) -> dict:
    check_project_access(current_user, project_id)

    try:
        metadata = await file_storage.save_upload(project_id, file)

        persisted, result = _run_ingestion(metadata)

        return {
            **persisted,
            "ingestion": result.model_dump(),
        }

    except FileUploadError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=str(error),
        ) from error

    except DocumentIngestionError as error:
        raise HTTPException(
            status_code=500,
            detail=f"文件上传成功，但知识库入库失败：{error}",
        ) from error


@router.post("/{file_id}/reingest")
async def reingest_file(
        file_id: str,
        project_id: str = Form(...),
        current_user: User = Depends(get_current_user),
) -> dict:
    project_id = _validate_project_id(project_id)
    check_project_access(current_user, project_id)

    try:
        metadata = file_storage.begin_reingestion(project_id, file_id)
        persisted, result = _run_ingestion(metadata)
        return {
            **persisted,
            "ingestion": result.model_dump(),
        }
    except FileUploadError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except DocumentIngestionError as error:
        raise HTTPException(
            status_code=500,
            detail=f"文件重新入库失败：{error}",
        ) from error


@router.get("/{file_id}/content")
async def get_file_content(
        file_id: str,
        project_id: str,
        current_user: User = Depends(get_current_user),
) -> FileResponse:
    project_id = _validate_project_id(project_id)
    check_project_access(current_user, project_id)

    try:
        metadata, stored_path = file_storage.resolve_file_content(project_id, file_id)
    except FileUploadError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    if metadata.get("file_type") != "pdf" or stored_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="当前暂不支持在线预览该文件类型")

    original_filename = metadata.get("original_filename")
    if not isinstance(original_filename, str) or not original_filename:
        original_filename = f"{file_id}.pdf"

    return FileResponse(
        stored_path,
        media_type="application/pdf",
        filename=Path(original_filename).name,
        content_disposition_type="inline",
    )


@router.get("/{file_id}/preview")
async def get_file_preview(
        file_id: str,
        project_id: str,
        current_user: User = Depends(get_current_user),
) -> dict:
    project_id = _validate_project_id(project_id)
    check_project_access(current_user, project_id)

    try:
        metadata, stored_path = file_storage.resolve_file_content(project_id, file_id)
    except FileUploadError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    if metadata.get("file_type") != "docx" or stored_path.suffix.lower() != ".docx":
        raise HTTPException(status_code=415, detail="当前 preview 接口仅支持 DOCX")

    try:
        return build_docx_preview(
            stored_path,
            file_id=file_id,
            project_id=project_id,
            document_version=metadata.get("document_version"),
            original_filename=str(metadata.get("original_filename") or f"{file_id}.docx"),
        )
    except DocumentPreviewError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _validate_project_id(project_id: str) -> str:
    project_id = project_id.strip()

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id 不能为空")

    if project_id in {".", ".."}:
        raise HTTPException(status_code=400, detail="project_id 不能包含 . 或 ..")

    if "/" in project_id or "\\" in project_id:
        raise HTTPException(status_code=400, detail="project_id 不能包含路径分隔符")

    if "\x00" in project_id:
        raise HTTPException(status_code=400, detail="project_id 不能包含 NUL 字符")

    return project_id


def _uploaded_at_sort_key(record: dict) -> tuple[int, float]:
    uploaded_at = record.get("uploaded_at")
    if not isinstance(uploaded_at, str):
        return 0, 0.0

    try:
        normalized = (
            f"{uploaded_at[:-1]}+00:00"
            if uploaded_at.endswith("Z")
            else uploaded_at
        )
        return 1, datetime.fromisoformat(normalized).timestamp()
    except (OSError, OverflowError, ValueError):
        return 0, 0.0


@router.get("")
async def list_files(
        project_id: str,
        current_user: User = Depends(get_current_user),
) -> dict:
    project_id = _validate_project_id(project_id)
    check_project_access(current_user, project_id)

    metadata_path = file_storage.storage_root / project_id / "metadata.json"

    if not metadata_path.exists():
        return {
            "project_id": project_id,
            "files": []
        }

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata_list = json.load(f)
    except json.JSONDecodeError as error:
        logger.error(f"Failed to parse metadata.json for project {project_id}: {error}")
        raise HTTPException(
            status_code=500,
            detail="项目文件列表数据格式异常"
        ) from error

    if not isinstance(metadata_list, list) or any(
            not isinstance(record, dict) for record in metadata_list
    ):
        logger.error("Invalid metadata.json structure for project %s", project_id)
        raise HTTPException(
            status_code=500,
            detail="项目文件列表数据格式异常",
        )

    files = []
    for record in metadata_list:
        if record.get("project_id") != project_id:
            continue
        files.append({
            "file_id": record.get("file_id"),
            "original_filename": record.get("original_filename"),
            "file_type": record.get("file_type"),
            "size": record.get("size"),
            "uploaded_at": record.get("uploaded_at"),
            "document_version": record.get("document_version"),
            "is_current": record.get("is_current"),
            "ingestion_status": record.get("ingestion_status"),
            "chunk_count": record.get("chunk_count"),
            "vector_count": record.get("vector_count"),
            "ingestion_error": record.get("ingestion_error"),
            "ingestion_started_at": record.get("ingestion_started_at"),
            "ingestion_completed_at": record.get("ingestion_completed_at"),
        })

    files.sort(key=_uploaded_at_sort_key, reverse=True)

    return {
        "project_id": project_id,
        "files": files
    }
