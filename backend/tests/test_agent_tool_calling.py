import unittest

from app.agent.orchestrator import process_message
from app.agent.protocol import LLMResponse, ToolCall
from app.tool_router import tool_router


class FakeToolCallingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def generate(self, messages):
        return "unused"

    def generate_with_tools(self, messages, tools):
        self.calls.append((list(messages), list(tools)))
        if len(self.calls) == 1:
            return LLMResponse(
                tool_calls=([
                    ToolCall(
                        tool="project_progress",
                        arguments={"project_id": "BJ-KC-2024-01"},
                        call_id="call-1",
                    )
                ])
            )
        return LLMResponse(
            content="我的工程项目目前处于施工图设计阶段，整体进度为 68%。"
        )


class FakeRiskToolCallingProvider(FakeToolCallingProvider):
    def generate_with_tools(self, messages, tools):
        self.calls.append((list(messages), list(tools)))
        if len(self.calls) == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        tool="risk_analysis",
                        arguments={"project_id": "BJ-KC-2024-01"},
                        call_id="risk-call-1",
                    )
                ]
            )
        return LLMResponse(content="目前我的工程项目整体风险等级为中。")


class AgentToolCallingTest(unittest.TestCase):
    def test_progress_tool_schema_is_generated_from_router(self) -> None:
        schemas = tool_router.tool_schemas(("project_progress",))
        self.assertEqual(schemas[0]["function"]["name"], "project_progress")
        self.assertIn("查询指定工程项目的当前进度", schemas[0]["function"]["description"])
        self.assertEqual(schemas[0]["function"]["parameters"]["properties"]["project_id"]["type"], "string")

    def test_tool_call_loop_executes_router_and_returns_final_reply(self) -> None:
        provider = FakeToolCallingProvider()
        result = process_message("帮我看看项目进度", "BJ-KC-2024-01", provider)
        self.assertEqual(result["tool"], "project_progress")
        self.assertIn("68%", result["reply"])
        self.assertEqual(len(provider.calls), 2)
        second_messages = provider.calls[1][0]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertIn("68%", second_messages[-1]["content"])

    def test_risk_tool_schema_and_two_round_tool_call_loop(self) -> None:
        schemas = tool_router.tool_schemas(("risk_analysis",))
        self.assertEqual(schemas[0]["function"]["name"], "risk_analysis")
        self.assertIn("分析指定工程项目的工期、质量、成本风险", schemas[0]["function"]["description"])
        self.assertEqual(schemas[0]["function"]["parameters"]["properties"]["project_id"]["type"], "string")

        provider = FakeRiskToolCallingProvider()
        result = process_message("帮我识别一下项目风险", "BJ-KC-2024-01", provider)
        self.assertEqual(result["tool"], "risk_analysis")
        self.assertIn("风险等级为中", result["reply"])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[1][0][-1]["role"], "tool")
        self.assertIn("risk_level", provider.calls[1][0][-1]["content"])
        self.assertEqual(
            {schema["function"]["name"] for schema in provider.calls[0][1]},
            {"project_progress", "risk_analysis", "search_project_documents"},
        )

    def test_unknown_tool_call_is_rejected(self) -> None:
        from app.services.assistant_errors import AssistantServiceError

        class UnknownToolProvider(FakeToolCallingProvider):
            def generate_with_tools(self, messages, tools):
                return LLMResponse(
                    tool_calls=[ToolCall(tool="not_registered", arguments={})]
                )

        with self.assertRaises(AssistantServiceError) as raised:
            process_message(
                "帮我看看项目进度", "BJ-KC-2024-01", UnknownToolProvider()
            )
        self.assertEqual(raised.exception.code, "internal_error")


if __name__ == "__main__":
    unittest.main()
