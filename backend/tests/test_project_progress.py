import asyncio
import unittest
from unittest.mock import patch
from app.auth.models import User

from app.main import AssistantRequest, assistant
from app.tools.project_progress import project_progress


class ProjectProgressTest(unittest.TestCase):
    def test_project_progress_tool_returns_68_percent(self) -> None:
        result = project_progress("BJ-KC-2024-01")
        self.assertEqual(result["overall_progress"], "68%")
        self.assertEqual(result["current_status"], "进行中")

    def test_assistant_routes_progress_question_to_tool(self) -> None:
        with patch("app.main.check_project_access"):
            result = asyncio.run(assistant(AssistantRequest(message="帮我看看项目进度", conversation_id="12345678-1234-4234-8234-123456789abc"), current_user=User(username="test", password_hash="hash")))
        self.assertEqual(result["tool"], "project_progress")
        self.assertIn("68%", result["reply"])


if __name__ == "__main__":
    unittest.main()
