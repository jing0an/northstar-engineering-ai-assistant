import unittest

from app.agent.llm.base import LLMResponse
from app.agent.protocol import ToolCall
from app.agent.orchestrator import AgentContext, _AGENT_CONTEXTS, process_message
from app.services.document_resolver import DocumentResolver


def record(file_id, filename, version, uploaded_at, project="project-a", current=True):
    return {
        "file_id": file_id,
        "project_id": project,
        "original_filename": filename,
        "document_version": version,
        "is_current": current,
        "uploaded_at": uploaded_at,
    }


class FinalLLM:
    def __init__(self, content="已收到"):
        self.content = content
        self.calls = []

    def generate_with_tools(self, messages, tools):
        self.calls.append((messages, tools))
        return LLMResponse(content=self.content)


class SpyResolver(DocumentResolver):
    def __init__(self, documents):
        super().__init__(documents)
        self.calls = []

    def resolve(self, query, project_id, **kwargs):
        self.calls.append((query, project_id, kwargs))
        return super().resolve(query, project_id, **kwargs)



class ToolThenFinalLLM:
    def __init__(self, arguments, content="已检索"):
        self.arguments = arguments
        self.content = content
        self.calls = []
        self.step = 0

    def generate_with_tools(self, messages, tools):
        self.calls.append(messages)
        if self.step == 0:
            self.step += 1
            return LLMResponse(tool_calls=[ToolCall(tool="search_project_documents", arguments=self.arguments)])
        return LLMResponse(content=self.content)


class CapturingRetrievalService:
    def __init__(self):
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return []

