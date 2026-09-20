import logging
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.routes import auth, files, health, projects
from app.agent.orchestrator import process_message
from app.auth.dependencies import check_project_access, get_current_user
from app.auth.models import User
from app.services.assistant_errors import AssistantServiceError

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Northstar Project Assistant API",
    version="0.1.0",
    description="Engineering project assistant backend foundation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(auth.router, prefix="/api")


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=10000)
    project_id: str = Field("BJ-KC-2024-01", min_length=1, max_length=200)
    conversation_id: UUID

    @field_validator("message", "project_id")
    @classmethod
    def validate_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


@app.post("/api/assistant")
async def assistant(
        request: AssistantRequest,
        current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    check_project_access(current_user, request.project_id)

    try:
        return process_message(
            request.message,
            request.project_id,
            user_id=str(current_user.user_id),
            conversation_id=str(request.conversation_id),
        )
    except AssistantServiceError as error:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Assistant processing failed")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "助理服务发生内部错误，请稍后重试。",
                }
            },
        )
