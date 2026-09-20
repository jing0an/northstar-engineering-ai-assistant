import unittest
from unittest.mock import patch

from app.agent.orchestrator import MAX_TOOL_ITERATIONS, process_message
from app.agent.protocol import LLMResponse, ToolCall
from app.services.vector_store.models import VectorSearchResult
from app.tool_router import tool_router


PROJECT_ID = "BJ-KC-2024-01"


class SequentialProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def generate(self, messages):
        return "unused"

    def generate_with_tools(self, messages, tools):
        self.calls.append((list(messages), list(tools)))
        if len(self.calls) == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        tool="project_progress",
                        arguments={"project_id": PROJECT_ID},
                        call_id="progress-call",
                    )
                ]
            )
        if len(self.calls) == 2:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        tool="risk_analysis",
                        arguments={"project_id": PROJECT_ID},
                        call_id="risk-call",
                    )
                ]
            )
        return LLMResponse(content="综合判断：项目进度 68%，风险等级为中。")


class ParallelProvider:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def generate(self, messages):
        return "unused"

    def generate_with_tools(self, messages, tools):
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        tool="project_progress",
                        arguments={"project_id": PROJECT_ID},
                        call_id="progress-call",
                    ),
                    ToolCall(
                        tool="risk_analysis",
                        arguments={"project_id": PROJECT_ID},
                        call_id="risk-call",
                    ),
                ]
            )
        return LLMResponse(content="进度 68%，整体风险等级为中。")


