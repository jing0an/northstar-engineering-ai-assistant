import unittest

from app.tool_router import tool_router


class ToolRouterTest(unittest.TestCase):
    def test_routes_progress_question(self) -> None:
        result = tool_router.route("帮我看看项目进度", "BJ-KC-2024-01")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["tool"], "project_progress")
        self.assertEqual(result["result"]["overall_progress"], "68%")

    def test_routes_risk_question(self) -> None:
        result = tool_router.route("帮我识别一下项目风险", "BJ-KC-2024-01")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["tool"], "risk_analysis")
        self.assertEqual(result["result"]["risk_level"], "中")

    def test_unknown_question_does_not_call_a_tool(self) -> None:
        self.assertIsNone(tool_router.route("今天的天气怎么样", "BJ-KC-2024-01"))




    def test_search_project_documents_tool(self) -> None:
        from app.tools.project_documents import search_project_documents

        class FakeResult:
            chunk_id = "chunk-001"
            project_id = "BJ-KC-2024-01"
            file_id = "file-001"
            text = "施工图设计阶段计划于2024年12月30日完成。"
            score = 0.95
            metadata = {"filename": "项目计划.pdf"}

        class FakeRetrievalService:
            def retrieve(self, query: str, project_id: str, top_k: int = 5):
                self.called_with = (query, project_id, top_k)
                return [FakeResult()]

        fake_service = FakeRetrievalService()

        result = search_project_documents(
            query="施工图设计什么时候完成？",
            project_id="BJ-KC-2024-01",
            top_k=3,
            retrieval_service=fake_service,
        )

        self.assertEqual(result["query"], "施工图设计什么时候完成？")
        self.assertEqual(result["project_id"], "BJ-KC-2024-01")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(
            result["results"][0]["chunk_id"],
            "chunk-001",
        )
        self.assertEqual(
            result["results"][0]["text"],
            "施工图设计阶段计划于2024年12月30日完成。",
        )
        self.assertEqual(
            fake_service.called_with,
            (
                "施工图设计什么时候完成？",
                "BJ-KC-2024-01",
                3,
            ),
        )


    def test_search_project_documents_defaults_to_current_versions(self) -> None:
        from app.tools.project_documents import search_project_documents

        class FakeResult:
            chunk_id = "chunk-current"
            project_id = "project-a"
            file_id = "file-1"
            text = "current"
            score = 1.0
            metadata = {"original_filename": "plan.pdf", "is_current": True}

        class FakeRetrievalService:
            def retrieve(self, **kwargs):
                self.called_with = kwargs
                return [FakeResult()]

        service = FakeRetrievalService()
        search_project_documents("进度", "project-a", retrieval_service=service)
        self.assertTrue(service.called_with["is_current"])
    def test_execute_search_forwards_document_version(self):
        from app.agent.protocol import ToolCall
        from app.tools import project_documents

        class FakeResult:
            chunk_id = "chunk-v2"; project_id = "project-a"; file_id = "file-v2"; text = "v2"; score = 1.0
            metadata = {"original_filename": "工程.pdf", "document_version": 2, "is_current": False}

        class FakeRetrievalService:
            def retrieve(self, **kwargs):
                self.called_with = kwargs
                return [FakeResult()]

        service = FakeRetrievalService()
        original = project_documents._retrieval_service
        project_documents._retrieval_service = service
        try:
            tool_router.execute_tool_call(ToolCall(tool="search_project_documents", arguments={
                "query": "融资计划", "project_id": "project-a", "file_id": "file-v2", "document_version": 2, "is_current": False,
            }))
            self.assertEqual(service.called_with["file_id"], "file-v2")
            self.assertEqual(service.called_with["document_version"], 2)
        finally:
            project_documents._retrieval_service = original
    def test_execute_search_project_documents_tool(self) -> None:
        from app.agent.protocol import ToolCall
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
                self.called_with = (query, project_id, top_k)
                return [FakeResult()]

        fake_service = FakeRetrievalService()

        original_service = project_documents._retrieval_service
        project_documents._retrieval_service = fake_service

        try:
            tool_call = ToolCall(
                tool="search_project_documents",
                arguments={
                    "query": "施工图设计什么时候完成？",
                    "project_id": "BJ-KC-2024-01",
                    "top_k": 3,
                },
            )

            result = tool_router.execute_tool_call(tool_call)

            self.assertEqual(result.tool, "search_project_documents")
            self.assertEqual(
                result.result["project_id"],
                "BJ-KC-2024-01",
            )
            self.assertEqual(
                result.result["query"],
                "施工图设计什么时候完成？",
            )
            self.assertEqual(len(result.result["results"]), 1)
            self.assertEqual(
                result.result["results"][0]["text"],
                "施工图设计阶段计划于2024年12月30日完成。",
            )
            self.assertEqual(
                fake_service.called_with,
                (
                    "施工图设计什么时候完成？",
                    "BJ-KC-2024-01",
                    3,
                ),
            )
        finally:
            project_documents._retrieval_service = original_service

if __name__ == "__main__":
    unittest.main()

