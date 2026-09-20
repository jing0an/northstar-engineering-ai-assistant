from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.auth.dependencies as dependencies
from app.auth.models import (
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectStatus,
    User,
    UserStatus,
)
from app.auth.password import PBKDF2PasswordHasher
from app.auth.persistence import (
    SQLiteProjectMembershipRepository,
    SQLiteProjectRepository,
    SQLiteUserRepository,
)
from app.auth.store import AuthStore
from app.auth.token import AccessTokenService
from app.main import app

SECRET = "northstar-project-test-secret-" + "x" * 32
PASSWORD = "correct-password-123"
PROJECT_ID = "BJ-KC-2024-01"


def _make_user(
        *,
        username: str = "project-user",
        email: str = "project@example.com",
) -> User:
    now = datetime.now(timezone.utc)
    return User(
        user_id=uuid4(),
        username=username,
        email=email,
        password_hash=PBKDF2PasswordHasher().hash(PASSWORD),
        email_verified=True,
        status=UserStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def _patch_auth_store(monkeypatch, tmp_path):
    database_path = tmp_path / "auth.sqlite3"
    original_store = dependencies.AuthStore

    def make_store():
        return original_store(database_path)

    # get_current_user, check_project_access, and the project routes all
    # resolve AuthStore through the dependencies module, so one patch keeps
    # every request in this test isolated from the real database.
    monkeypatch.setattr(dependencies, "AuthStore", make_store)
    return database_path


def _create_user(database_path, user: User) -> None:
    store = AuthStore(database_path)
    try:
        SQLiteUserRepository(store).create(user)
    finally:
        store.close()


def _create_project(
        database_path,
        *,
        project_id: str,
        name: str,
        owner_user_id,
) -> Project:
    now = datetime.now(timezone.utc)
    project = Project(
        project_id=project_id,
        name=name,
        status=ProjectStatus.ACTIVE,
        owner_user_id=owner_user_id,
        created_at=now,
        updated_at=now,
    )
    store = AuthStore(database_path)
    try:
        SQLiteProjectRepository(store).create_with_owner(
            project,
            ProjectMembership(
                user_id=owner_user_id,
                project_id=project_id,
                role=ProjectRole.OWNER,
                created_at=now,
            ),
        )
    finally:
        store.close()
    return project


def _create_membership(database_path, user: User, project_id: str) -> None:
    store = AuthStore(database_path)
    try:
        SQLiteProjectMembershipRepository(store).add(
            ProjectMembership(
                user_id=user.user_id,
                project_id=project_id,
                role=ProjectRole.MEMBER,
            )
        )
    finally:
        store.close()


def _token(user: User) -> str:
    return AccessTokenService(secret=SECRET).create_access_token(user.user_id)


def _client() -> TestClient:
    return TestClient(app)


def test_project_list_without_authorization_is_401(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    response = _client().get("/api/projects")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_project_create_without_authorization_is_401(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    response = _client().post("/api/projects", json={"name": "测试项目"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_project_without_authorization_is_401(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    response = _client().get(f"/api/projects/{PROJECT_ID}")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_project_with_invalid_jwt_is_401(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    response = _client().get(
        f"/api/projects/{PROJECT_ID}",
        headers={"Authorization": "Bearer this-is-not-a-valid-token"},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_create_project_creates_real_project_and_owner_membership(
        monkeypatch,
        tmp_path,
):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    database_path = _patch_auth_store(monkeypatch, tmp_path)
    user = _make_user()
    _create_user(database_path, user)

    response = _client().post(
        "/api/projects",
        json={"name": "测试项目"},
        headers={"Authorization": f"Bearer {_token(user)}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"]
    assert body["name"] == "测试项目"
    assert body["status"] == "active"
    assert body["owner_user_id"] == str(user.user_id)
    assert body["created_at"]
    assert body["updated_at"]
    assert "placeholder" not in body.values()

    store = AuthStore(database_path)
    try:
        project = SQLiteProjectRepository(store).get_by_id(body["project_id"])
        memberships = SQLiteProjectMembershipRepository(store).list_for_user(
            user.user_id
        )
    finally:
        store.close()

    assert project is not None
    assert project.name == "测试项目"
    assert any(
        membership.project_id == project.project_id
        and membership.role is ProjectRole.OWNER
        for membership in memberships
    )


def test_created_project_is_visible_in_project_list(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    database_path = _patch_auth_store(monkeypatch, tmp_path)
    user = _make_user()
    _create_user(database_path, user)
    created = _client().post(
        "/api/projects",
        json={"name": "列表项目"},
        headers={"Authorization": f"Bearer {_token(user)}"},
    )
    assert created.status_code == 201

    response = _client().get(
        "/api/projects",
        headers={"Authorization": f"Bearer {_token(user)}"},
    )

    assert response.status_code == 200
    assert [item["project_id"] for item in response.json()] == [
        created.json()["project_id"]
    ]


def test_project_list_isolated_between_users(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    database_path = _patch_auth_store(monkeypatch, tmp_path)
    user_a = _make_user(username="user-a", email="a@example.com")
    user_b = _make_user(username="user-b", email="b@example.com")
    _create_user(database_path, user_a)
    _create_user(database_path, user_b)
    project_a = _create_project(
        database_path,
        project_id="project-a",
        name="项目 A",
        owner_user_id=user_a.user_id,
    )
    project_b = _create_project(
        database_path,
        project_id="project-b",
        name="项目 B",
        owner_user_id=user_b.user_id,
    )

    response_a = _client().get(
        "/api/projects",
        headers={"Authorization": f"Bearer {_token(user_a)}"},
    )
    response_b = _client().get(
        "/api/projects",
        headers={"Authorization": f"Bearer {_token(user_b)}"},
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert [item["project_id"] for item in response_a.json()] == [project_a.project_id]
    assert [item["project_id"] for item in response_b.json()] == [project_b.project_id]


def test_project_without_membership_is_403(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    database_path = _patch_auth_store(monkeypatch, tmp_path)
    user = _make_user()
    _create_user(database_path, user)
    _create_project(
        database_path,
        project_id=PROJECT_ID,
        name="真实项目",
        owner_user_id=user.user_id,
    )

    # Remove the owner's membership to exercise the access-denied path while
    # keeping the Project row present.
    store = AuthStore(database_path)
    try:
        store._connection.execute("DELETE FROM project_memberships")
        store._connection.commit()
    finally:
        store.close()

    response = _client().get(
        f"/api/projects/{PROJECT_ID}",
        headers={"Authorization": f"Bearer {_token(user)}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Project access denied"


def test_membership_without_project_is_404(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    database_path = _patch_auth_store(monkeypatch, tmp_path)
    user = _make_user()
    _create_user(database_path, user)
    _create_membership(database_path, user, PROJECT_ID)

    response = _client().get(
        f"/api/projects/{PROJECT_ID}",
        headers={"Authorization": f"Bearer {_token(user)}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_project_with_membership_returns_real_project(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    database_path = _patch_auth_store(monkeypatch, tmp_path)
    user = _make_user()
    _create_user(database_path, user)
    project = _create_project(
        database_path,
        project_id=PROJECT_ID,
        name="滨江科创中心",
        owner_user_id=user.user_id,
    )

    response = _client().get(
        f"/api/projects/{PROJECT_ID}",
        headers={"Authorization": f"Bearer {_token(user)}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project.project_id
    assert body["name"] == project.name
    assert body["status"] == "active"
    assert body["owner_user_id"] == str(user.user_id)
    assert "placeholder" not in body.values()


def test_project_access_isolated_between_users(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    database_path = _patch_auth_store(monkeypatch, tmp_path)
    owner = _make_user(username="owner", email="owner@example.com")
    other = _make_user(username="other", email="other@example.com")
    _create_user(database_path, owner)
    _create_user(database_path, other)
    _create_project(
        database_path,
        project_id=PROJECT_ID,
        name="隔离项目",
        owner_user_id=owner.user_id,
    )

    response = _client().get(
        f"/api/projects/{PROJECT_ID}",
        headers={"Authorization": f"Bearer {_token(other)}"},
    )

    assert response.status_code == 403


def test_orphan_historical_membership_does_not_break_store_initialization(tmp_path):
    database_path = tmp_path / "auth.sqlite3"
    store = AuthStore(database_path)
    try:
        user = _make_user()
        SQLiteUserRepository(store).create(user)
        SQLiteProjectMembershipRepository(store).add(
            ProjectMembership(
                user_id=user.user_id,
                project_id="legacy-project",
                role=ProjectRole.MEMBER,
            )
        )
    finally:
        store.close()

    reopened = AuthStore(database_path)
    try:
        rows = reopened._connection.execute(
            "SELECT project_id FROM project_memberships"
        ).fetchall()
        assert [row["project_id"] for row in rows] == ["legacy-project"]
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 201},
    ],
)
def test_create_project_validates_name(monkeypatch, tmp_path, payload):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    database_path = _patch_auth_store(monkeypatch, tmp_path)
    user = _make_user()
    _create_user(database_path, user)

    response = _client().post(
        "/api/projects",
        json=payload,
        headers={"Authorization": f"Bearer {_token(user)}"},
    )

    assert response.status_code == 422
