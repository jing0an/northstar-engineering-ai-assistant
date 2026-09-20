import unittest

from app.services.document_resolver import (
    DocumentCandidate,
    DocumentResolver,
    chinese_number,
)


def record(file_id, filename, version, uploaded_at, project="project-a", current=None, **extra):
    value = {
        "file_id": file_id,
        "project_id": project,
        "original_filename": filename,
        "document_version": version,
        "uploaded_at": uploaded_at,
    }
    if current is not None:
        value["is_current"] = current
    value.update(extra)
    return value


class DocumentResolverTest(unittest.TestCase):
    def setUp(self):
        self.documents = [
            record("a-v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record("a-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00", current=True),
            record("b-v1", "说明书.pdf", 1, "2026-09-03T00:00:00+00:00", current=True),
            record("c-v1", "合同.docx", 1, "2026-09-04T00:00:00+00:00", current=True),
            record("d-v1", "附录.pdf", 1, "2026-09-05T00:00:00+00:00", current=True),
        ]
        self.resolver = DocumentResolver(self.documents)

    def assert_selected(self, resolution, file_id, version=None):
        self.assertEqual(resolution.status, "resolved")
        self.assertIsNotNone(resolution.selected_document)
        self.assertEqual(resolution.selected_document.file_id, file_id)
        if version is not None:
            self.assertEqual(resolution.selected_document.document_version, version)

    def test_chinese_number_helper(self):
        self.assertEqual(chinese_number("一"), 1)
        self.assertEqual(chinese_number("十"), 10)
        self.assertEqual(chinese_number("十一"), 11)
        self.assertEqual(chinese_number("二十"), 20)
        self.assertEqual(chinese_number("二十一"), 21)
        self.assertEqual(chinese_number("20"), 20)
        self.assertEqual(chinese_number("三十"), 30)
        self.assertEqual(chinese_number("三十一"), 31)
        self.assertEqual(chinese_number("一百"), 100)

    def test_v_version_boundaries_allow_chinese_context_but_reject_identifiers(self):
        for query, version in (
            ("V1", 1),
            ("V2", 2),
            ("v1", 1),
            ("V10", 10),
            ("V1主要", 1),
            ("V2工程", 2),
            ("V1，主要", 1),
            ("V1 主要", 1),
        ):
            with self.subTest(query=query):
                self.assertEqual(DocumentResolver._extract_version(query), version)

        for query in ("V1xxx", "V2_工程", "abcV10def"):
            with self.subTest(query=query):
                self.assertIsNone(DocumentResolver._extract_version(query))

    def test_filename_and_adjacent_v_version_resolve_together(self):
        docs = [
            record("a-v1", "工程项目AI助理测试.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record("a-v2", "工程项目AI助理测试.pdf", 2, "2026-09-02T00:00:00+00:00", current=True),
        ]
        resolver = DocumentResolver(docs)
        for query in (
            "《工程项目AI助理测试.pdf》V1主要讲了什么？",
            "《工程项目AI助理测试.pdf》V1，主要讲了什么？",
            "V1工程项目AI助理测试.pdf",
        ):
            with self.subTest(query=query):
                self.assert_selected(resolver.resolve(query, "project-a"), "a-v1", 1)
    def test_explicit_versions_and_arbitrary_n(self):
        docs = [record(f"v{i}", "工程.pdf", i, f"2026-09-{i:02d}T00:00:00+00:00", current=i == 20) for i in range(1, 21)]
        resolver = DocumentResolver(docs)
        for query, version in (("V1", 1), ("v5", 5), ("第十版", 10), ("版本 12", 12), ("第20版", 20)):
            with self.subTest(query=query):
                result = resolver.resolve(query, "project-a")
                self.assert_selected(result, f"v{version}", version)

    def test_filename_wins_over_contextual_reference(self):
        previous = record("b-v1", "说明书.pdf", 1, "2026-09-03T00:00:00+00:00", current=True)
        result = self.resolver.resolve("工程.pdf这个文件", "project-a", previous_document=previous)
        self.assert_selected(result, "a-v2", 2)
        self.assert_selected(self.resolver.resolve("工程.pdf第二版", "project-a", previous_document=previous), "a-v2", 2)
        self.assert_selected(self.resolver.resolve("第二版工程.pdf", "project-a"), "a-v2", 2)

    def test_latest_boundaries_with_multiple_current_documents(self):
        docs = [
            record("a-v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record("a-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00", current=True),
            record("b-v1", "说明书.pdf", 1, "2026-09-03T00:00:00+00:00", current=True),
            record("c-v1", "合同.pdf", 1, "2026-09-04T00:00:00+00:00", current=True),
        ]
        resolver = DocumentResolver(docs)
        self.assert_selected(resolver.resolve("工程.pdf", "project-a"), "a-v2", 2)
        self.assert_selected(resolver.resolve("最新版工程.pdf", "project-a"), "a-v2", 2)
        self.assertEqual(resolver.resolve("最新版", "project-a").status, "ambiguous")

    def test_recent_upload_respects_filename_and_ties_are_ambiguous(self):
        docs = [
            record("a-v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record("a-v2", "工程.pdf", 2, "2026-09-03T00:00:00+00:00", current=True),
            record("b-v1", "说明书.pdf", 1, "2026-09-02T00:00:00+00:00", current=True),
        ]
        resolver = DocumentResolver(docs)
        self.assert_selected(resolver.resolve("刚上传的工程.pdf", "project-a"), "a-v2", 2)
        tied = [
            record("a", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=True),
            record("b", "工程.pdf", 2, "2026-09-01T00:00:00+00:00", current=True),
        ]
        self.assertEqual(DocumentResolver(tied).resolve("刚上传的工程.pdf", "project-a").status, "ambiguous")

    def test_context_must_match_project(self):
        previous = record("other", "工程.pdf", 2, "2026-09-02T00:00:00+00:00", project="other-project", current=True)
        self.assertEqual(self.resolver.resolve("刚才那个", "project-a", previous_document=previous).status, "insufficient_context")

    def test_duplicate_explicit_version_is_ambiguous(self):
        docs = [
            record("a", "工程.pdf", 2, "2026-09-01T00:00:00+00:00", current=True),
            record("b", "工程.pdf", 2, "2026-09-02T00:00:00+00:00", current=True),
        ]
        result = DocumentResolver(docs).resolve("工程.pdf V2", "project-a")
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual({item.file_id for item in result.candidates}, {"a", "b"})
    def test_version_and_ordinal_are_distinct(self):
        result = self.resolver.resolve("第二版工程.pdf", "project-a")
        self.assert_selected(result, "a-v2", 2)
        result = self.resolver.resolve("第二个文件", "project-a")
        self.assert_selected(result, "b-v1", 1)

    def test_ordinal_orders_current_documents_by_uploaded_at(self):
        self.assert_selected(self.resolver.resolve("第一个文件", "project-a"), "a-v2")
        self.assert_selected(self.resolver.resolve("第二个文件", "project-a"), "b-v1")
        self.assert_selected(self.resolver.resolve("第三份 PDF", "project-a"), "d-v1")

    def test_latest_and_current(self):
        self.assert_selected(self.resolver.resolve("最新版工程.pdf", "project-a"), "a-v2", 2)
        self.assert_selected(self.resolver.resolve("工程.pdf", "project-a"), "a-v2", 2)
        self.assertEqual(self.resolver.resolve("最新版", "project-a").status, "ambiguous")

    def test_multiple_explicit_filenames_are_ambiguous(self):
        result = self.resolver.resolve(
            "比较 工程.pdf 和 说明书.pdf。它的第3页有什么区别？",
            "project-a",
        )
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.selected_document)
        self.assertEqual(
            {item.original_filename for item in result.candidates},
            {"工程.pdf", "说明书.pdf"},
        )

    def test_contextual_latest_and_current_are_scoped_to_context_filename(self):
        documents = [
            record("a-v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record("a-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00", current=False),
            record("a-v3", "工程.pdf", 3, "2026-09-03T00:00:00+00:00", current=True),
            record("b-v1", "说明书.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record("b-v2", "说明书.pdf", 2, "2026-09-02T00:00:00+00:00", current=False),
            record("b-v4", "说明书.pdf", 4, "2026-09-04T00:00:00+00:00", current=True),
        ]
        resolver = DocumentResolver(documents)
        context = next(item for item in resolver.documents if item.file_id == "a-v2")
        for query in ("最新版", "这个文件的最新版", "这个文件的当前版本", "现在这份文件的最新版", "现在这个版本"):
            with self.subTest(query=query):
                self.assert_selected(
                    resolver.resolve(query, "project-a", previous_document=context),
                    "a-v3",
                    3,
                )
        self.assertEqual(
            resolver.resolve("现在这个版本", "project-a").status,
            "insufficient_context",
        )

    def test_contextual_reference(self):
        previous = record("a-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00", current=True)
        for query in ("刚才那个", "这份文件", "这个文件", "刚才那份报告", "它", "上一个"):
            with self.subTest(query=query):
                self.assert_selected(
                    self.resolver.resolve(query, "project-a", previous_document=previous),
                    "a-v2",
                    2,
                )
                self.assertEqual(
                    self.resolver.resolve(query, "project-a").status,
                    "insufficient_context",
                )

    def test_previous_version_uses_context(self):
        current = record("a-v3", "工程.pdf", 3, "2026-09-03T00:00:00+00:00", current=True)
        docs = self.documents + [record("a-v3", "工程.pdf", 3, "2026-09-05T00:00:00+00:00", current=True)]
        resolver = DocumentResolver(docs)
        self.assert_selected(resolver.resolve("上一个版本", "project-a", previous_document=current), "a-v2", 2)
        first = record("a-v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=True)
        self.assertEqual(resolver.resolve("上一个版本", "project-a", previous_document=first).status, "not_found")
        self.assertEqual(resolver.resolve("上一个版本", "project-a").status, "insufficient_context")

    def test_previous_version_phrasings_use_context_and_do_not_fall_back_to_current(self):
        current = record("a-v4", "工程.pdf", 4, "2026-09-04T00:00:00+00:00", current=True)
        documents = [
            record("a-v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record("a-v2", "工程.pdf", 2, "2026-09-02T00:00:00+00:00", current=False),
            record("a-v3", "工程.pdf", 3, "2026-09-03T00:00:00+00:00", current=False),
            current,
        ]
        resolver = DocumentResolver(documents)
        for query in ("上一版", "上一版本", "上一个版本", "之前那个版本"):
            with self.subTest(query=query):
                self.assert_selected(
                    resolver.resolve(query, "project-a", previous_document=current),
                    "a-v3",
                    3,
                )
                self.assertEqual(resolver.resolve(query, "project-a").status, "insufficient_context")

        first = documents[0]
        for query in ("上一版", "上一版本", "上一个版本", "之前那个版本"):
            with self.subTest(query=query):
                self.assertEqual(
                    resolver.resolve(query, "project-a", previous_document=first).status,
                    "not_found",
                )

    def test_filename_version_combinations_scope_by_filename(self):
        docs = self.documents + [record("b-v2", "说明书.pdf", 2, "2026-09-05T00:00:00+00:00", current=True)]
        resolver = DocumentResolver(docs)
        self.assert_selected(resolver.resolve("工程.pdf V2", "project-a"), "a-v2", 2)
        self.assert_selected(resolver.resolve("第2版 说明书.pdf", "project-a"), "b-v2", 2)

    def test_page_feature_requires_reliable_metadata(self):
        result = self.resolver.resolve("带页码的那个", "project-a")
        self.assertEqual(result.status, "insufficient_context")
        docs = [
            record("p1", "带页码.pdf", 1, "2026-09-01T00:00:00+00:00", current=True, has_page_numbers=True),
            record("p2", "无页码.pdf", 1, "2026-09-02T00:00:00+00:00", current=True, has_page_numbers=False),
        ]
        resolver = DocumentResolver(docs)
        self.assert_selected(resolver.resolve("带页码的 PDF", "project-a"), "p1")
        self.assert_selected(resolver.resolve("没有页码的 PDF", "project-a"), "p2")

    def test_uploaded_at_reference(self):
        result = self.resolver.resolve("刚上传的那个", "project-a")
        self.assert_selected(result, "d-v1", 1)
        tied = [
            record("x", "x.pdf", 1, "2026-09-01T00:00:00+00:00", current=True),
            record("y", "y.pdf", 1, "2026-09-01T00:00:00+00:00", current=True),
        ]
        self.assertEqual(DocumentResolver(tied).resolve("刚上传的文件", "project-a").status, "ambiguous")

    def test_project_isolation_and_no_guessing(self):
        self.assertEqual(self.resolver.resolve("工程.pdf", "other-project").status, "not_found")
        self.assertEqual(self.resolver.resolve("那个文件", "project-a").status, "ambiguous")

    def test_unknown_explicit_filename_is_not_found_even_with_one_visible_document(self):
        documents = [record("only", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=True)]
        result = DocumentResolver(documents).resolve("不存在的测试文件999.pdf", "project-a")
        self.assertEqual(result.status, "not_found")
        self.assertIsNone(result.selected_document)

    def test_unknown_explicit_filename_is_not_found_with_multiple_documents(self):
        result = self.resolver.resolve("不存在的测试文件999.PDF", "project-a")
        self.assertEqual(result.status, "not_found")
        self.assertIsNone(result.selected_document)

    def test_unknown_explicit_docx_filename_is_not_found(self):
        for query in (
            "请查询不存在的测试文件999.docx",
            "请查询不存在的测试文件999.DOCX",
        ):
            with self.subTest(query=query):
                result = self.resolver.resolve(query, "project-a")
                self.assertEqual(result.status, "not_found")
                self.assertIsNone(result.selected_document)

    def test_project_level_query_without_filename_keeps_existing_resolution_behavior(self):
        result = self.resolver.resolve("当前项目资料中有什么内容", "project-a")
        self.assertEqual(result.status, "ambiguous")

    def test_resolution_contains_candidates_and_explanation(self):
        result = self.resolver.resolve("最新版", "project-a")
        self.assertEqual(result.status, "ambiguous")
        self.assertGreaterEqual(len(result.candidates), 2)
        self.assertTrue(result.explanation)
        self.assertTrue(all(isinstance(item, DocumentCandidate) for item in result.candidates))

    def test_duplicate_upload_is_excluded_from_business_candidates(self):
        docs = [
            record("v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=False),
            record(
                "duplicate", "工程.pdf", 99, "2026-09-02T00:00:00+00:00",
                current=True, is_duplicate=True, duplicate_of_file_id="v1",
            ),
            record("v2", "工程.pdf", 2, "2026-09-03T00:00:00+00:00", current=True),
            record("other", "说明书.pdf", 1, "2026-09-04T00:00:00+00:00", current=True),
        ]
        resolver = DocumentResolver(docs)
        self.assert_selected(resolver.resolve("工程.pdf", "project-a"), "v2", 2)
        self.assert_selected(resolver.resolve("工程.pdf V2", "project-a"), "v2", 2)
        self.assertEqual(resolver.resolve("工程.pdf V99", "project-a").status, "not_found")
        self.assert_selected(resolver.resolve("第二个文件", "project-a"), "other", 1)
        self.assertNotIn("duplicate", {item.file_id for item in resolver.resolve("最新版", "project-a").candidates})

    def test_duplicate_fields_are_backward_compatible(self):
        candidate = DocumentCandidate.from_metadata(record(
            "v1", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=True,
        ))
        self.assertFalse(candidate.is_duplicate)
        self.assertIsNone(candidate.duplicate_of_file_id)

    def test_duplicate_reference_must_be_same_project_legal_file(self):
        with self.assertRaises(ValueError):
            DocumentResolver([
                record(
                    "duplicate", "工程.pdf", None, "2026-09-02T00:00:00+00:00",
                    current=False, is_duplicate=True, duplicate_of_file_id="missing",
                )
            ])
        with self.assertRaises(ValueError):
            DocumentResolver([
                record("original", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", project="project-a", current=True),
                record(
                    "duplicate", "工程.pdf", None, "2026-09-02T00:00:00+00:00",
                    project="project-b", current=False, is_duplicate=True, duplicate_of_file_id="original",
                ),
            ])
        with self.assertRaises(ValueError):
            DocumentResolver([
                record("original", "工程.pdf", 1, "2026-09-01T00:00:00+00:00", current=True),
                record(
                    "duplicate-1", "工程.pdf", None, "2026-09-02T00:00:00+00:00",
                    current=False, is_duplicate=True, duplicate_of_file_id="original",
                ),
                record(
                    "duplicate-2", "工程.pdf", None, "2026-09-03T00:00:00+00:00",
                    current=False, is_duplicate=True, duplicate_of_file_id="duplicate-1",
                ),
            ])


if __name__ == "__main__":
    unittest.main()
