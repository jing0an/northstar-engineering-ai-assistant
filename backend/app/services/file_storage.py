import json
from threading import RLock
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage"
METADATA_FILENAME = "metadata.json"


class FileUploadError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class FileStorage:
    def __init__(self, storage_root: Path = STORAGE_ROOT) -> None:
        self.storage_root = storage_root
        self._metadata_lock = RLock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _metadata_path(self, project_id: str) -> Path:
        return self.storage_root / project_id / METADATA_FILENAME

    def _read_metadata(self, project_id: str) -> list[dict[str, Any]]:
        metadata_path = self._metadata_path(project_id)
        if not metadata_path.exists():
            return []
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise FileUploadError("Failed to read the project file metadata.", 500) from error
        if not isinstance(loaded, list) or any(not isinstance(item, dict) for item in loaded):
            raise FileUploadError("Project file metadata has an invalid format.", 500)
        return loaded

    def _write_metadata(self, project_id: str, records: list[dict[str, Any]]) -> None:
        try:
            self._metadata_path(project_id).write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as error:
            raise FileUploadError("Failed to save the project file metadata.", 500) from error

    @staticmethod
    def _find_record(
        records: list[dict[str, Any]], project_id: str, file_id: str
    ) -> dict[str, Any] | None:
        return next(
            (
                item for item in records
                if item.get("project_id") == project_id and item.get("file_id") == file_id
            ),
            None,
        )

    async def save_upload(self, project_id: str, upload: UploadFile) -> dict[str, Any]:
        project_id = project_id.strip()
        if not project_id:
            raise FileUploadError("project_id is required.")
        if Path(project_id).name != project_id or project_id in {".", ".."}:
            raise FileUploadError("project_id contains invalid path characters.")
        if not upload.filename:
            raise FileUploadError("A file is required.")

        original_filename = Path(upload.filename).name
        extension = Path(original_filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise FileUploadError("Only .pdf and .docx files are supported.")

        project_dir = self.storage_root / project_id
        stored_filename = f"{uuid4().hex}{extension}"
        stored_path = project_dir / stored_filename
        size = 0
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            with stored_path.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    destination.write(chunk)
                    size += len(chunk)
            if size == 0:
                stored_path.unlink(missing_ok=True)
                raise FileUploadError("The uploaded file is empty.")

            metadata: dict[str, Any] = {
                "file_id": Path(stored_filename).stem,
                "project_id": project_id,
                "original_filename": original_filename,
                "stored_filename": stored_filename,
                "file_type": extension[1:],
                "size": size,
                "uploaded_at": self._now(),
                "is_duplicate": False,
                # A file is not searchable as the current version until its
                # vectors have been written and the version is activated.
                "is_current": False,
                "ingestion_status": "processing",
                "chunk_count": None,
                "vector_count": None,
                "ingestion_error": None,
                "ingestion_started_at": self._now(),
                "ingestion_completed_at": None,
            }
            with self._metadata_lock:
                existing = self._read_metadata(project_id)
                # Only explicit, modern version values participate.  Legacy
                # records remain untouched rather than being guessed as v1.
                same_name_versions = [
                    version
                    for item in existing
                    if item.get("project_id") == project_id
                    and item.get("original_filename") == original_filename
                    and item.get("is_duplicate") is not True
                    for version in [item.get("document_version")]
                    if isinstance(version, int) and not isinstance(version, bool)
                    and version >= 1
                ]
                metadata["document_version"] = max(same_name_versions, default=0) + 1
                existing.append(metadata)
                self._write_metadata(project_id, existing)
            return metadata
        except FileUploadError:
            raise
        except (OSError, json.JSONDecodeError) as error:
            stored_path.unlink(missing_ok=True)
            raise FileUploadError("Failed to save the uploaded file.", 500) from error

    def begin_reingestion(self, project_id: str, file_id: str) -> dict[str, Any]:
        with self._metadata_lock:
            records = self._read_metadata(project_id)
            record = self._find_record(records, project_id, file_id)
            if record is None:
                raise FileUploadError("File not found in this project.", 404)
            if record.get("ingestion_status") == "processing":
                raise FileUploadError("File ingestion is already processing.", 409)
            if record.get("ingestion_status") != "failed":
                raise FileUploadError("Only failed files can be re-ingested.", 409)
            record.update({
                "ingestion_status": "processing",
                "chunk_count": None,
                "vector_count": None,
                "ingestion_error": None,
                "ingestion_started_at": self._now(),
                "ingestion_completed_at": None,
            })
            self._write_metadata(project_id, records)
            return dict(record)

    def resolve_file_content(
        self, project_id: str, file_id: str
    ) -> tuple[dict[str, Any], Path]:
        """Resolve one metadata-owned file without allowing paths outside its project."""
        with self._metadata_lock:
            record = self._find_record(
                self._read_metadata(project_id), project_id, file_id
            )
            if record is None:
                raise FileUploadError("File not found in this project.", 404)

            stored_filename = record.get("stored_filename")
            if (
                not isinstance(stored_filename, str)
                or not stored_filename
                or Path(stored_filename).name != stored_filename
                or stored_filename in {".", ".."}
            ):
                raise FileUploadError("Stored file path is invalid.", 404)

            project_dir = (self.storage_root / project_id).resolve()
            stored_path = (project_dir / stored_filename).resolve()
            try:
                stored_path.relative_to(project_dir)
            except ValueError as error:
                raise FileUploadError("Stored file path is invalid.", 404) from error

            if not stored_path.is_file():
                raise FileUploadError("Stored file was not found.", 404)

            return dict(record), stored_path

    def current_file_ids(self, project_id: str, original_filename: str, *, exclude_file_id: str) -> list[str]:
        with self._metadata_lock:
            return [
                str(item["file_id"])
                for item in self._read_metadata(project_id)
                if item.get("project_id") == project_id
                and item.get("original_filename") == original_filename
                and item.get("is_duplicate") is not True
                and item.get("is_current") is True
                and item.get("file_id") != exclude_file_id
                and isinstance(item.get("file_id"), str)
            ]

    def mark_ingestion_failed(
        self, project_id: str, file_id: str, *, stage: str, message: str
    ) -> dict[str, Any]:
        with self._metadata_lock:
            records = self._read_metadata(project_id)
            record = self._find_record(records, project_id, file_id)
            if record is None:
                raise FileUploadError("File not found in this project.", 404)
            record.update({
                "is_current": False,
                "ingestion_status": "failed",
                "chunk_count": None,
                "vector_count": None,
                "ingestion_error": {"stage": stage, "message": message},
                "ingestion_completed_at": self._now(),
            })
            self._write_metadata(project_id, records)
            return dict(record)

    def complete_ingestion_and_activate(
        self,
        project_id: str,
        file_id: str,
        *,
        chunk_count: int,
        vector_count: int,
    ) -> dict[str, Any]:
        with self._metadata_lock:
            records = self._read_metadata(project_id)
            record = self._find_record(records, project_id, file_id)
            if record is None:
                raise FileUploadError("File not found in this project.", 404)
            original_filename = record.get("original_filename")
            for item in records:
                # Legacy records without is_current are deliberately not
                # rewritten: their historical version relation is unknown.
                if (
                    item is not record
                    and item.get("project_id") == project_id
                    and item.get("original_filename") == original_filename
                    and item.get("is_duplicate") is not True
                    and item.get("is_current") is True
                ):
                    item["is_current"] = False
            record.update({
                "is_current": True,
                "ingestion_status": "completed",
                "chunk_count": chunk_count,
                "vector_count": vector_count,
                "ingestion_error": None,
                "ingestion_completed_at": self._now(),
            })
            self._write_metadata(project_id, records)
            return dict(record)


file_storage = FileStorage()
