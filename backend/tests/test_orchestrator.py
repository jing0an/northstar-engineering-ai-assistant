import unittest
from unittest.mock import patch

from app.agent.orchestrator import process_message
from app.agent.protocol import AgentMessage, ToolCall, ToolResult
from app.tool_router import tool_router


class AgentOrchestratorTest(unittest.TestCase):
    def test_progress_message_returns_68_percent(self) -> None:
        user_message = AgentMessage(role="user", content="帮我看看项目进度")
        route = tool_router.route(user_message.content, "BJ-KC-2024-01")
        self.assertIsNotNone(route)
        assert route is not None
        self.assertEqual(
            ToolCall.model_validate(route.tool_call).tool,
            "project_progress",
        )
        self.assertEqual(
            ToolResult.model_validate(route.tool_result).result["overall_progress"],
            "68%",
        )
        result = process_message("帮我看看项目进度", "BJ-KC-2024-01")
        self.assertEqual(result["tool"], "project_progress")
        self.assertIn("68%", result["reply"])

    def test_risk_message_returns_medium_risk(self) -> None:
        user_message = AgentMessage(role="user", content="帮我识别一下项目风险")
        route = tool_router.route(user_message.content, "BJ-KC-2024-01")
        self.assertIsNotNone(route)
        assert route is not None
        self.assertEqual(route.tool_call.tool, "risk_analysis")
        self.assertEqual(route.tool_result.result["risk_level"], "中")
        result = process_message("帮我识别一下项目风险", "BJ-KC-2024-01")
        self.assertEqual(result["tool"], "risk_analysis")
        self.assertIn("中", result["reply"])

    def test_unknown_message_raises_when_llm_is_unavailable(self) -> None:
        from app.services.assistant_errors import AssistantServiceError

        with patch(
            "app.agent.orchestrator.create_llm_provider",
            side_effect=RuntimeError("provider unavailable"),
        ):
            with self.assertRaises(AssistantServiceError) as raised:
                process_message("请介绍一下 Northstar", "BJ-KC-2024-01")
        self.assertEqual(raised.exception.code, "llm_unavailable")
        self.assertEqual(raised.exception.status_code, 503)

    def test_llm_can_execute_search_project_documents_tool(self) -> None:
        from app.agent.llm.base import LLMResponse
        from app.tools import project_documents

        class FakeResult:
            chunk_id = "chunk-001"
            project_id = "BJ-KC-2024-01"
            file_id = "file-001"
            text = "施工图设计阶段计划于2024年12月30日完成。"
            score = 0.95
            metadata = {"filename": "项目计划.pdf"}

        class FakeRetrievalService:
            def retrieve(self, query: str, project_id: str, top_k: int = 5):
                return [FakeResult()]

        class FakeLLMProvider:
            def __init__(self):
                self.calls = 0

            def generate_with_tools(self, messages, tool_schemas):
                self.calls += 1

                if self.calls == 1:
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                tool="search_project_documents",
                                arguments={
                                    "query": "施工图设计什么时候完成？",
                                    "project_id": "BJ-KC-2024-01",
                                    "top_k": 3,
                                },
                            )
                        ]
                    )

                return LLMResponse(
                    content="根据项目文档，施工图设计阶段计划于2024年12月30日完成。"
                )

        fake_service = FakeRetrievalService()
        original_service = project_documents._retrieval_service
        project_documents._retrieval_service = fake_service

        try:
            provider = FakeLLMProvider()

            result = process_message(
                "帮我从项目文档里查一下施工图什么时候完成",
                "BJ-KC-2024-01",
                llm_provider=provider,
            )

            self.assertEqual(
                result["tool"],
                "search_project_documents",
            )
            self.assertIn(
                "2024年12月30日",
                result["reply"],
            )
            self.assertEqual(provider.calls, 2)
        finally:
            project_documents._retrieval_service = original_service


if __name__ == "__main__":
    unittest.main()
