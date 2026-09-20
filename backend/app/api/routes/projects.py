from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth.dependencies import get_current_user, require_project_access
import app.auth.dependencies as auth_dependencies
from app.auth.models import Project, ProjectMembership, ProjectRole, User
from app.auth.persistence import SQLiteProjectRepository

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


@router.get("", response_model=list[Project])
async def list_projects(
        current_user: User = Depends(get_current_user),
) -> list[Project]:
    """Return only projects for which the current user has membership."""
    store = auth_dependencies.AuthStore()
    try:
        return SQLiteProjectRepository(store).list_for_user(current_user.user_id)
    finally:
        store.close()


@router.post("", response_model=Project, status_code=201)
async def create_project(
        request: ProjectCreateRequest,
        current_user: User = Depends(get_current_user),
) -> Project:
    """Create a project and its owner membership atomically."""
    now = datetime.now(timezone.utc)
    project = Project(
        project_id=str(uuid4()),
        name=request.name,
        owner_user_id=current_user.user_id,
        created_at=now,
        updated_at=now,
    )
    owner_membership = ProjectMembership(
        user_id=current_user.user_id,
        project_id=project.project_id,
        role=ProjectRole.OWNER,
        created_at=now,
    )

    store = auth_dependencies.AuthStore()
    try:
        SQLiteProjectRepository(store).create_with_owner(
            project,
            owner_membership,
        )
        return project
    finally:
        store.close()


@router.get("/{project_id}", response_model=Project)
async def get_project(
        project_id: str,
        current_user: User = Depends(require_project_access),
) -> Project:
    """Return a real project after authentication and membership checks."""
    del current_user  # The dependency performs the membership check.

    store = auth_dependencies.AuthStore()
    try:
        project = SQLiteProjectRepository(store).get_by_id(project_id)
    finally:
        store.close()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return project
