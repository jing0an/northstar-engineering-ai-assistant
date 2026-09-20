from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import User, UserStatus
from .persistence import (
    SQLiteProjectMembershipRepository,
    SQLiteUserRepository,
)
from .store import AuthStore
from .token import AccessTokenError, AccessTokenService

_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail="Project access denied",
    )


def get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """Resolve and validate the currently authenticated user from a Bearer JWT."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        token_service = AccessTokenService()
        claims = token_service.decode_access_token(credentials.credentials)
        user_id = UUID(str(claims["sub"]))
    except (AccessTokenError, KeyError, TypeError, ValueError):
        raise _unauthorized()

    store = AuthStore()
    repository = SQLiteUserRepository(store)

    try:
        user = repository.get_by_id(user_id)

        if user is None:
            raise _unauthorized()

        if user.status is not UserStatus.ACTIVE:
            raise _unauthorized()

        if not user.email_verified:
            raise _unauthorized()

        return user
    finally:
        store.close()


def check_project_access(current_user: User, project_id: str) -> None:
    """Require the authenticated user to have membership in the project."""
    store = AuthStore()
    repository = SQLiteProjectMembershipRepository(store)

    try:
        if not repository.has_access(current_user.user_id, project_id):
            raise _forbidden()
    finally:
        store.close()


def require_project_access(
        project_id: str = Path(..., min_length=1, max_length=200),
        current_user: User = Depends(get_current_user),
) -> User:
    """Require the authenticated user to have membership in the project."""
    check_project_access(current_user, project_id)
    return current_user
