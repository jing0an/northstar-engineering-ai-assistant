import asyncio
import unittest
from unittest.mock import patch
from app.auth.models import User

from app.main import AssistantRequest, assistant
from app.tools.risk_analysis import risk_analysis


class RiskAnalysisTest(unittest.TestCase):
    def test_risk_analysis_tool_returns_expected_risks(self) -> None:
        result = risk_analysis("BJ-KC-2024-01")
        self.assertEqual(result["project_id"], "BJ-KC-2024-01")
        self.assertEqual(result["risk_level"], "中")
        self.assertEqual(len(result["risks"]), 3)
        self.assertEqual({risk["type"] for risk in result["risks"]}, {"工期", "质量", "成本"})

    def test_assistant_routes_risk_question_to_tool(self) -> None:
        with patch("app.main.check_project_access"):
            result = asyncio.run(assistant(AssistantRequest(message="帮我识别一下项目风险", conversation_id="12345678-1234-4234-8234-123456789abc"), current_user=User(username="test", password_hash="hash")))
        self.assertEqual(result["tool"], "risk_analysis")
        self.assertIn("风险等级为中", result["reply"])


if __name__ == "__main__":
    unittest.main()
