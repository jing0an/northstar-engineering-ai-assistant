from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth import (
    AccessTokenService,
    AuthStore,
    MockEmailProvider,
    PBKDF2PasswordHasher,
    SQLiteUserRepository,
    User,
    UserAlreadyExistsError,
    UserStatus,
    VerificationCodeRepository,
    VerificationCodeService,
    VerificationInvalidError,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_dummy_password_hasher = PBKDF2PasswordHasher()
_DUMMY_PASSWORD_HASH = _dummy_password_hasher.hash(
    "northstar-auth-dummy-password"
)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8)
    # Email verification is not wired into the product flow yet. Keep this
    # optional for compatibility with older clients that still send a code.
    verification_code: str | None = Field(default=None, min_length=1)

    @field_validator("username", "email")
    @classmethod
    def registration_text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("password")
    @classmethod
    def password_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be blank")
        return value


class RegisterResponse(BaseModel):
    user_id: str
    username: str
    email: str
    email_verified: bool
    status: UserStatus


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=8)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


def _new_services():
    store = AuthStore()
    return (
        store,
        SQLiteUserRepository(store),
        VerificationCodeService(
            VerificationCodeRepository(store),
            email_provider=MockEmailProvider(),
        ),
    )


def _find_user(
        user_repo: SQLiteUserRepository,
        identifier: str,
) -> User | None:
    identifier = identifier.strip()

    if re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            identifier,
    ):
        return user_repo.get_by_email(identifier.casefold())

    return user_repo.get_by_username(identifier)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
)
async def register(request: RegisterRequest):
    store, user_repo, verification = _new_services()

    try:
        try:
            user = User(
                username=request.username,
                email=request.email,
                password_hash="pending",
                email_verified=True,
                status=UserStatus.ACTIVE,
            )
        except Exception as error:
            raise HTTPException(
                status_code=400,
                detail="Invalid registration data",
            ) from error

        if user_repo.get_by_username(user.username) is not None:
            raise HTTPException(
                status_code=409,
                detail="Username is already registered",
            )

        if user_repo.get_by_email(user.email) is not None:
            raise HTTPException(
                status_code=409,
                detail="Email is already registered",
            )

        if request.verification_code is not None:
            try:
                verification.verify(
                    user.email,
                    request.verification_code,
                )
            except VerificationInvalidError as error:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid verification code",
                ) from error

        user = user.model_copy(
            update={
                "password_hash": PBKDF2PasswordHasher().hash(
                    request.password
                )
            }
        )

        try:
            saved = user_repo.create(user)
        except UserAlreadyExistsError as error:
            raise HTTPException(
                status_code=409,
                detail="Username or email is already registered",
            ) from error

        return RegisterResponse(
            user_id=str(saved.user_id),
            username=saved.username,
            email=saved.email or "",
            email_verified=saved.email_verified,
            status=saved.status,
        )
    finally:
        store.close()


@router.post(
    "/login",
    response_model=LoginResponse,
)
async def login(request: LoginRequest):
    store, user_repo, _ = _new_services()

    try:
        identifier = request.identifier.strip()

        if not identifier:
            raise HTTPException(
                status_code=401,
                detail="Invalid username/email or password",
            )

        user = _find_user(user_repo, identifier)

        password_hasher = PBKDF2PasswordHasher()

        if user is None:
            password_hasher.verify(
                request.password,
                _DUMMY_PASSWORD_HASH,
            )
            raise HTTPException(
                status_code=401,
                detail="Invalid username/email or password",
            )

        if not password_hasher.verify(
                request.password,
                user.password_hash,
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid username/email or password",
            )

        if user.status is not UserStatus.ACTIVE:
            raise HTTPException(
                status_code=401,
                detail="Invalid username/email or password",
            )

        if not user.email_verified:
            raise HTTPException(
                status_code=401,
                detail="Invalid username/email or password",
            )

        token_service = AccessTokenService()

        access_token = token_service.create_access_token(
            user.user_id
        )

        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=token_service.expire_minutes * 60,
        )
    finally:
        store.close()
