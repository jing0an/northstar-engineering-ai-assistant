import io
import json
import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from reportlab.pdfgen import canvas

from fastapi.testclient import TestClient

from app.auth.models import ProjectMembership, ProjectRole, User, UserStatus
from app.auth.persistence import (
    SQLiteProjectMembershipRepository,
    SQLiteUserRepository,
)
from app.auth.store import AuthStore
from app.auth.token import AccessTokenService

from app.main import app
from app.services.document_ingestion import (
    EmbeddingError,
    IngestionResult,
    TextExtractionError,
    VectorStoreWriteError,
)
from app.services.file_storage import FileStorage
import app.api.routes.files as files_route


def make_test_pdf(content: str = "test pdf content") -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, content)
    pdf.save()
    return buffer.getvalue()


def make_test_docx(content: str = "test docx content") -> bytes:
    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph(content)
    document.save(buffer)
    return buffer.getvalue()


class RecordingVectorStore:
    def __init__(self):
        self.payload_updates = []
        self.deletions = []

    def update_file_metadata(self, *, project_id, file_id, metadata):
        self.payload_updates.append({
            "project_id": project_id,
            "file_id": file_id,
            "metadata": dict(metadata),
        })

    def delete(self, *, file_id=None, project_id=None, chunk_ids=None):
        self.deletions.append({
            "file_id": file_id,
            "project_id": project_id,
            "chunk_ids": chunk_ids,
        })


class FakeIngestionService:
    def __init__(self):
        self.vector_store = RecordingVectorStore()
        self.calls = []

    def ingest(self, file_id, project_id, file_path, file_type, original_filename, **kwargs):
        self.calls.append({
            "file_id": file_id,
            "project_id": project_id,
            "file_path": file_path,
            "file_type": file_type,
            "original_filename": original_filename,
            **kwargs,
        })
        return IngestionResult(
            file_id=file_id,
            project_id=project_id,
            chunk_count=1,
            vector_count=1,
        )


class FileUploadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ACCESS_TOKEN_SECRET"] = "test-secret-for-file-upload-tests-1234567890"

        self.auth_store = AuthStore(
            Path(self.temp_dir.name) / "auth.sqlite3"
        )
        self.user_repository = SQLiteUserRepository(self.auth_store)
        self.membership_repository = SQLiteProjectMembershipRepository(self.auth_store)

        self.test_user = User(
            username="file-upload-test-user",
            email="file-upload-test@example.com",
            password_hash="unused",
            status=UserStatus.ACTIVE,
            email_verified=True,
        )
        self.user_repository.create(self.test_user)

        self.membership_repository.add(
            ProjectMembership(
                user_id=self.test_user.user_id,
                project_id="project-a",
                role=ProjectRole.MEMBER,
            )
        )
        self.membership_repository.add(
            ProjectMembership(
                user_id=self.test_user.user_id,
                project_id="project-b",
                role=ProjectRole.MEMBER,
            )
        )

        self.access_token = AccessTokenService().create_access_token(
            self.test_user.user_id
        )
        os.environ["ACCESS_TOKEN_SECRET"] = "test-secret-for-file-upload-tests-1234567890"

        self.original_storage = files_route.file_storage
        files_route.file_storage = FileStorage(Path(self.temp_dir.name))

        self.auth_dependency_store_patcher = patch(
            "app.auth.dependencies.AuthStore",
            lambda: AuthStore(Path(self.temp_dir.name) / "auth.sqlite3"),
        )
        self.auth_dependency_store_patcher.start()

        self.fake_ingestion = FakeIngestionService()
        self.ingestion_factory_patcher = patch.object(
            files_route,
            "_create_ingestion_service",
            return_value=self.fake_ingestion,
        )
        self.ingestion_factory_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.auth_dependency_store_patcher.stop()
        self.ingestion_factory_patcher.stop()
        files_route.file_storage = self.original_storage
        self.auth_store.close()
        self.temp_dir.cleanup()

    def test_upload_requires_authentication(self):
        response = self.client.post(
            "/api/files/upload",
            data={"project_id": "project-a"},
            files={"file": ("test.pdf", b"test content")},
        )

        self.assertEqual(response.status_code, 401)

    def test_upload_requires_project_membership(self):
        response = self.upload("project-c", "plans.pdf", make_test_pdf())

        self.assertEqual(response.status_code, 403)

    def upload(self, project_id: str, filename: str, content: bytes):
        return self.client.post(
            "/api/files/upload",
            data={"project_id": project_id},
            files={"file": (filename, content)},
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

    def reingest(self, project_id: str, file_id: str):
        return self.client.post(
            f"/api/files/{file_id}/reingest",
            data={"project_id": project_id},
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

    def metadata(self, project_id: str = "project-a"):
        return json.loads(
            (Path(self.temp_dir.name) / project_id / "metadata.json").read_text(
                encoding="utf-8"
            )
        )

    def test_ingestion_service_includes_page_parser(self) -> None:
        self.ingestion_factory_patcher.stop()

        class FakeEmbeddingProvider:
            dimension = 4

            def __init__(self, *args, **kwargs):
                pass

            def embed_text(self, text):
                return [0.0] * self.dimension

        class FakeVectorStore:
            def __init__(self, *args, **kwargs):
                pass

        with (
            patch.object(files_route, "BGEM3EmbeddingProvider", FakeEmbeddingProvider),
            patch.object(files_route, "QdrantVectorStore", FakeVectorStore),
        ):
            service = files_route._create_ingestion_service()

        self.assertIs(service.parser, files_route.extract_text)
        self.assertIs(service.page_parser, files_route.extract_pages)

    def test_pdf_upload_success(self) -> None:
        content = make_test_pdf()
        response = self.upload("project-a", "plans.pdf", content)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["file_type"], "pdf")
        self.assertEqual(body["size"], len(content))

    def test_docx_upload_success(self) -> None:
        response = self.upload("project-a", "brief.docx", make_test_docx())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["file_type"], "docx")

    def test_first_success_persists_completed_ingestion_and_activates_qdrant(self) -> None:
        response = self.upload("project-a", "plans.pdf", make_test_pdf())

        self.assertEqual(response.status_code, 201)
        body = response.json()
        record = self.metadata()[0]
        self.assertEqual(record["ingestion_status"], "completed")
        self.assertEqual(record["chunk_count"], 1)
        self.assertEqual(record["vector_count"], 1)
        self.assertIsNone(record["ingestion_error"])
        self.assertTrue(record["ingestion_started_at"])
        self.assertTrue(record["ingestion_completed_at"])
        self.assertTrue(record["is_current"])
        self.assertEqual(body["ingestion"]["status"], "completed")
        self.assertEqual(
            self.fake_ingestion.calls[0]["is_current"], False,
        )
        self.assertEqual(
            self.fake_ingestion.vector_store.payload_updates,
            [{
                "project_id": "project-a",
                "file_id": body["file_id"],
                "metadata": {"is_current": True},
            }],
        )

    def test_successful_new_version_activates_new_vector_and_deactivates_old_vector(self) -> None:
        first = self.upload("project-a", "plans.pdf", make_test_pdf("v1"))
        second = self.upload("project-a", "plans.pdf", make_test_pdf("v2"))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        records = self.metadata()
        self.assertFalse(records[0]["is_current"])
        self.assertTrue(records[1]["is_current"])
        self.assertEqual(records[1]["document_version"], 2)
        self.assertEqual(
            self.fake_ingestion.vector_store.payload_updates[-2:],
            [
                {
                    "project_id": "project-a",
                    "file_id": first.json()["file_id"],
                    "metadata": {"is_current": False},
                },
                {
                    "project_id": "project-a",
                    "file_id": second.json()["file_id"],
                    "metadata": {"is_current": True},
                },
            ],
        )

    def test_processing_new_version_does_not_deactivate_old_current(self) -> None:
        first = self.upload("project-a", "plans.pdf", make_test_pdf("v1"))
        observed = {}
        test_case = self

        class InspectingIngestion(FakeIngestionService):
            def ingest(self, *args, **kwargs):
                observed["records"] = test_case.metadata()
                return super().ingest(*args, **kwargs)

        self.ingestion_factory_patcher.stop()
        with patch.object(
                files_route, "_create_ingestion_service", return_value=InspectingIngestion()
        ):
            second = self.upload("project-a", "plans.pdf", make_test_pdf("v2"))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertTrue(observed["records"][0]["is_current"])
        self.assertFalse(observed["records"][1]["is_current"])
        self.assertEqual(observed["records"][1]["ingestion_status"], "processing")

    def test_failed_new_version_keeps_old_current_and_persists_failure(self) -> None:
        first = self.upload("project-a", "plans.pdf", make_test_pdf("v1"))

        class FailingParserIngestion(FakeIngestionService):
            def ingest(self, *args, **kwargs):
                raise TextExtractionError("parser failed")

        self.ingestion_factory_patcher.stop()
        with patch.object(
                files_route,
                "_create_ingestion_service",
                return_value=FailingParserIngestion(),
        ):
            second = self.upload("project-a", "plans.pdf", make_test_pdf("v2"))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 500)
        records = self.metadata()
        self.assertTrue(records[0]["is_current"])
        self.assertEqual(records[0]["ingestion_status"], "completed")
        self.assertFalse(records[1]["is_current"])
        self.assertEqual(records[1]["ingestion_status"], "failed")
        self.assertEqual(records[1]["ingestion_error"]["stage"], "text_extraction")
        self.assertIn("parser failed", records[1]["ingestion_error"]["message"])
        self.assertTrue(records[1]["ingestion_completed_at"])

    def test_embedding_and_vector_failures_persist_failed_state_and_clean_vectors(self) -> None:
        class FailingIngestion(FakeIngestionService):
            def __init__(self, error):
                super().__init__()
                self.error = error

            def ingest(self, *args, **kwargs):
                raise self.error

        self.ingestion_factory_patcher.stop()
        embedding = FailingIngestion(EmbeddingError("embedding failed"))
        with patch.object(files_route, "_create_ingestion_service", return_value=embedding):
            embedding_response = self.upload("project-a", "embedding.pdf", make_test_pdf())
        vector = FailingIngestion(VectorStoreWriteError("partial vector write"))
        with patch.object(files_route, "_create_ingestion_service", return_value=vector):
            vector_response = self.upload("project-a", "vector.pdf", make_test_pdf())

        self.assertEqual(embedding_response.status_code, 500)
        self.assertEqual(vector_response.status_code, 500)
        records = {record["original_filename"]: record for record in self.metadata()}
        self.assertEqual(records["embedding.pdf"]["ingestion_status"], "failed")
        self.assertEqual(records["embedding.pdf"]["ingestion_error"]["stage"], "embedding")
        self.assertEqual(records["vector.pdf"]["ingestion_status"], "failed")
        self.assertEqual(records["vector.pdf"]["ingestion_error"]["stage"], "vector_store")
        self.assertEqual(vector.vector_store.deletions, [{
            "file_id": records["vector.pdf"]["file_id"],
            "project_id": "project-a",
            "chunk_ids": None,
        }])
        self.assertEqual(embedding.vector_store.deletions, [])

    def test_reingest_reuses_failed_file_without_creating_a_new_version(self) -> None:
        class FailingIngestion(FakeIngestionService):
            def ingest(self, *args, **kwargs):
                raise VectorStoreWriteError("qdrant unavailable")

        self.ingestion_factory_patcher.stop()
        with patch.object(
                files_route, "_create_ingestion_service", return_value=FailingIngestion()
        ):
            failed = self.upload("project-a", "plans.pdf", make_test_pdf())
        failed_record = self.metadata()[0]
        retry_service = FakeIngestionService()
        with patch.object(
                files_route, "_create_ingestion_service", return_value=retry_service
        ):
            retried = self.reingest("project-a", failed_record["file_id"])

        self.assertEqual(failed.status_code, 500)
        self.assertEqual(retried.status_code, 200)
        records = self.metadata()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["file_id"], failed_record["file_id"])
        self.assertEqual(records[0]["document_version"], failed_record["document_version"])
        self.assertEqual(records[0]["ingestion_status"], "completed")
        self.assertTrue(records[0]["is_current"])
        self.assertEqual(retry_service.calls[0]["file_id"], failed_record["file_id"])
        self.assertEqual(len(list((Path(self.temp_dir.name) / "project-a").glob("*.pdf"))), 1)

    def test_reingest_requires_authentication_and_project_membership(self) -> None:
        failed_record = {
            "file_id": "failed-file",
            "project_id": "project-a",
            "original_filename": "plans.pdf",
            "stored_filename": "failed-file.pdf",
            "file_type": "pdf",
            "size": 1,
            "uploaded_at": "2026-09-01T00:00:00+00:00",
            "document_version": 1,
            "is_current": False,
            "is_duplicate": False,
            "duplicate_of_file_id": None,
            "ingestion_status": "failed",
            "chunk_count": None,
            "vector_count": None,
            "ingestion_error": {"stage": "embedding", "message": "failed"},
            "ingestion_started_at": "2026-09-01T00:00:00+00:00",
            "ingestion_completed_at": "2026-09-01T00:00:01+00:00",
        }
        project_dir = Path(self.temp_dir.name) / "project-a"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "metadata.json").write_text(json.dumps([failed_record]), encoding="utf-8")

        unauthenticated = self.client.post(
            "/api/files/failed-file/reingest", data={"project_id": "project-a"}
        )
        unauthorized = self.reingest("project-c", "failed-file")

        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(unauthorized.status_code, 403)

    def test_reingest_failure_keeps_existing_current_version(self) -> None:
        first = self.upload("project-a", "plans.pdf", make_test_pdf("v1"))

        class FailingIngestion(FakeIngestionService):
            def ingest(self, *args, **kwargs):
                raise VectorStoreWriteError("qdrant unavailable")

        self.ingestion_factory_patcher.stop()
        failed_service = FailingIngestion()
        with patch.object(files_route, "_create_ingestion_service", return_value=failed_service):
            second = self.upload("project-a", "plans.pdf", make_test_pdf("v2"))
        failed_record = self.metadata()[1]
        with patch.object(files_route, "_create_ingestion_service", return_value=FailingIngestion()):
            retried = self.reingest("project-a", failed_record["file_id"])

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 500)
        self.assertEqual(retried.status_code, 500)
        records = self.metadata()
        self.assertTrue(records[0]["is_current"])
        self.assertFalse(records[1]["is_current"])
        self.assertEqual(records[1]["ingestion_status"], "failed")

    def test_legacy_metadata_is_not_migrated_when_new_schema_record_is_written(self) -> None:
        project_dir = Path(self.temp_dir.name) / "project-a"
        project_dir.mkdir(parents=True, exist_ok=True)
        legacy = {
            "file_id": "legacy-file",
            "project_id": "project-a",
            "original_filename": "legacy.pdf",
            "stored_filename": "legacy-file.pdf",
            "file_type": "pdf",
            "size": 123,
            "uploaded_at": "2026-09-01T00:00:00+00:00",
        }
        (project_dir / "metadata.json").write_text(json.dumps([legacy]), encoding="utf-8")

        response = self.upload("project-a", "new.pdf", make_test_pdf())

        self.assertEqual(response.status_code, 201)
        records = self.metadata()
        self.assertEqual(records[0], legacy)
        self.assertEqual(records[1]["ingestion_status"], "completed")
        self.assertIn("document_version", records[1])
        self.assertIn("is_current", records[1])

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        legacy_response = next(
            item for item in response.json()["files"] if item["file_id"] == "legacy-file"
        )
        self.assertIsNone(legacy_response["document_version"])
        self.assertIsNone(legacy_response["is_current"])

    def test_unsupported_file_is_rejected(self) -> None:
        response = self.upload("project-a", "notes.txt", b"text")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only .pdf and .docx", response.json()["detail"])

    def test_project_id_isolation_and_metadata(self) -> None:
        response = self.upload("project-a", "plans.pdf", make_test_pdf("project isolation"))
        self.assertEqual(response.status_code, 201)
        body = response.json()
        project_dir = Path(self.temp_dir.name) / "project-a"
        self.assertTrue((project_dir / body["stored_filename"]).exists())
        self.assertFalse((Path(self.temp_dir.name) / "project-b" / body["stored_filename"]).exists())
        metadata = json.loads((project_dir / "metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(metadata[0]["file_id"], body["file_id"])
        self.assertEqual(metadata[0]["project_id"], body["project_id"])
        self.assertEqual(metadata[0]["original_filename"], body["original_filename"])
        self.assertEqual(metadata[0]["stored_filename"], body["stored_filename"])
        self.assertEqual(metadata[0]["file_type"], body["file_type"])
        self.assertEqual(metadata[0]["size"], body["size"])
        self.assertEqual(metadata[0]["uploaded_at"], body["uploaded_at"])

        self.assertEqual(body["project_id"], "project-a")
        self.assertEqual(body["original_filename"], "plans.pdf")
        self.assertTrue(body["uploaded_at"])

    def test_same_name_does_not_overwrite(self) -> None:
        first_content = make_test_pdf("first")
        second_content = make_test_pdf("second")

        first = self.upload("project-a", "plans.pdf", first_content)
        second = self.upload("project-a", "plans.pdf", second_content)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        first_body, second_body = first.json(), second.json()
        self.assertNotEqual(first_body["file_id"], second_body["file_id"])
        self.assertNotEqual(first_body["stored_filename"], second_body["stored_filename"])
        project_dir = Path(self.temp_dir.name) / "project-a"
        self.assertEqual(
            (project_dir / first_body["stored_filename"]).read_bytes(),
            first_content,
        )
        self.assertEqual(
            (project_dir / second_body["stored_filename"]).read_bytes(),
            second_content,
        )

    def test_same_name_versions_are_incremented_and_previous_is_not_current(self) -> None:
        first = self.upload("project-a", "plans.pdf", make_test_pdf("first"))
        second = self.upload("project-a", "plans.pdf", make_test_pdf("second"))
        third = self.upload("project-a", "plans.pdf", make_test_pdf("third"))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(third.status_code, 201)
        self.assertEqual(first.json()["document_version"], 1)
        self.assertEqual(second.json()["document_version"], 2)
        self.assertEqual(third.json()["document_version"], 3)
        self.assertTrue(third.json()["is_current"])

        records = json.loads(
            (Path(self.temp_dir.name) / "project-a" / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([record["document_version"] for record in records], [1, 2, 3])
        self.assertEqual([record["is_current"] for record in records], [False, False, True])

    def test_duplicate_metadata_does_not_consume_business_version(self) -> None:
        project_dir = Path(self.temp_dir.name) / "project-a"
        project_dir.mkdir(parents=True, exist_ok=True)
        first = {
            "file_id": "original",
            "project_id": "project-a",
            "original_filename": "plans.pdf",
            "stored_filename": "original.pdf",
            "document_version": 1,
            "is_current": False,
            "is_duplicate": False,
            "uploaded_at": "2026-09-01T00:00:00+00:00",
        }
        duplicate = {
            "file_id": "duplicate",
            "project_id": "project-a",
            "original_filename": "plans.pdf",
            "stored_filename": "duplicate.pdf",
            "document_version": None,
            "is_current": False,
            "is_duplicate": True,
            "duplicate_of_file_id": "original",
            "uploaded_at": "2026-09-02T00:00:00+00:00",
        }
        (project_dir / "metadata.json").write_text(
            json.dumps([first, duplicate]), encoding="utf-8"
        )
        response = self.upload("project-a", "plans.pdf", make_test_pdf("third"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["document_version"], 2)
        records = json.loads((project_dir / "metadata.json").read_text(encoding="utf-8"))
        by_id = {record["file_id"]: record for record in records}
        self.assertEqual(by_id["duplicate"]["document_version"], None)
        self.assertTrue(by_id["duplicate"]["is_duplicate"])

    def test_different_names_and_projects_have_independent_versions(self) -> None:
        first = self.upload("project-a", "plans.pdf", make_test_pdf("a"))
        other_name = self.upload("project-a", "brief.pdf", make_test_pdf("b"))
        other_project = self.upload("project-b", "plans.pdf", make_test_pdf("c"))

        self.assertEqual(first.json()["document_version"], 1)
        self.assertEqual(other_name.json()["document_version"], 1)
        self.assertEqual(other_project.json()["document_version"], 1)
        self.assertTrue(first.json()["is_current"])
        self.assertTrue(other_name.json()["is_current"])
        self.assertTrue(other_project.json()["is_current"])

    def test_upload_passes_version_metadata_to_ingestion(self) -> None:
        captured = {}

        class CapturingIngestionService(FakeIngestionService):
            def ingest(self, *args, **kwargs):
                captured.update(kwargs)
                return super().ingest(*args, **kwargs)

        self.ingestion_factory_patcher.stop()
        with patch.object(
                files_route,
                "_create_ingestion_service",
                return_value=CapturingIngestionService(),
        ):
            response = self.upload("project-a", "plans.pdf", make_test_pdf())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(captured["document_version"], 1)
        self.assertFalse(captured["is_current"])
        self.assertEqual(captured["uploaded_at"], response.json()["uploaded_at"])

    def test_empty_project_or_file_is_rejected(self) -> None:
        self.assertEqual(self.upload("", "plans.pdf", b"abc").status_code, 422)
        self.assertEqual(self.upload("project-a", "plans.pdf", b"").status_code, 400)

    def test_list_files_requires_authentication(self):
        response = self.client.get("/api/files?project_id=project-a")
        self.assertEqual(response.status_code, 401)

    def test_list_files_requires_project_membership(self):
        response = self.client.get(
            "/api/files?project_id=project-c",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_list_files_returns_uploaded_files(self):
        self.upload("project-a", "plans.pdf", make_test_pdf())
        self.upload("project-a", "brief.docx", make_test_docx())

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project_id"], "project-a")
        self.assertEqual(len(body["files"]), 2)

    def test_list_files_returns_correct_fields(self):
        upload_response = self.upload("project-a", "plans.pdf", make_test_pdf())
        upload_body = upload_response.json()

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        file_record = body["files"][0]

        self.assertEqual(file_record["file_id"], upload_body["file_id"])
        self.assertEqual(file_record["original_filename"], upload_body["original_filename"])
        self.assertEqual(file_record["file_type"], upload_body["file_type"])
        self.assertEqual(file_record["size"], upload_body["size"])
        self.assertEqual(file_record["uploaded_at"], upload_body["uploaded_at"])
        self.assertEqual(file_record["document_version"], upload_body["document_version"])
        self.assertEqual(file_record["is_current"], upload_body["is_current"])

        self.assertNotIn("stored_filename", file_record)
        self.assertNotIn("storage_root", file_record)

    def test_list_files_empty_project_returns_empty_list(self):
        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project_id"], "project-a")
        self.assertEqual(body["files"], [])

    def test_list_files_user_cannot_access_other_user_project(self):
        other_user = User(
            username="other-user",
            email="other@example.com",
            password_hash="unused",
            status=UserStatus.ACTIVE,
            email_verified=True,
        )
        self.user_repository.create(other_user)

        self.membership_repository.add(
            ProjectMembership(
                user_id=other_user.user_id,
                project_id="project-other",
                role=ProjectRole.MEMBER,
            )
        )

        response = self.client.get(
            "/api/files?project_id=project-other",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 403)

    def test_list_files_only_returns_target_project_files(self):
        self.upload("project-a", "a.pdf", make_test_pdf("a"))
        self.upload("project-b", "b.pdf", make_test_pdf("b"))

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["files"]), 1)
        self.assertEqual(body["files"][0]["original_filename"], "a.pdf")

    def test_list_files_sorted_by_uploaded_at_desc(self):
        import time

        self.upload("project-a", "first.pdf", make_test_pdf("1"))
        time.sleep(0.01)
        self.upload("project-a", "second.pdf", make_test_pdf("2"))
        time.sleep(0.01)
        self.upload("project-a", "third.pdf", make_test_pdf("3"))

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        filenames = [f["original_filename"] for f in body["files"]]
        self.assertEqual(filenames, ["third.pdf", "second.pdf", "first.pdf"])

    def test_list_files_does_not_modify_metadata(self):
        self.upload("project-a", "plans.pdf", make_test_pdf())

        project_dir = Path(self.temp_dir.name) / "project-a"
        metadata_before = (project_dir / "metadata.json").read_text(encoding="utf-8")

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)

        metadata_after = (project_dir / "metadata.json").read_text(encoding="utf-8")
        self.assertEqual(metadata_before, metadata_after)

    def test_list_files_corrupted_metadata_returns_500(self):
        project_dir = Path(self.temp_dir.name) / "project-a"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "metadata.json").write_text("invalid json {", encoding="utf-8")

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("项目文件列表数据格式异常", response.json()["detail"])

    def test_list_files_non_list_metadata_returns_500(self):
        project_dir = Path(self.temp_dir.name) / "project-a"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "metadata.json").write_text(
            json.dumps({"files": []}), encoding="utf-8"
        )

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("项目文件列表数据格式异常", response.json()["detail"])

    def test_list_files_non_object_metadata_record_returns_500(self):
        project_dir = Path(self.temp_dir.name) / "project-a"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "metadata.json").write_text(
            json.dumps([{"project_id": "project-a"}, "invalid record"]),
            encoding="utf-8",
        )

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("项目文件列表数据格式异常", response.json()["detail"])

    def test_list_files_filters_records_for_other_projects(self):
        self.upload("project-a", "plans.pdf", make_test_pdf())
        metadata_path = Path(self.temp_dir.name) / "project-a" / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        other_project_record = {**metadata[0], "file_id": "project-b-file", "project_id": "project-b"}
        metadata_path.write_text(json.dumps([metadata[0], other_project_record]), encoding="utf-8")

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["file_id"] for item in response.json()["files"]], [metadata[0]["file_id"]])

    def test_list_files_missing_uploaded_at_does_not_fail(self):
        project_dir = Path(self.temp_dir.name) / "project-a"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "metadata.json").write_text(
            json.dumps([{"file_id": "missing-time", "project_id": "project-a"}]),
            encoding="utf-8",
        )

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["files"][0]["file_id"], "missing-time")

    def test_list_files_invalid_uploaded_at_does_not_fail(self):
        project_dir = Path(self.temp_dir.name) / "project-a"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "metadata.json").write_text(
            json.dumps([{
                "file_id": "invalid-time",
                "project_id": "project-a",
                "uploaded_at": "not-a-timestamp",
            }]),
            encoding="utf-8",
        )

        response = self.client.get(
            "/api/files?project_id=project-a",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["files"][0]["file_id"], "invalid-time")

    def test_list_files_normalizes_project_id(self):
        self.upload("project-a", "plans.pdf", make_test_pdf())

        response = self.client.get(
            "/api/files",
            params={"project_id": " project-a "},
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project_id"], "project-a")
        self.assertEqual(len(response.json()["files"]), 1)

    def test_list_files_rejects_path_traversal(self):
        test_cases = [
            ".",
            "..",
            "../other",
            "project/../etc",
            "project/../../etc",
            "project/./file",
        ]

        for malicious_id in test_cases:
            response = self.client.get(
                f"/api/files?project_id={malicious_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            self.assertIn(response.status_code, [400, 403],
                         f"Expected 400 or 403 for project_id={malicious_id}, got {response.status_code}")


if __name__ == "__main__":
    unittest.main()
