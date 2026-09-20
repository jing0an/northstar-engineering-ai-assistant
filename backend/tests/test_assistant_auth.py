from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.auth import dependencies
from app.auth.models import ProjectMembership, ProjectRole, User, UserStatus
from app.auth.password import PBKDF2PasswordHasher
from app.auth.persistence import SQLiteProjectMembershipRepository, SQLiteUserRepository
from app.auth.store import AuthStore
from app.auth.token import AccessTokenService
from app.main import app

SECRET = "northstar-assistant-test-secret-" + "x" * 32
CONVERSATION_ID = "12345678-1234-4234-8234-123456789abc"


def _assistant_payload(**overrides):
    payload = {
        "message": "hello",
        "project_id": "project-a",
        "conversation_id": CONVERSATION_ID,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def assistant_context(monkeypatch, tmp_path):
    db_path = tmp_path / "auth.sqlite3"
    original_store = dependencies.AuthStore

    def make_store():
        return original_store(db_path)

    monkeypatch.setattr(dependencies, "AuthStore", make_store)
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    user = User(
        user_id=uuid4(),
        username="assistant-user",
        email="assistant@example.com",
        password_hash=PBKDF2PasswordHasher().hash("password"),
        email_verified=True,
        status=UserStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    store = AuthStore(db_path)
    SQLiteUserRepository(store).create(user)
    store.close()
    return TestClient(app), db_path, user


def _token(user: User) -> str:
    return AccessTokenService(secret=SECRET).create_access_token(user.user_id)


def _add_membership(db_path, user: User, project_id: str) -> None:
    store = AuthStore(db_path)
    try:
        SQLiteProjectMembershipRepository(store).add(
            ProjectMembership(
                membership_id=uuid4(),
                user_id=user.user_id,
                project_id=project_id,
                role=ProjectRole.MEMBER,
                created_at=datetime.now(timezone.utc),
            )
        )
    finally:
        store.close()


def test_assistant_requires_authorization(assistant_context):
    client, _, _ = assistant_context
    with patch("app.main.process_message") as process:
        response = client.post("/api/assistant", json=_assistant_payload())
    assert response.status_code == 401
    process.assert_not_called()


def test_assistant_rejects_invalid_jwt(assistant_context):
    client, _, _ = assistant_context
    with patch("app.main.process_message") as process:
        response = client.post(
            "/api/assistant",
            json=_assistant_payload(),
            headers={"Authorization": "Bearer invalid-token"},
        )
    assert response.status_code == 401
    process.assert_not_called()


def test_assistant_rejects_non_member(assistant_context):
    client, _, user = assistant_context
    with patch("app.main.process_message") as process:
        response = client.post(
            "/api/assistant",
            json=_assistant_payload(),
            headers={"Authorization": f"Bearer {_token(user)}"},
        )
    assert response.status_code == 403
    process.assert_not_called()


def test_assistant_allows_member_and_calls_agent(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")
    with patch("app.main.process_message", return_value={"reply": "ok"}) as process:
        response = client.post(
            "/api/assistant",
            json=_assistant_payload(),
            headers={"Authorization": f"Bearer {_token(user)}"},
        )
    assert response.status_code == 200
    assert response.json() == {"reply": "ok"}
    process.assert_called_once_with(
        "hello",
        "project-a",
        user_id=str(user.user_id),
        conversation_id=CONVERSATION_ID,
    )


def test_assistant_rejects_client_supplied_user_id(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")
    with patch("app.main.process_message") as process:
        response = client.post(
            "/api/assistant",
            json=_assistant_payload(user_id="forged-user"),
            headers={"Authorization": f"Bearer {_token(user)}"},
        )

    assert response.status_code == 422
    process.assert_not_called()


def test_assistant_enforces_project_isolation(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")
    with patch("app.main.process_message") as process:
        response = client.post(
            "/api/assistant",
            json=_assistant_payload(project_id="project-b"),
            headers={"Authorization": f"Bearer {_token(user)}"},
        )
    assert response.status_code == 403
    process.assert_not_called()


def test_assistant_rejects_empty_message(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")

    response = client.post(
        "/api/assistant",
        headers={"Authorization": f"Bearer {_token(user)}"},
        json=_assistant_payload(message=""),
    )

    assert response.status_code == 422


def test_assistant_rejects_whitespace_message(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")

    response = client.post(
        "/api/assistant",
        headers={"Authorization": f"Bearer {_token(user)}"},
        json=_assistant_payload(message="   "),
    )

    assert response.status_code == 422


def test_assistant_rejects_empty_project_id(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")

    response = client.post(
        "/api/assistant",
        headers={"Authorization": f"Bearer {_token(user)}"},
        json=_assistant_payload(project_id=""),
    )

    assert response.status_code == 422


def test_assistant_rejects_whitespace_project_id(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")

    response = client.post(
        "/api/assistant",
        headers={"Authorization": f"Bearer {_token(user)}"},
        json=_assistant_payload(project_id="   "),
    )

    assert response.status_code == 422


def test_assistant_rejects_overlong_message(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")

    response = client.post(
        "/api/assistant",
        headers={"Authorization": f"Bearer {_token(user)}"},
        json=_assistant_payload(message="a" * 10001),
    )

    assert response.status_code == 422


def test_assistant_rejects_overlong_project_id(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")

    response = client.post(
        "/api/assistant",
        headers={"Authorization": f"Bearer {_token(user)}"},
        json=_assistant_payload(project_id="a" * 201),
    )

    assert response.status_code == 422


def test_assistant_returns_safe_500_on_unexpected_agent_error(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")

    with patch(
            "app.main.process_message",
            side_effect=RuntimeError("internal failure: secret path"),
    ) as process:
        response = client.post(
            "/api/assistant",
            headers={"Authorization": f"Bearer {_token(user)}"},
            json=_assistant_payload(),
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "助理服务发生内部错误，请稍后重试。",
        }
    }
    assert "internal failure" not in response.text
    assert "secret path" not in response.text
    process.assert_called_once_with(
        "hello",
        "project-a",
        user_id=str(user.user_id),
        conversation_id=CONVERSATION_ID,
    )


def test_assistant_preserves_http_exception(assistant_context):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")

    with patch(
            "app.main.process_message",
            side_effect=HTTPException(
                status_code=418,
                detail="test http error",
            ),
    ) as process:
        response = client.post(
            "/api/assistant",
            headers={"Authorization": f"Bearer {_token(user)}"},
            json=_assistant_payload(),
        )

    assert response.status_code == 418
    assert response.json() == {"detail": "test http error"}
    process.assert_called_once_with(
        "hello",
        "project-a",
        user_id=str(user.user_id),
        conversation_id=CONVERSATION_ID,
    )


@pytest.mark.parametrize(
    "conversation_id",
    [None, "", "not-a-uuid", "../project-a", "a" * 201],
)
def test_assistant_rejects_missing_or_invalid_conversation_id(
        assistant_context,
        conversation_id,
):
    client, db_path, user = assistant_context
    _add_membership(db_path, user, "project-a")
    payload = _assistant_payload(conversation_id=conversation_id)
    if conversation_id is None:
        payload.pop("conversation_id")

    with patch("app.main.process_message") as process:
        response = client.post(
            "/api/assistant",
            headers={"Authorization": f"Bearer {_token(user)}"},
            json=payload,
        )

    assert response.status_code == 422
    process.assert_not_called()
