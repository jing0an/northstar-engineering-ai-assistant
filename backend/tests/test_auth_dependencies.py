from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import dependencies
from app.auth.models import ProjectMembership, User, UserStatus
from app.auth.password import PBKDF2PasswordHasher
from app.auth.store import AuthStore
from app.auth.token import AccessTokenService

SECRET = "northstar-test-secret-" + "x" * 32
PASSWORD = "correct-password-123"


def _make_user(
        *,
        status: UserStatus = UserStatus.ACTIVE,
        email_verified: bool = True,
) -> User:
    now = datetime.now(timezone.utc)
    password_hash = PBKDF2PasswordHasher().hash(PASSWORD)

    return User(
        user_id=uuid4(),
        username="test-user",
        email="test@example.com",
        password_hash=password_hash,
        email_verified=email_verified,
        status=status,
        created_at=now,
        updated_at=now,
    )


def _credentials(token: str, scheme: str = "Bearer"):
    return HTTPAuthorizationCredentials(
        scheme=scheme,
        credentials=token,
    )


def _patch_auth_store(monkeypatch, tmp_path):
    database_path = tmp_path / "auth.sqlite3"

    original_store = dependencies.AuthStore

    def make_store():
        return original_store(database_path)

    monkeypatch.setattr(dependencies, "AuthStore", make_store)
    return database_path


def _create_token(user_id):
    return AccessTokenService(secret=SECRET).create_access_token(user_id)


def _assert_unauthorized(call):
    with pytest.raises(HTTPException) as error:
        call()

    assert error.value.status_code == 401
    assert error.value.headers["WWW-Authenticate"] == "Bearer"


def test_missing_authorization_is_401():
    _assert_unauthorized(lambda: dependencies.get_current_user(None))


def test_non_bearer_authorization_is_401():
    credentials = HTTPAuthorizationCredentials(
        scheme="Basic",
        credentials="not-a-jwt",
    )

    _assert_unauthorized(
        lambda: dependencies.get_current_user(credentials)
    )


def test_invalid_jwt_is_401(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)

    credentials = _credentials("this-is-not-a-jwt")

    _assert_unauthorized(
        lambda: dependencies.get_current_user(credentials)
    )


def test_expired_jwt_is_401(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)

    user = _make_user()
    token = AccessTokenService(
        secret=SECRET,
        expire_minutes=-1,
    ) if False else None

    # Construct an expired token directly through PyJWT so the test
    # exercises AccessTokenService.decode_access_token().
    import jwt

    expired_token = jwt.encode(
        {
            "sub": str(user.user_id),
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc).replace(year=2020),
            "jti": str(uuid4()),
            "typ": "access",
        },
        SECRET,
        algorithm="HS256",
    )

    _assert_unauthorized(
        lambda: dependencies.get_current_user(
            _credentials(expired_token)
        )
    )


def test_valid_jwt_returns_current_user(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    store = AuthStore(tmp_path / "auth.sqlite3")
    user = _make_user()

    from app.auth.persistence import SQLiteUserRepository

    SQLiteUserRepository(store).create(user)
    store.close()

    token = _create_token(user.user_id)

    result = dependencies.get_current_user(_credentials(token))

    assert result.user_id == user.user_id
    assert result.username == user.username
    assert result.email == user.email
    assert result.email_verified is True
    assert result.status is UserStatus.ACTIVE


def test_jwt_for_unknown_user_is_401(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    token = _create_token(uuid4())

    _assert_unauthorized(
        lambda: dependencies.get_current_user(
            _credentials(token)
        )
    )


def test_disabled_user_is_401(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    store = AuthStore(tmp_path / "auth.sqlite3")
    user = _make_user(status=UserStatus.DISABLED)

    from app.auth.persistence import SQLiteUserRepository

    SQLiteUserRepository(store).create(user)
    store.close()

    token = _create_token(user.user_id)

    _assert_unauthorized(
        lambda: dependencies.get_current_user(
            _credentials(token)
        )
    )


def test_unverified_email_user_is_401(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    store = AuthStore(tmp_path / "auth.sqlite3")
    user = _make_user(email_verified=False)

    from app.auth.persistence import SQLiteUserRepository

    SQLiteUserRepository(store).create(user)
    store.close()

    token = _create_token(user.user_id)

    _assert_unauthorized(
        lambda: dependencies.get_current_user(
            _credentials(token)
        )
    )


def test_project_access_returns_current_user(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    store = AuthStore(tmp_path / "auth.sqlite3")

    user = _make_user()

    from app.auth.persistence import (
        SQLiteProjectMembershipRepository,
        SQLiteUserRepository,
    )

    SQLiteUserRepository(store).create(user)
    SQLiteProjectMembershipRepository(store).add(
        ProjectMembership(
            membership_id=uuid4(),
            user_id=user.user_id,
            project_id="BJ-KC-2024-01",
            role="member",
            created_at=datetime.now(timezone.utc),
        )
    )
    store.close()

    token = _create_token(user.user_id)
    current_user = dependencies.get_current_user(_credentials(token))

    result = dependencies.require_project_access(
        project_id="BJ-KC-2024-01",
        current_user=current_user,
    )

    assert result.user_id == user.user_id


def test_project_access_without_membership_is_403(
        monkeypatch,
        tmp_path,
):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    store = AuthStore(tmp_path / "auth.sqlite3")
    user = _make_user()

    from app.auth.persistence import SQLiteUserRepository

    SQLiteUserRepository(store).create(user)
    store.close()

    token = _create_token(user.user_id)
    current_user = dependencies.get_current_user(_credentials(token))

    with pytest.raises(HTTPException) as error:
        dependencies.require_project_access(
            project_id="BJ-KC-2024-01",
            current_user=current_user,
        )

    assert error.value.status_code == 403
    assert error.value.detail == "Project access denied"


def test_project_access_isolated_between_users(
        monkeypatch,
        tmp_path,
):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", SECRET)
    _patch_auth_store(monkeypatch, tmp_path)

    store = AuthStore(tmp_path / "auth.sqlite3")

    owner = _make_user()
    other_user = _make_user()

    # Give the project to owner only.
    from app.auth.persistence import (
        SQLiteProjectMembershipRepository,
        SQLiteUserRepository,
    )

    # SQLite username/email are unique, so make the second user distinct.
    other_user = other_user.model_copy(
        update={
            "user_id": uuid4(),
            "username": "other-user",
            "email": "other@example.com",
        }
    )

    SQLiteUserRepository(store).create(owner)
    SQLiteUserRepository(store).create(other_user)

    SQLiteProjectMembershipRepository(store).add(
        ProjectMembership(
            membership_id=uuid4(),
            user_id=owner.user_id,
            project_id="BJ-KC-2024-01",
            role="owner",
            created_at=datetime.now(timezone.utc),
        )
    )

    store.close()

    token = _create_token(other_user.user_id)
    current_user = dependencies.get_current_user(_credentials(token))

    with pytest.raises(HTTPException) as error:
        dependencies.require_project_access(
            project_id="BJ-KC-2024-01",
            current_user=current_user,
        )

    assert error.value.status_code == 403