class AgentLoopTest(unittest.TestCase):
    def test_sequential_tool_calls_feed_each_result_to_next_llm_round(self) -> None:
        provider = SequentialProvider()
        result = process_message("请综合判断项目", PROJECT_ID, provider)

        self.assertEqual(result["tool"], "risk_analysis")
        self.assertIn("68%", result["reply"])
        self.assertIn("风险等级为中", result["reply"])
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(provider.calls[1][0][-1]["role"], "tool")
        self.assertIn("overall_progress", provider.calls[1][0][-1]["content"])
        self.assertEqual(
            [message["role"] for message in provider.calls[2][0][-2:]],
            ["assistant", "tool"],
        )
        self.assertIn("risk_level", provider.calls[2][0][-1]["content"])

    def test_multiple_tool_calls_in_one_round_are_both_executed(self) -> None:
        provider = ParallelProvider()
        result = process_message("请同时看进度和风险", PROJECT_ID, provider)

        self.assertIn("68%", result["reply"])
        self.assertIn("风险等级为中", result["reply"])
        self.assertEqual(len(provider.calls), 2)
        second_messages = provider.calls[1]
        self.assertEqual(
            [message["role"] for message in second_messages[-2:]],
            ["tool", "tool"],
        )
        self.assertIn("overall_progress", second_messages[-2]["content"])
        self.assertIn("risk_level", second_messages[-1]["content"])

    def test_unknown_tool_is_rejected_without_executing_any_batch_call(self) -> None:
        from app.services.assistant_errors import AssistantServiceError

        class UnknownProvider:
            def generate(self, messages):
                return "unused"

            def generate_with_tools(self, messages, tools):
                return LLMResponse(
                    tool_calls=[
                        ToolCall(
                            tool="not_registered",
                            arguments={"project_id": PROJECT_ID},
                        ),
                        ToolCall(
                            tool="project_progress",
                            arguments={"project_id": PROJECT_ID},
                        ),
                    ]
                )

        with patch.object(tool_router, "execute_tool_call") as execute:
            with self.assertRaises(AssistantServiceError) as raised:
                process_message("任意问题", PROJECT_ID, UnknownProvider())

        self.assertEqual(raised.exception.code, "internal_error")
        execute.assert_not_called()

    def test_loop_stops_at_maximum_iterations(self) -> None:
        from app.services.assistant_errors import AssistantServiceError

        class InfiniteProvider:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, messages):
                return "unused"

            def generate_with_tools(self, messages, tools):
                self.calls += 1
                return LLMResponse(
                    tool_calls=[
                        ToolCall(
                            tool="project_progress",
                            arguments={"project_id": PROJECT_ID},
                        )
                    ]
                )

        provider = InfiniteProvider()
        with self.assertRaises(AssistantServiceError) as raised:
            process_message("循环调用", PROJECT_ID, provider)

        self.assertEqual(provider.calls, MAX_TOOL_ITERATIONS)
        self.assertEqual(raised.exception.code, "internal_error")

    def test_repeated_document_query_is_skipped_and_existing_citation_is_kept(self) -> None:
        from app.tools import project_documents

        class FakeRetrievalService:
            def __init__(self) -> None:
                self.calls = []

            def retrieve(self, **kwargs):
                self.calls.append(kwargs)
                return [
                    VectorSearchResult(
                        chunk_id="chunk-v2",
                        project_id=PROJECT_ID,
                        file_id="file-v2",
                        text="项目清单内容",
                        score=0.9,
                        metadata={
                            "original_filename": "工程.pdf",
                            "document_version": 2,
                            "is_current": True,
                            "page_number": 9,
                        },
                    )
                ]

        class RepeatingSearchProvider:
            def __init__(self) -> None:
                self.calls = []

            def generate(self, messages):
                return "unused"

            def generate_with_tools(self, messages, tools):
                self.calls.append(list(messages))
                if len(self.calls) == 1:
                    return LLMResponse(tool_calls=[ToolCall(
                        tool="search_project_documents",
                        arguments={"query": "项目清单", "project_id": PROJECT_ID},
                    )])
                if len(self.calls) == 2:
                    return LLMResponse(tool_calls=[ToolCall(
                        tool="search_project_documents",
                        arguments={"query": "项目 清单！", "project_id": PROJECT_ID},
                    )])
                return LLMResponse(content="基于已检索内容回答。")

        service = FakeRetrievalService()
        original = project_documents._retrieval_service
        project_documents._retrieval_service = service
        try:
            provider = RepeatingSearchProvider()
            result = process_message("查询文档", PROJECT_ID, provider)
        finally:
            project_documents._retrieval_service = original

        self.assertEqual(len(service.calls), 1)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(result["reply"], "基于已检索内容回答。")
        self.assertEqual(result["citations"][0]["page_number"], 9)

    def test_document_search_limit_forces_final_answer_with_citations(self) -> None:
        from app.tools import project_documents

        class FakeRetrievalService:
            def __init__(self) -> None:
                self.calls = []

            def retrieve(self, **kwargs):
                self.calls.append(kwargs)
                return [
                    VectorSearchResult(
                        chunk_id=f"chunk-{len(self.calls)}",
                        project_id=PROJECT_ID,
                        file_id="file-v2",
                        text="表格行",
                        score=0.8,
                        metadata={
                            "original_filename": "工程.pdf",
                            "document_version": 2,
                            "is_current": True,
                            "page_number": len(self.calls) + 4,
                        },
                    )
                ]

        class InfiniteSearchProvider:
            def __init__(self) -> None:
                self.calls = []

            def generate(self, messages):
                return "unused"

            def generate_with_tools(self, messages, tools):
                self.calls.append(list(messages))
                if len(self.calls) <= 4:
                    return LLMResponse(tool_calls=[ToolCall(
                        tool="search_project_documents",
                        arguments={
                            "query": f"项目清单 {len(self.calls)}",
                            "project_id": PROJECT_ID,
                        },
                    )])
                return LLMResponse(content="根据已有表格结果整理如下。")

        service = FakeRetrievalService()
        original = project_documents._retrieval_service
        project_documents._retrieval_service = service
        try:
            provider = InfiniteSearchProvider()
            result = process_message("查询文档", PROJECT_ID, provider)
        finally:
            project_documents._retrieval_service = original

        self.assertEqual(len(service.calls), 3)
        self.assertEqual(len(provider.calls), 5)
        self.assertEqual(result["reply"], "根据已有表格结果整理如下。")
        self.assertEqual(
            [item["page_number"] for item in result["citations"]],
            [5, 6, 7],
        )
        self.assertIn("请停止调用工具", provider.calls[-1][-1]["content"])


if __name__ == "__main__":
    unittest.main()
