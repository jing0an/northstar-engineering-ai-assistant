"""Controlled, safe-to-expose errors for the Assistant API."""

from __future__ import annotations


class AssistantServiceError(RuntimeError):
    """An Assistant failure with a deliberate HTTP and public error contract."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def llm_unavailable() -> AssistantServiceError:
    return AssistantServiceError(
        503,
        "llm_unavailable",
        "AI 模型当前不可用，请稍后重试。",
    )


def rag_unavailable() -> AssistantServiceError:
    return AssistantServiceError(
        503,
        "rag_unavailable",
        "项目资料检索服务当前不可用，请稍后重试。",
    )


def citation_generation_failed() -> AssistantServiceError:
    return AssistantServiceError(
        500,
        "citation_generation_failed",
        "回答来源生成失败，请稍后重试。",
    )


def internal_error() -> AssistantServiceError:
    return AssistantServiceError(
        500,
        "internal_error",
        "助理服务发生内部错误，请稍后重试。",
    )