class AgentDocumentResolverTest(unittest.TestCase):
    def setUp(self):
        _AGENT_CONTEXTS.clear()
        self.documents = [
            record("a-v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record("a-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00"),
            record("b-v1", "说明书.pdf", 1, "2026-09-03T00:00:00+00:00"),
            record("c-v1", "合同.pdf", 1, "2026-09-04T00:00:00+00:00"),
        ]
        self.resolver = SpyResolver(self.documents)

    def tearDown(self):
        _AGENT_CONTEXTS.clear()

    def test_explicit_filename_and_version_are_saved_in_agent_context(self):
        context = AgentContext()
        provider = FinalLLM()
        result = process_message(
            "分析一下第二版工程.pdf",
            "project-a",
            provider,
            document_resolver=self.resolver,
            agent_context=context,
        )
        self.assertEqual(result["reply"], "已收到")
        self.assertEqual(context.last_referenced_document.file_id, "a-v2")
        self.assertEqual(context.last_referenced_document.document_version, 2)
        self.assertIn("工程.pdf", provider.calls[0][0][1]["content"])
        self.assertNotIn("a-v2", result["reply"])
        self.assertNotIn("project-a", result["reply"])

    def test_v2_syntax_and_ordinal_are_delegated_to_resolver(self):
        context = AgentContext()
        process_message("工程.pdf V2", "project-a", FinalLLM(), document_resolver=self.resolver, agent_context=context)
        self.assertEqual(context.last_referenced_document.document_version, 2)
        process_message("第二个文件", "project-a", FinalLLM(), document_resolver=self.resolver, agent_context=AgentContext())
        self.assertEqual(self.resolver.calls[-1][0], "第二个文件")

    def test_latest_filename_resolves_but_project_latest_is_ambiguous(self):
        context = AgentContext()
        process_message("最新版工程.pdf", "project-a", FinalLLM(), document_resolver=self.resolver, agent_context=context)
        self.assertEqual(context.last_referenced_document.file_id, "a-v2")
        provider = FinalLLM()
        result = process_message("最新版", "project-a", provider, document_resolver=self.resolver, agent_context=AgentContext())
        self.assertIn("多个文档", result["reply"])
        self.assertEqual(provider.calls, [])

    def test_multiple_explicit_filenames_stop_before_llm_and_rag(self):
        provider = FinalLLM()
        result = process_message(
            "比较 工程.pdf 和 说明书.pdf。它的第3页有什么区别？",
            "project-a",
            provider,
            document_resolver=self.resolver,
            agent_context=AgentContext(),
        )
        self.assertEqual(result["status"], "no_evidence")
        self.assertIn("多个文档", result["reply"])
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["sources"], [])
        self.assertEqual(provider.calls, [])

    def test_contextual_latest_is_bound_to_last_document(self):
        def page_record(file_id, filename, version, current):
            return {
                **record(file_id, filename, version, f"2026-09-{version:02d}T00:00:00+00:00", current=current),
                "display_page_mapping": {"1": 2, "2": 3, "3": 4},
                "file_type": "pdf",
            }

        resolver = SpyResolver([
            page_record("a-v1", "工程.pdf", 1, False),
            page_record("a-v2", "工程.pdf", 2, False),
            page_record("a-v3", "工程.pdf", 3, True),
            page_record("b-v1", "说明书.pdf", 1, False),
            page_record("b-v2", "说明书.pdf", 2, False),
            page_record("b-v4", "说明书.pdf", 4, True),
        ])
        context = AgentContext()
        process_message("工程.pdf V2", "project-a", FinalLLM(), document_resolver=resolver, agent_context=context)
        initial_context = context.last_referenced_document
        for query in (
            "最新版的第3页讲了什么",
            "这个文件的最新版第3页讲了什么",
            "这个文件的当前版本第3页讲了什么",
            "现在这个版本的第3页讲了什么",
        ):
            with self.subTest(query=query):
                context.last_referenced_document = initial_context
                process_message(query, "project-a", FinalLLM(), document_resolver=resolver, agent_context=context)
                self.assertEqual(resolver.calls[-1][2]["previous_document"].file_id, "a-v2")
                self.assertEqual(context.last_referenced_document.file_id, "a-v3")

    def test_contextual_page_phrasings_resolve_expected_document_versions(self):
        def page_record(file_id, filename, version, current):
            return {
                **record(file_id, filename, version, f"2026-09-{version:02d}T00:00:00+00:00", current=current),
                "display_page_mapping": {"1": 2, "2": 3, "3": 4},
                "file_type": "pdf",
            }

        resolver = SpyResolver([
            page_record("a-v3", "工程.pdf", 3, False),
            page_record("a-v4", "工程.pdf", 4, True),
        ])
        context = AgentContext()
        process_message("工程.pdf V4", "project-a", FinalLLM(), document_resolver=resolver, agent_context=context)
        for query, expected_file_id in (
            ("它的第3页讲了什么", "a-v4"),
            ("这份文件的第3页讲了什么", "a-v4"),
            ("刚才那份文件的第3页讲了什么", "a-v4"),
            ("上一版本的第3页讲了什么", "a-v3"),
            ("之前那个版本的第3页讲了什么", "a-v3"),
        ):
            with self.subTest(query=query):
                process_message(query, "project-a", FinalLLM(), document_resolver=resolver, agent_context=context)
                self.assertEqual(context.last_referenced_document.file_id, expected_file_id)

    def test_new_contextual_page_phrasings_without_history_stop_before_llm(self):
        for query in (
            "它的第3页讲了什么",
            "这份文件的第5页是什么",
            "刚才那份文件的第3页是什么",
            "上一版本的第3页是什么",
        ):
            with self.subTest(query=query):
                provider = FinalLLM()
                result = process_message(
                    query,
                    "project-a",
                    provider,
                    document_resolver=self.resolver,
                    agent_context=AgentContext(),
                )
                self.assertEqual(result["status"], "no_evidence")
                self.assertEqual(result["citations"], [])
                self.assertEqual(result["sources"], [])
                self.assertEqual(provider.calls, [])

    def test_not_found_and_insufficient_context_stop_before_llm(self):
        provider = FinalLLM()
        result = process_message("查一下工程.pdf V99", "project-a", provider, document_resolver=self.resolver, agent_context=AgentContext())
        self.assertIn("没有找到", result["reply"])
        self.assertEqual(provider.calls, [])
        provider = FinalLLM()
        result = process_message("查一下刚才那个", "project-a", provider, document_resolver=self.resolver, agent_context=AgentContext())
        self.assertIn("先指定一下文档", result["reply"])
        self.assertEqual(provider.calls, [])

    def test_unknown_filename_stops_before_llm_and_returns_no_evidence(self):
        provider = FinalLLM()
        result = process_message(
            "请查询不存在的测试文件999.pdf，并告诉我它的内容",
            "project-a",
            provider,
            document_resolver=self.resolver,
            agent_context=AgentContext(),
        )
        self.assertEqual(result["status"], "no_evidence")
        self.assertIn("没有找到", result["reply"])
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["sources"], [])
        self.assertEqual(provider.calls, [])

    def test_contextual_and_previous_version_references(self):
        context = AgentContext()
        process_message("工程.pdf V2", "project-a", FinalLLM(), document_resolver=self.resolver, agent_context=context)
        process_message("刚才那个", "project-a", FinalLLM(), document_resolver=self.resolver, agent_context=context)
        self.assertEqual(context.last_referenced_document.file_id, "a-v2")
        context.last_referenced_document = next(item for item in self.resolver.documents if item.file_id == "a-v2")
        process_message("上一个版本", "project-a", FinalLLM(), document_resolver=self.resolver, agent_context=context)
        self.assertEqual(context.last_referenced_document.file_id, "a-v1")

    def test_contextual_entry_terms_reuse_last_referenced_document(self):
        for query in ("这份文件", "这个文件", "刚才那份报告", "它", "上一个", "刚才那个 PDF"):
            with self.subTest(query=query):
                context = AgentContext()
                process_message(
                    "工程.pdf V2", "project-a", FinalLLM(),
                    document_resolver=self.resolver, agent_context=context,
                )
                calls_before = len(self.resolver.calls)
                result = process_message(
                    query, "project-a", FinalLLM("已使用上一轮文档"),
                    document_resolver=self.resolver, agent_context=context,
                )

                self.assertEqual(result["reply"], "已使用上一轮文档")
                self.assertEqual(len(self.resolver.calls), calls_before + 1)
                self.assertEqual(
                    self.resolver.calls[-1][2]["previous_document"].file_id,
                    "a-v2",
                )
                self.assertEqual(context.last_referenced_document.file_id, "a-v2")

    def test_cross_project_context_is_not_used(self):
        context = AgentContext(last_referenced_document=self.resolver.documents[1], current_project_id="other-project")
        provider = FinalLLM()
        result = process_message("刚才那个", "project-a", provider, document_resolver=self.resolver, agent_context=context)
        self.assertIn("先指定一下文档", result["reply"])
        self.assertEqual(provider.calls, [])

    def test_contexts_are_isolated_by_conversation_for_same_user_and_project(self):
        user_id = "user-a"
        conversation_a = "11111111-1111-4111-8111-111111111111"
        conversation_b = "22222222-2222-4222-8222-222222222222"

        process_message(
            "工程.pdf V2",
            "project-a",
            FinalLLM(),
            document_resolver=self.resolver,
            user_id=user_id,
            conversation_id=conversation_a,
        )
        process_message(
            "说明书.pdf",
            "project-a",
            FinalLLM(),
            document_resolver=self.resolver,
            user_id=user_id,
            conversation_id=conversation_b,
        )

        document_a = _AGENT_CONTEXTS[(user_id, "project-a", conversation_a)].last_referenced_document
        document_b = _AGENT_CONTEXTS[(user_id, "project-a", conversation_b)].last_referenced_document
        self.assertEqual(
            (
                document_a.file_id,
                document_a.original_filename,
                document_a.document_version,
                document_a.is_current,
            ),
            ("a-v2", "工程.pdf", 2, True),
        )
        self.assertEqual(document_b.file_id, "b-v1")

    def test_contexts_are_isolated_by_user_for_same_project_and_conversation(self):
        conversation_id = "33333333-3333-4333-8333-333333333333"
        process_message(
            "工程.pdf V2",
            "project-a",
            FinalLLM(),
            document_resolver=self.resolver,
            user_id="user-a",
            conversation_id=conversation_id,
        )

        provider = FinalLLM()
        result = process_message(
            "刚才那个文件",
            "project-a",
            provider,
            document_resolver=self.resolver,
            user_id="user-b",
            conversation_id=conversation_id,
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertIn("先指定一下文档", result["reply"])
        self.assertIsNone(
            _AGENT_CONTEXTS[("user-b", "project-a", conversation_id)].last_referenced_document
        )
        self.assertEqual(provider.calls, [])

    def test_contexts_are_isolated_by_project_for_same_user_and_conversation(self):
        user_id = "user-a"
        conversation_id = "44444444-4444-4444-8444-444444444444"
        process_message(
            "工程.pdf V2",
            "project-a",
            FinalLLM(),
            document_resolver=self.resolver,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        project_b_resolver = SpyResolver([
            record(
                "project-b-file",
                "项目B.pdf",
                1,
                "2026-09-05T00:00:00+00:00",
                project="project-b",
            ),
        ])

        provider = FinalLLM()
        result = process_message(
            "刚才那个文件",
            "project-b",
            provider,
            document_resolver=project_b_resolver,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertIn("先指定一下文档", result["reply"])
        self.assertIsNone(
            _AGENT_CONTEXTS[(user_id, "project-b", conversation_id)].last_referenced_document
        )
        self.assertEqual(provider.calls, [])

    def test_same_user_project_and_conversation_reuses_last_document(self):
        user_id = "user-a"
        conversation_id = "55555555-5555-4555-8555-555555555555"
        process_message(
            "工程.pdf V2",
            "project-a",
            FinalLLM(),
            document_resolver=self.resolver,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        provider = FinalLLM("继续使用工程文档")
        result = process_message(
            "刚才那个文件",
            "project-a",
            provider,
            document_resolver=self.resolver,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        self.assertEqual(result["reply"], "继续使用工程文档")
        self.assertEqual(
            self.resolver.calls[-1][2]["previous_document"].file_id,
            "a-v2",
        )
        self.assertEqual(
            _AGENT_CONTEXTS[(user_id, "project-a", conversation_id)]
            .last_referenced_document.file_id,
            "a-v2",
        )

    def test_contextual_reference_without_history_does_not_fall_back_to_project_rag(self):
        for index, query in enumerate(("刚才那个文件", "这份文件", "它"), start=1):
            with self.subTest(query=query):
                provider = FinalLLM()
                result = process_message(
                    query,
                    "project-a",
                    provider,
                    document_resolver=self.resolver,
                    user_id="user-a",
                    conversation_id=f"66666666-6666-4666-8666-{index:012d}",
                )

                self.assertEqual(result["status"], "no_evidence")
                self.assertEqual(result["citations"], [])
                self.assertEqual(result["sources"], [])
                self.assertIn("先指定一下文档", result["reply"])
                self.assertEqual(provider.calls, [])

    def test_ordinary_question_does_not_call_resolver(self):
        provider = FinalLLM("普通回答")
        result = process_message("这个项目目前有哪些资料？", "project-a", provider, document_resolver=self.resolver, agent_context=AgentContext())
        self.assertEqual(result["reply"], "普通回答")
        self.assertEqual(self.resolver.calls, [])

    def test_page_number_with_unresolved_file_reference_keeps_page_guard(self):
        provider = FinalLLM()
        result = process_message(
            "第3页那个文件", "project-a", provider,
            document_resolver=self.resolver, agent_context=AgentContext(),
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertIn("先指定一下文档", result["reply"])
        self.assertEqual(self.resolver.calls, [])
        self.assertEqual(provider.calls, [])

    def test_resolved_document_constraints_override_llm_tool_arguments(self):
        from app.tools import project_documents

        retrieval = CapturingRetrievalService()
        original = project_documents._retrieval_service
        project_documents._retrieval_service = retrieval
        try:
            provider = ToolThenFinalLLM({"query": "融资计划", "document_version": 1, "original_filename": "工程.pdf"})
            context = AgentContext()
            result = process_message("第二版工程.pdf的融资计划是什么？", "project-a", provider,
                                     document_resolver=self.resolver, agent_context=context)
            self.assertEqual(result["status"], "no_evidence")
            self.assertIn("没有找到足够依据", result["reply"])
            self.assertEqual(len(retrieval.calls), 1)
            self.assertEqual(retrieval.calls[0]["file_id"], "a-v2")
            self.assertEqual(retrieval.calls[0]["document_version"], 2)
            self.assertEqual(retrieval.calls[0]["original_filename"], "工程.pdf")
        finally:
            project_documents._retrieval_service = original

    def test_resolved_document_is_injected_when_llm_omits_selectors(self):
        from app.tools import project_documents

        retrieval = CapturingRetrievalService()
        original = project_documents._retrieval_service
        project_documents._retrieval_service = retrieval
        try:
            provider = ToolThenFinalLLM({"query": "融资计划"})
            context = AgentContext()
            process_message("工程.pdf V2", "project-a", provider,
                            document_resolver=self.resolver, agent_context=context)
            self.assertEqual(retrieval.calls[0]["file_id"], "a-v2")
            self.assertEqual(retrieval.calls[0]["document_version"], 2)
        finally:
            project_documents._retrieval_service = original

    def test_contextual_reference_reuses_document_for_rag(self):
        from app.tools import project_documents

        retrieval = CapturingRetrievalService()
        original = project_documents._retrieval_service
        project_documents._retrieval_service = retrieval
        try:
            context = AgentContext()
            process_message("工程.pdf V2", "project-a", FinalLLM(), document_resolver=self.resolver, agent_context=context)
            provider = ToolThenFinalLLM({"query": "融资计划"})
            process_message("刚才那个的融资计划", "project-a", provider,
                            document_resolver=self.resolver, agent_context=context)
            self.assertEqual(retrieval.calls[-1]["file_id"], "a-v2")
            self.assertEqual(retrieval.calls[-1]["document_version"], 2)
        finally:
            project_documents._retrieval_service = original
    def test_no_internal_ids_in_resolution_prompts_or_replies(self):
        provider = FinalLLM("根据文档可以回答。")
        context = AgentContext()
        result = process_message("工程.pdf V2", "project-a", provider, document_resolver=self.resolver, agent_context=context)
        self.assertNotIn("file_id", result["reply"])
        self.assertNotIn("chunk_id", result["reply"])
        self.assertNotIn("score", result["reply"])
    def test_resolved_v2_page_range_is_injected_into_document_search(self):
        from app.tools import project_documents

        records = [
            {**record("page-v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=False), "file_type": "pdf", "display_page_mapping": {"1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7}},
            {**record("page-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00"), "file_type": "pdf", "display_page_mapping": {"1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10}},
        ]
        resolver = DocumentResolver(records)
        retrieval = CapturingRetrievalService()
        original = project_documents._retrieval_service
        project_documents._retrieval_service = retrieval
        try:
            provider = ToolThenFinalLLM({"query": "工程项目清单"})
            process_message("工程.pdf V2最后两页的清单", "project-a", provider, document_resolver=resolver, agent_context=AgentContext())
            self.assertEqual(retrieval.calls[0]["file_id"], "page-v2")
            self.assertEqual(retrieval.calls[0]["document_version"], 2)
            self.assertEqual(retrieval.calls[0]["page_numbers"], [9, 10])
        finally:
            project_documents._retrieval_service = original

    def test_last_pages_without_document_do_not_guess_a_candidate(self):
        provider = FinalLLM()
        result = process_message("最后两页有哪些内容？", "project-a", provider, document_resolver=self.resolver, agent_context=AgentContext())
        self.assertIn("先指定一下文档", result["reply"])
        self.assertEqual(provider.calls, [])
    def test_page_reference_without_reliable_mapping_stops_before_llm(self):
        resolver = DocumentResolver([
            {**record("unmapped-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00"), "file_type": "pdf"},
        ])
        provider = FinalLLM()
        result = process_message(
            "工程.pdf V2第8页有什么内容？", "project-a", provider,
            document_resolver=resolver, agent_context=AgentContext(),
        )
        self.assertIn("可靠页码信息", result["reply"])
        self.assertEqual(provider.calls, [])
    def test_llm_tool_context_uses_display_pages_not_physical_pages(self):
        from app.services.retrieval import RetrievalResult
        from app.tools import project_documents

        mapping = {str(display): display + 1 for display in range(1, 10)}
        resolver = DocumentResolver([
            {
                **record("display-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00"),
                "file_type": "pdf",
                "display_page_mapping": mapping,
            },
        ])

        class ResultsRetrievalService:
            def __init__(self):
                self.calls = []

            def retrieve(self, **kwargs):
                self.calls.append(kwargs)
                return [
                    RetrievalResult(
                        chunk_id="physical-9", project_id="project-a", file_id="display-v2",
                        text="第八页表格", score=0.9,
                        metadata={"original_filename": "工程.pdf", "document_version": 2, "is_current": True, "page_number": 9},
                    ),
                    RetrievalResult(
                        chunk_id="physical-10", project_id="project-a", file_id="display-v2",
                        text="第九页表格", score=0.8,
                        metadata={"original_filename": "工程.pdf", "document_version": 2, "is_current": True, "page_number": 10},
                    ),
                ]

        class ContextCheckingProvider:
            def __init__(self):
                self.calls = []
                self.step = 0

            def generate_with_tools(self, messages, tools):
                self.calls.append(messages)
                if self.step == 0:
                    self.step += 1
                    return LLMResponse(tool_calls=[ToolCall(tool="search_project_documents", arguments={"query": "工程项目清单"})])
                return LLMResponse(content="工程项目清单见第8、9页。")

        retrieval = ResultsRetrievalService()
        provider = ContextCheckingProvider()
        original = project_documents._retrieval_service
        project_documents._retrieval_service = retrieval
        try:
            result = process_message(
                "工程.pdf V2最后两页的工程项目清单", "project-a", provider,
                document_resolver=resolver, agent_context=AgentContext(),
            )
        finally:
            project_documents._retrieval_service = original

        tool_messages = [item for item in provider.calls[1] if item["role"] == "tool"]
        self.assertEqual(retrieval.calls[0]["page_numbers"], [9, 10])
        self.assertEqual(len(tool_messages), 1)
        context = tool_messages[0]["content"]
        self.assertIn('"display_page_number": 8', context)
        self.assertIn('"display_page_number": 9', context)
        self.assertNotIn('"page_number": 9', context)
        self.assertNotIn('"page_number": 10', context)
        self.assertEqual(result["reply"], "工程项目清单见第8、9页。")
        self.assertEqual([item["page_number"] for item in result["citations"]], [8, 9])

if __name__ == "__main__":
    unittest.main()



