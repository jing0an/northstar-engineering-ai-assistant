from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agent.orchestrator import AgentContext, process_message
from app.agent.protocol import LLMResponse, ToolCall
from app.main import app
from app.services.assistant_errors import AssistantServiceError
from app.services.document_resolver import DocumentResolver
from app.services.vector_store.models import VectorSearchResult


PROJECT_ID = "project-a"


class FinalProvider:
    def __init__(self, content: str = "这是正常回答。") -> None:
        self.content = content

    def generate_with_tools(self, messages, tools):
        return LLMResponse(content=self.content)


class SearchThenFinalProvider:
    def __init__(self, arguments: dict[str, object]) -> None:
        self.arguments = arguments
        self.calls = 0

    def generate_with_tools(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                tool_calls=[ToolCall(tool="search_project_documents", arguments=self.arguments)]
            )
        return LLMResponse(content="根据资料得出结论。")


class EmptyRetrievalService:
    def retrieve(self, **kwargs):
        self.kwargs = kwargs
        return []


class CurrentOnlyRetrievalService:
    def retrieve(self, **kwargs):
        self.kwargs = kwargs
        return [
            VectorSearchResult(
                chunk_id="chunk-current",
                project_id=PROJECT_ID,
                file_id="file-current",
                text="当前版本内容",
                score=0.9,
                metadata={
                    "original_filename": "工程.pdf",
                    "document_version": 2,
                    "is_current": True,
                    "page_number": 3,
                },
            )
        ]


def test_normal_answer_is_explicitly_marked_answered():
    result = process_message("请介绍一下项目", PROJECT_ID, FinalProvider())
    assert result["status"] == "answered"
    assert result["reply"] == "这是正常回答。"


def test_empty_document_retrieval_returns_no_evidence_without_second_llm_answer():
    from app.tools import project_documents

    service = EmptyRetrievalService()
    original = project_documents._retrieval_service
    project_documents._retrieval_service = service
    try:
        provider = SearchThenFinalProvider({"query": "资料中有什么", "project_id": PROJECT_ID})
        result = process_message("查询资料", PROJECT_ID, provider)
    finally:
        project_documents._retrieval_service = original

    assert result == {
        "status": "no_evidence",
        "reply": "当前项目资料中没有找到足够依据回答这个问题。",
        "citations": [],
        "sources": [],
    }
    assert provider.calls == 1


def test_document_answer_returns_public_citations_and_answered_status():
    from app.tools import project_documents

    service = CurrentOnlyRetrievalService()
    original = project_documents._retrieval_service
    project_documents._retrieval_service = service
    try:
        result = process_message(
            "工程.pdf V2 的内容是什么？",
            PROJECT_ID,
            SearchThenFinalProvider({"query": "内容"}),
            document_resolver=DocumentResolver([
                {
                    "file_id": "file-current", "project_id": PROJECT_ID,
                    "original_filename": "工程.pdf", "document_version": 2,
                    "is_current": True,
                }
            ]),
            agent_context=AgentContext(),
        )
    finally:
        project_documents._retrieval_service = original

    assert result["status"] == "answered"
    assert result["citations"] == [{
        "original_filename": "工程.pdf", "document_version": 2,
        "page_number": 3, "chunk_index": None,
    }]
    assert "file_id" not in result["citations"][0]


def test_regular_document_search_cannot_request_historical_vectors():
    from app.tools import project_documents

    service = CurrentOnlyRetrievalService()
    original = project_documents._retrieval_service
    project_documents._retrieval_service = service
    try:
        process_message(
            "查询资料",
            PROJECT_ID,
            SearchThenFinalProvider({
                "query": "资料", "project_id": PROJECT_ID, "is_current": False,
            }),
        )
    finally:
        project_documents._retrieval_service = original

    assert service.kwargs["is_current"] is True


def test_explicit_historical_version_keeps_resolved_historical_filter():
    from app.tools import project_documents

    service = CurrentOnlyRetrievalService()
    original = project_documents._retrieval_service
    project_documents._retrieval_service = service
    try:
        process_message(
            "工程.pdf V1 的内容是什么？",
            PROJECT_ID,
            SearchThenFinalProvider({"query": "内容"}),
            document_resolver=DocumentResolver([
                {
                    "file_id": "file-v1", "project_id": PROJECT_ID,
                    "original_filename": "工程.pdf", "document_version": 1,
                    "is_current": False,
                },
                {
                    "file_id": "file-current", "project_id": PROJECT_ID,
                    "original_filename": "工程.pdf", "document_version": 2,
                    "is_current": True,
                },
            ]),
            agent_context=AgentContext(),
        )
    finally:
        project_documents._retrieval_service = original

    assert service.kwargs["file_id"] == "file-v1"
    assert service.kwargs["document_version"] == 1
    assert service.kwargs["is_current"] is False


def test_citation_failure_is_explicit_internal_error():
    provider = SearchThenFinalProvider({"query": "资料", "project_id": PROJECT_ID})
    from app.agent.protocol import ToolResult

    result = ToolResult(tool="search_project_documents", result={
        "results": [{
            "project_id": PROJECT_ID, "file_id": "file-current", "chunk_id": "chunk-1",
            "original_filename": "工程.pdf", "page_number": 3, "text": "内容",
            "metadata": {"document_version": 2, "is_current": True},
        }],
    })
    with patch("app.agent.orchestrator.tool_router.execute_tool_call", return_value=result), patch(
        "app.agent.orchestrator.build_citations", side_effect=RuntimeError("secret detail")
    ):
        with pytest.raises(AssistantServiceError) as raised:
            process_message("查询资料", PROJECT_ID, provider)
    assert raised.value.code == "citation_generation_failed"
    assert raised.value.status_code == 500


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (RuntimeError("missing key"), "llm_unavailable"),
        (RuntimeError("transport error"), "llm_unavailable"),
    ],
)
def test_llm_failures_are_classified(error, expected_code):
    with patch("app.agent.orchestrator.create_llm_provider", side_effect=error):
        with pytest.raises(AssistantServiceError) as raised:
            process_message("普通问题", PROJECT_ID)
    assert raised.value.status_code == 503
    assert raised.value.code == expected_code


def test_document_tool_dependency_failure_is_rag_unavailable():
    with patch.object(
        __import__("app.tool_router", fromlist=["tool_router"]).tool_router,
        "execute_tool_call",
        side_effect=RuntimeError("qdrant unavailable"),
    ):
        with pytest.raises(AssistantServiceError) as raised:
            process_message(
                "查询资料", PROJECT_ID,
                SearchThenFinalProvider({"query": "资料", "project_id": PROJECT_ID}),
            )
    assert raised.value.status_code == 503
    assert raised.value.code == "rag_unavailable"


def test_assistant_route_serializes_safe_controlled_errors(monkeypatch):
    monkeypatch.setattr("app.main.check_project_access", lambda *args: None)
    monkeypatch.setattr("app.main.process_message", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssistantServiceError(503, "llm_unavailable", "AI 模型当前不可用，请稍后重试。")
    ))
    from app.auth.models import User
    import asyncio
    from app.main import AssistantRequest, assistant

    response = asyncio.run(assistant(AssistantRequest(message="问题", project_id=PROJECT_ID, conversation_id="12345678-1234-4234-8234-123456789abc"), User(username="test", password_hash="hash")))
    assert response.status_code == 503
    assert response.body.decode("utf-8") == (
        '{"error":{"code":"llm_unavailable","message":"AI 模型当前不可用，请稍后重试。"}}'
    )
