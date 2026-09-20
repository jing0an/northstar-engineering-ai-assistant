"""Small, persistence-agnostic identity and project membership models."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

def _utc_now() -> datetime: return datetime.now(timezone.utc)
class UserStatus(str, Enum):
    PENDING="pending"
    ACTIVE="active"
    DISABLED="disabled"
class ProjectRole(str, Enum):
    OWNER="owner"
    MEMBER="member"
    VIEWER="viewer"


class ProjectStatus(str, Enum):
    """Lifecycle state for a project."""

    ACTIVE = "active"
    ARCHIVED = "archived"
class User(BaseModel):
    """Identity model. Plaintext passwords are rejected; only hashes belong here."""
    model_config=ConfigDict(extra="forbid")
    user_id: UUID=Field(default_factory=uuid4)
    username: str=Field(min_length=1,max_length=100)
    email: str|None=Field(default=None,max_length=320)
    password_hash: str=Field(min_length=1)
    email_verified: bool=False
    status: UserStatus=UserStatus.PENDING
    created_at: datetime=Field(default_factory=_utc_now)
    updated_at: datetime=Field(default_factory=_utc_now)
    @field_validator("username","password_hash")
    @classmethod
    def no_blank(cls,value:str)->str:
        value=value.strip()
        if not value: raise ValueError("value must not be blank")
        return value
    @field_validator("email")
    @classmethod
    def email_shape(cls,value:str|None)->str|None:
        if value is None:return None
        value=value.strip().casefold()
        if not value or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",value): raise ValueError("email must be valid")
        return value
    @field_validator("created_at","updated_at")
    @classmethod
    def utc(cls,value:datetime)->datetime:
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)
    @model_validator(mode="after")
    def ordered(self)->"User":
        if self.updated_at<self.created_at: raise ValueError("updated_at must not be earlier than created_at")
        return self
class ProjectMembership(BaseModel):
    """Future authorization link to the existing opaque project_id."""
    model_config=ConfigDict(extra="forbid")
    membership_id: UUID=Field(default_factory=uuid4)
    user_id: UUID
    project_id: str=Field(min_length=1,max_length=200)
    role: ProjectRole=ProjectRole.MEMBER
    created_at: datetime=Field(default_factory=_utc_now)
    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls,value:str)->str:
        value=value.strip()
        if not value or value in {".",".."} or "/" in value or "\\" in value: raise ValueError("project_id must be an opaque identifier")
        return value
    @field_validator("created_at")
    @classmethod
    def utc(cls,value:datetime)->datetime:
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class Project(BaseModel):
    """A persisted engineering project owned by a user."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    status: ProjectStatus = ProjectStatus.ACTIVE
    owner_user_id: UUID
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError("project_id must be an opaque identifier")
        return value

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def ordered(self) -> "Project":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self
class VerificationPurpose(str, Enum):
    REGISTRATION="registration"
    PASSWORD_RESET="password_reset"
    CHANGE_EMAIL="change_email"
    EMAIL_LOGIN="email_login"
class VerificationStatus(str, Enum):
    ACTIVE="active"
    CONSUMED="consumed"
    EXPIRED="expired"
    LOCKED="locked"
class EmailVerificationCode(BaseModel):
    model_config=ConfigDict(extra="forbid")
    verification_id: UUID=Field(default_factory=uuid4)
    email: str=Field(min_length=3,max_length=320)
    purpose: VerificationPurpose=VerificationPurpose.REGISTRATION
    code_hash: str=Field(min_length=1)
    expires_at: datetime
    created_at: datetime=Field(default_factory=_utc_now)
    consumed_at: datetime|None=None
    failed_attempts: int=Field(default=0,ge=0)
    status: VerificationStatus=VerificationStatus.ACTIVE
    @field_validator("email")
    @classmethod
    def verification_email(cls,value:str)->str:
        value=value.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",value): raise ValueError("email must be valid")
        return value
    @field_validator("created_at","expires_at","consumed_at")
    @classmethod
    def verification_utc(cls,value):
        if value is None:return None
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)
    @model_validator(mode="after")
    def verification_lifecycle(self):
        if self.expires_at<=self.created_at: raise ValueError("expires_at must be later than created_at")
        if self.status is VerificationStatus.CONSUMED and self.consumed_at is None: raise ValueError("consumed_at is required")
        if self.status is not VerificationStatus.CONSUMED and self.consumed_at is not None: raise ValueError("consumed_at requires consumed status")
        return self

