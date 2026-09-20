import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.api.routes.files as files_route
from app.auth.models import ProjectMembership, ProjectRole, User, UserStatus
from app.auth.persistence import (
    SQLiteProjectMembershipRepository,
    SQLiteUserRepository,
)
from app.auth.store import AuthStore
from app.auth.token import AccessTokenService
from app.main import app
from app.services.file_storage import FileStorage


PDF_BYTES = b"%PDF-1.4\n% Northstar preview test\n%%EOF\n"


class FileContentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.temp_dir.name) / "storage"
        self.auth_db = Path(self.temp_dir.name) / "auth.sqlite3"
        os.environ["ACCESS_TOKEN_SECRET"] = (
            "test-secret-for-file-content-tests-1234567890"
        )

        self.auth_store = AuthStore(self.auth_db)
        self.user_repository = SQLiteUserRepository(self.auth_store)
        self.membership_repository = SQLiteProjectMembershipRepository(
            self.auth_store
        )
        self.test_user = User(
            username="file-content-test-user",
            email="file-content-test@example.com",
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

        self.original_storage = files_route.file_storage
        files_route.file_storage = FileStorage(self.storage_root)
        self.auth_store_patcher = patch(
            "app.auth.dependencies.AuthStore", lambda: AuthStore(self.auth_db)
        )
        self.auth_store_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.auth_store_patcher.stop()
        files_route.file_storage = self.original_storage
        self.auth_store.close()
        self.temp_dir.cleanup()

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def add_file(
        self,
        project_id: str,
        file_id: str = "owned-pdf",
        *,
        stored_filename: str = "owned-pdf.pdf",
        create_file: bool = True,
    ) -> None:
        project_dir = self.storage_root / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        metadata = [{
            "file_id": file_id,
            "project_id": project_id,
            "original_filename": "工程管理22-4 张静 20220102128.pdf",
            "stored_filename": stored_filename,
            "file_type": "pdf",
            "document_version": 4,
            "is_current": True,
        }]
        (project_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        if create_file and Path(stored_filename).name == stored_filename:
            (project_dir / stored_filename).write_bytes(PDF_BYTES)

    def get_content(self, project_id: str, file_id: str = "owned-pdf"):
        return self.client.get(
            f"/api/files/{file_id}/content",
            params={"project_id": project_id},
            headers=self.headers,
        )

    def test_owner_can_preview_pdf_inline(self) -> None:
        self.add_file("project-a")

        response = self.get_content("project-a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PDF_BYTES)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(
            response.headers["content-disposition"].lower().startswith("inline")
        )

    def test_preview_requires_authentication(self) -> None:
        self.add_file("project-a")

        response = self.client.get(
            "/api/files/owned-pdf/content", params={"project_id": "project-a"}
        )

        self.assertEqual(response.status_code, 401)

    def test_preview_requires_project_membership(self) -> None:
        self.add_file("project-c")

        response = self.get_content("project-c")

        self.assertEqual(response.status_code, 403)

    def test_file_from_another_project_is_not_exposed(self) -> None:
        self.add_file("project-b", file_id="project-b-pdf")

        response = self.get_content("project-a", "project-b-pdf")

        self.assertEqual(response.status_code, 404)

    def test_missing_stored_file_returns_404(self) -> None:
        self.add_file("project-a", create_file=False)

        response = self.get_content("project-a")

        self.assertEqual(response.status_code, 404)

    def test_metadata_path_traversal_is_rejected(self) -> None:
        (self.storage_root / "outside.pdf").parent.mkdir(parents=True, exist_ok=True)
        (self.storage_root / "outside.pdf").write_bytes(PDF_BYTES)
        self.add_file(
            "project-a", stored_filename="../outside.pdf", create_file=False
        )

        response = self.get_content("project-a")

        self.assertEqual(response.status_code, 404)

    def test_project_id_path_traversal_is_rejected(self) -> None:
        response = self.get_content("../project-a")

        self.assertIn(response.status_code, {400, 403})


if __name__ == "__main__":
    unittest.main()
